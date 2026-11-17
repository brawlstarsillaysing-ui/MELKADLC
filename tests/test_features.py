import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from test_domain import deposit, setup_users, transaction

from backend import models as m
from backend import services as s
from backend.admin import execute
from backend.schemas import AdminAction
from backend.security import decrypt


@pytest.mark.parametrize("kind,value", [("license", "3600"), ("discount", "50"), ("extension", "3600")])
def test_promo_reward_types(kind, value):
    setup_users()
    lic = transaction(lambda db: s.trial(db, 2))
    activated = transaction(lambda db: s.activate(db, decrypt(lic.key_ciphertext), str(uuid.uuid4())))
    transaction(
        lambda db: execute(
            db,
            999,
            AdminAction(
                action="promo_create",
                target="SPECIAL",
                reward_type=kind,
                amount=value,
                expires_at=m.utcnow() + timedelta(days=1),
                max_uses=10,
                allowed_users=[2],
                reason="Feature test",
                request_key="promo",
            ),
        )
    )
    transaction(lambda db: s.redeem(db, 2, "SPECIAL", "redemption", lic.id))
    if kind == "license":
        assert transaction(lambda db: db.scalar(select(func.count()).select_from(m.License))) == 2
    elif kind == "discount":
        assert transaction(lambda db: s.quote(db, 2, "1")[2]) == Decimal("10")
        deposit(2, "20")
        transaction(lambda db: s.buy(db, 2, "1", "10", "purchase"))
        assert transaction(lambda db: s.quote(db, 2, "1")[2]) == Decimal("20")
        assert transaction(lambda db: db.get(m.Wallet, 1).bonus) == Decimal("3")
    else:
        assert transaction(lambda db: db.get(m.License, lic.id).expires_at) == activated[
            "expires_at"
        ] + timedelta(hours=1)
    with pytest.raises(s.Problem):
        transaction(lambda db: s.redeem(db, 1, "SPECIAL", "not-allowed"))


def test_block_suspend_and_changed_price():
    setup_users()
    key = transaction(lambda db: decrypt(s.trial(db, 2).key_ciphertext))
    activated = transaction(lambda db: s.activate(db, key, str(uuid.uuid4())))
    transaction(
        lambda db: execute(
            db,
            999,
            AdminAction(action="ban", target="user", user_id=2, reason="Account review", request_key="ban"),
        )
    )
    with pytest.raises(s.Problem) as exc:
        transaction(lambda db: s.status(db, activated["session_token"]))
    assert exc.value.code == "account_blocked"
    transaction(
        lambda db: execute(
            db,
            999,
            AdminAction(
                action="unban", target="user", user_id=2, reason="Review completed", request_key="unban"
            ),
        )
    )
    transaction(
        lambda db: execute(
            db,
            999,
            AdminAction(
                action="license_update",
                target=activated["id"],
                status="suspended",
                reason="Suspend license",
                request_key="suspend",
            ),
        )
    )
    with pytest.raises(s.Problem) as exc:
        transaction(lambda db: s.status(db, activated["session_token"]))
    assert exc.value.code == "key_blocked"
    deposit(2, "100")
    transaction(
        lambda db: execute(
            db,
            999,
            AdminAction(
                action="plan_update", target="1", amount="30", reason="New price", request_key="price"
            ),
        )
    )
    with pytest.raises(s.Problem) as exc:
        transaction(lambda db: s.buy(db, 2, "1", "20", "old-quote"))
    assert exc.value.code == "price_changed"
    assert transaction(lambda db: db.get(m.Wallet, 2).cash) == Decimal("100")


def test_admin_credit_is_not_external_revenue_and_is_idempotent():
    setup_users()
    command = AdminAction(
        action="adjust_balance",
        target="user",
        user_id=2,
        amount="50",
        reason="Courtesy credit",
        request_key="credit",
    )
    transaction(lambda db: execute(db, 999, command))
    transaction(lambda db: execute(db, 999, command))
    assert transaction(lambda db: db.get(m.Wallet, 2).bonus) == Decimal("50")
    assert transaction(lambda db: s.stats(db)["external_deposits"]) == 0
    transaction(lambda db: s.buy(db, 2, "1", "20", "bonus"))
    assert transaction(lambda db: db.get(m.Wallet, 1).bonus) == 0


def test_support_and_broadcast_preview_confirmation(client):
    from test_api_bot import auth

    client.post("/bot/4/register", json={}, headers=auth())
    ticket = client.post(
        "/bot/4/support", json={"text": "Help with activation", "file_id": "test-file"}, headers=auth()
    ).json()
    reply = client.post(
        "/admin/999/action",
        json={
            "action": "support_reply",
            "target": ticket["id"],
            "value": "Please try again",
            "reason": "Reply to ticket",
            "request_key": "reply",
        },
        headers=auth(),
    )
    assert reply.status_code == 200
    tickets = client.get("/bot/4/support", headers=auth()).json()
    assert tickets[0]["replies"] == ["Please try again"]
    draft = client.post(
        "/admin/999/action",
        json={
            "action": "broadcast_create",
            "target": "new",
            "value": "MELKADLC update",
            "reason": "Release announcement",
            "request_key": "draft",
        },
        headers=auth(),
    ).json()
    assert client.get("/worker/deliveries", headers=auth()).json() == []
    assert (
        client.post(
            "/admin/999/action",
            json={
                "action": "broadcast_confirm",
                "target": draft["id"],
                "reason": "Preview approved",
                "request_key": "send",
            },
            headers=auth(),
        ).status_code
        == 200
    )
    deliveries = client.get("/worker/deliveries", headers=auth()).json()
    assert len(deliveries) == 1 and deliveries[0]["user_id"] == 4
