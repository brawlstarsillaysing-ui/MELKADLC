import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import models as m
from backend import services as s
from backend.admin import execute
from backend.db import engine
from backend.schemas import AdminAction
from backend.security import decrypt


def transaction(fn):
    with Session(engine(), expire_on_commit=False) as db, db.begin():
        return fn(db)


def setup_users():
    def setup(db):
        s.seed(db)
        s.register(db, 1, "inviter")
        s.register(db, 2, "buyer", 1)
        db.add_all(
            [
                m.ApplicationSetting(key="payment_card", value="0000000000000000"),
                m.ApplicationSetting(key="payment_recipient", value="Test recipient"),
            ]
        )

    transaction(setup)


def deposit(uid, amount):
    def run(db):
        p = s.topup(db, uid, amount, str(uuid.uuid4()))
        s.decide_payment(db, 999, p.id, "confirmed")
        return p.id

    return transaction(run)


def test_trial_race_and_registration_persistence():
    setup_users()
    with ThreadPoolExecutor(max_workers=10) as pool:
        ids = list(pool.map(lambda _: transaction(lambda db: s.trial(db, 2).id), range(20)))
    assert len(set(ids)) == 1

    def check(db):
        s.register(db, 2, "changed_username", 1)
        assert db.get(m.TrialEntitlement, 2).issued == 1
        assert s.profile(db, 2)["trial_remaining"] == 4
        assert s.trial(db, 2).id == ids[0]

    transaction(check)


def test_five_sequential_trials_and_server_expiry():
    setup_users()
    for index in range(5):

        def activate(db):
            lic = s.trial(db, 2)
            assert db.get(m.TrialEntitlement, 2).issued == index + 1
            assert lic.expires_at is None
            result = s.activate(db, decrypt(lic.key_ciphertext), str(uuid.uuid4()))
            assert (lic.expires_at - lic.activated_at).total_seconds() == 86400
            return result["session_token"], lic.id

        token, lid = transaction(activate)

        def expire(db):
            lic = db.get(m.License, lid)
            lic.expires_at = m.utcnow() - timedelta(seconds=1)
            db.get(m.Subscription, lid).ends_at = lic.expires_at

        transaction(expire)
        with pytest.raises(s.Problem) as exc:
            transaction(lambda db: s.status(db, token))
        assert exc.value.code == "key_expired"
    with pytest.raises(s.Problem) as exc:
        transaction(lambda db: s.trial(db, 2))
    assert exc.value.code == "trial_exhausted"


def test_device_limit_race_reset_and_original_expiry():
    setup_users()
    key = transaction(lambda db: decrypt(s.trial(db, 2).key_ciphertext))

    def use(_):
        try:
            return transaction(lambda db: s.activate(db, key, str(uuid.uuid4())))
        except s.Problem as e:
            return e.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(use, range(8)))
    winners = [x for x in results if isinstance(x, dict)]
    assert len(winners) == 1
    assert results.count("device_limit_reached") == 7
    result = winners[0]
    original = result["expires_at"]
    transaction(lambda db: s.reset_device(db, 2, result["id"], "reset1"))
    transaction(lambda db: s.reset_device(db, 2, result["id"], "reset1"))
    with pytest.raises(s.Problem) as exc:
        transaction(lambda db: s.status(db, result["session_token"]))
    assert exc.value.code == "session_invalid"
    new = transaction(lambda db: s.activate(db, key, str(uuid.uuid4())))
    assert new["expires_at"] == original
    transaction(lambda db: s.reset_device(db, 2, result["id"], "reset2"))
    with pytest.raises(s.Problem) as exc:
        transaction(lambda db: s.reset_device(db, 2, result["id"], "reset3"))
    assert exc.value.code == "reset_limit_reached"


def test_payment_confirm_race_and_no_credit_for_rejection():
    setup_users()
    pid = transaction(lambda db: s.topup(db, 2, "100", "deposit1").id)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(lambda _: transaction(lambda db: s.decide_payment(db, 999, pid, "confirmed")), range(16))
        )

    def check(db):
        assert db.get(m.Wallet, 2).cash == Decimal("100")
        assert db.scalar(select(func.count()).select_from(m.WalletTransaction)) == 1
        p = s.topup(db, 2, "50", "deposit2")
        s.decide_payment(db, 999, p.id, "rejected")
        assert db.get(m.Wallet, 2).cash == Decimal("100")

    transaction(check)
    with pytest.raises(s.Problem) as exc:
        transaction(lambda db: s.decide_payment(db, 123, pid, "confirmed"))
    assert exc.value.status == 403


def test_purchase_idempotency_race_and_referral_cash_only():
    setup_users()
    deposit(2, "100")
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(
            pool.map(lambda _: transaction(lambda db: s.buy(db, 2, "7", "90", "same_order").id), range(16))
        )
    assert len(set(ids)) == 1

    def check(db):
        assert db.get(m.Wallet, 2).cash == Decimal("10")
        assert db.get(m.Wallet, 1).bonus == Decimal("27")
        assert db.scalar(select(func.count()).select_from(m.Purchase)) == 1
        assert db.scalar(select(func.count()).select_from(m.ReferralReward)) == 1

    transaction(check)


def test_concurrent_distinct_purchases_cannot_overdraw():
    setup_users()
    deposit(2, "20")

    def buy(i):
        try:
            return transaction(lambda db: s.buy(db, 2, "1", "20", str(i)).id)
        except s.Problem as e:
            return e.code

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(buy, range(6)))
    assert results.count("insufficient_balance") == 5
    assert transaction(lambda db: db.get(m.Wallet, 2).cash) == 0


def test_bonus_only_does_not_reward_and_refund_claws_back_spent_reward():
    setup_users()
    deposit(2, "100")
    transaction(lambda db: s.buy(db, 2, "7", "90", "order"))
    transaction(lambda db: s.buy(db, 1, "1", "20", "bonus-order"))
    purchase_id = transaction(lambda db: db.scalar(select(m.Purchase.id).where(m.Purchase.user_id == 2)))
    transaction(lambda db: s.refund(db, 999, purchase_id, "Customer return"))
    transaction(lambda db: s.refund(db, 999, purchase_id, "Duplicate return"))

    def check(db):
        assert db.get(m.Wallet, 2).cash == Decimal("100")
        assert db.get(m.Wallet, 1).bonus == 0
        assert db.get(m.Wallet, 1).bonus_debt == Decimal("20")
        assert s.stats(db)["external_deposits"] == Decimal("100")
        assert db.scalar(select(func.count()).select_from(m.ReferralReward)) == 1
        assert db.scalar(select(m.ReferralReward)).reversed

    transaction(check)


def test_promo_limit_concurrent_and_idempotent_credit():
    setup_users()

    def setup(db):
        s.register(db, 3)
        execute(
            db,
            999,
            AdminAction(
                action="promo_create",
                target="PROMO",
                reason="Test promotion",
                request_key="new-promo",
                reward_type="balance",
                amount="50",
                max_uses=1,
                expires_at=m.utcnow() + timedelta(days=1),
            ),
        )

    transaction(setup)

    def redeem(uid):
        try:
            return transaction(lambda db: s.redeem(db, uid, "promo", "redeem"))
        except s.Problem as e:
            return e.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(redeem, [2, 3]))
    assert sorted(results) == ["balance", "promo_limit_reached"]
    winner = 2 if results[0] == "balance" else 3
    assert redeem(winner) == "balance"
    assert transaction(lambda db: db.get(m.Wallet, winner).bonus) == Decimal("50")


def test_admin_extension_idempotency_and_audit():
    setup_users()
    lic = transaction(lambda db: s.issue(db, 2, "grant", 3600))
    cmd = AdminAction(
        action="license_update",
        target=lic.id,
        reason="One hour extension",
        delta_seconds=3600,
        request_key="extend-once",
    )
    transaction(lambda db: execute(db, 999, cmd))
    transaction(lambda db: execute(db, 999, cmd))
    assert transaction(lambda db: db.get(m.License, lic.id).duration_seconds) == 7200
    assert transaction(lambda db: db.scalar(select(func.count()).select_from(m.AuditLog))) == 1


def test_persistence_after_new_engine_connections():
    setup_users()
    key = transaction(lambda db: decrypt(s.trial(db, 2).key_ciphertext))
    token = transaction(lambda db: s.activate(db, key, str(uuid.uuid4()))["session_token"])
    engine().dispose()
    assert transaction(lambda db: s.status(db, token)["status"]) == "active"
    assert transaction(lambda db: db.get(m.TrialEntitlement, 2).issued) == 1
