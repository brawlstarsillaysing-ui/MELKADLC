"""Transactional domain operations shared by the API and Telegram bot.

PostgreSQL row locks serialize activations. A transaction advisory lock serializes
commerce mutations, including multi-wallet reversals, without lock-order deadlocks.
The lock is database-wide across workers; no process-local financial state exists.
"""

import secrets
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from backend import models as m
from backend.config import settings
from backend.security import decrypt, digest, encrypt, make_key

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


class Problem(Exception):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status


def money(value) -> Decimal:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount != amount.quantize(CENT) or abs(amount) > 1000000:
            raise ValueError()
        return amount.quantize(CENT)
    except Exception:
        raise Problem("invalid_amount") from None


def commerce(db: Session):
    db.execute(text("SELECT pg_advisory_xact_lock(1296387147)"))


def user(db, uid, allow_banned=False):
    row = db.get(m.User, uid)
    if not row:
        raise Problem("user_not_found", 404)
    if row.banned and not allow_banned:
        raise Problem("account_blocked", 403)
    return row


def admin(db, uid):
    row = db.get(m.AdminUser, uid)
    if not row or not row.active:
        raise Problem("admin_required", 403)


def audit(db, aid, action, target, detail=None):
    db.add(m.AuditLog(admin_id=aid, action=action, target=str(target), detail=detail or {}))


def register(db, uid, username=None, inviter_id=None):
    commerce(db)
    row = db.get(m.User, uid)
    if row:
        row.username = username
        return row
    row = m.User(id=uid, username=username)
    db.add(row)
    db.flush()
    db.add_all([m.Wallet(user_id=uid), m.UserSettings(user_id=uid), m.TrialEntitlement(user_id=uid)])
    # Referrer must already exist. The relation is immutable after first registration.
    if inviter_id and inviter_id != uid and db.get(m.User, inviter_id):
        db.add(m.Referral(user_id=uid, inviter_id=inviter_id))
    db.flush()
    return row


def ledger(db, wallet, cash, bonus, debt, event, reason):
    wallet.cash += cash
    wallet.bonus += bonus
    wallet.bonus_debt += debt
    db.add(
        m.WalletTransaction(
            user_id=wallet.user_id,
            cash_delta=cash,
            bonus_delta=bonus,
            debt_delta=debt,
            event=event,
            reason=reason,
        )
    )


def bonus_credit(db, wallet, amount, event, reason):
    paid_debt = min(wallet.bonus_debt, amount)
    ledger(db, wallet, ZERO, amount - paid_debt, -paid_debt, event, reason)


def issue(db, uid, kind, duration, device_limit=1):
    key = make_key()
    lic = m.License(
        user_id=uid,
        key_hash=digest(key),
        key_ciphertext=encrypt(key),
        kind=kind,
        duration_seconds=duration,
        device_limit=device_limit,
    )
    db.add(lic)
    db.flush()
    return lic


def effective_status(lic):
    if lic.status in {"revoked", "suspended"}:
        return lic.status
    if lic.expires_at and lic.expires_at <= m.utcnow():
        return "expired"
    return lic.status


def license_view(lic, reveal=False):
    result = {
        "id": lic.id,
        "kind": lic.kind,
        "status": effective_status(lic),
        "duration_seconds": lic.duration_seconds,
        "activated_at": lic.activated_at,
        "expires_at": lic.expires_at,
        "created_at": lic.created_at,
        "device_limit": lic.device_limit,
        "resets": lic.resets,
        "server_time": m.utcnow(),
    }
    if reveal:
        result["key"] = decrypt(lic.key_ciphertext)
    return result


def trial(db, uid):
    commerce(db)
    user(db, uid)
    ent = db.get(m.TrialEntitlement, uid)
    # An unactivated trial also occupies the single slot; it cannot be stockpiled.
    current = db.scalars(
        select(m.License).where(
            m.License.user_id == uid,
            m.License.kind == "trial",
            m.License.status.in_(["available", "active", "suspended"]),
            (m.License.expires_at.is_(None)) | (m.License.expires_at > m.utcnow()),
        )
    ).first()
    if current:
        return current
    if ent.issued >= 5:
        raise Problem("trial_exhausted")
    lic = issue(db, uid, "trial", 86400)
    ent.issued += 1
    return lic


def activate(db, key, device_id):
    lic = db.scalar(select(m.License).where(m.License.key_hash == digest(key)).with_for_update())
    if not lic:
        raise Problem("key_not_found", 404)
    user(db, lic.user_id)
    state = effective_status(lic)
    if state in {"revoked", "suspended"}:
        raise Problem("key_blocked", 403)
    if state == "expired":
        raise Problem("key_expired", 403)
    device_hash = digest("device:" + device_id)
    binding = db.scalar(
        select(m.DeviceBinding).where(
            m.DeviceBinding.license_id == lic.id, m.DeviceBinding.device_hash == device_hash
        )
    )
    if not binding:
        count = db.scalar(
            select(func.count()).select_from(m.DeviceBinding).where(m.DeviceBinding.license_id == lic.id)
        )
        if count >= lic.device_limit:
            raise Problem("device_limit_reached", 409)
        binding = m.DeviceBinding(license_id=lic.id, device_hash=device_hash)
        db.add(binding)
    if not lic.activated_at:
        lic.activated_at = m.utcnow()
        lic.expires_at = lic.activated_at + timedelta(seconds=lic.duration_seconds)
        lic.status = "active"
        db.add(m.Subscription(license_id=lic.id, starts_at=lic.activated_at, ends_at=lic.expires_at))
    token = secrets.token_urlsafe(32)
    binding.token_hash = digest("session:" + token)
    db.add(m.Activation(license_id=lic.id, device_hash=device_hash, action="activate"))
    db.flush()
    return {**license_view(lic), "session_token": token}


def status(db, token):
    binding = db.scalar(
        select(m.DeviceBinding).where(m.DeviceBinding.token_hash == digest("session:" + token))
    )
    if not binding:
        raise Problem("session_invalid", 401)
    lic = db.get(m.License, binding.license_id)
    user(db, lic.user_id)
    state = effective_status(lic)
    if state in {"revoked", "suspended"}:
        raise Problem("key_blocked", 403)
    if state == "expired":
        raise Problem("key_expired", 403)
    return license_view(lic)


def owned_license(db, uid, lid, lock=False):
    query = select(m.License).where(m.License.id == lid)
    lic = db.scalar(query.with_for_update() if lock else query)
    if not lic or lic.user_id != uid:
        raise Problem("license_not_found", 404)
    return lic


def reset_device(db, uid, lid, request_key, aid=None):
    commerce(db)
    if aid is not None:
        admin(db, aid)
    else:
        user(db, uid)
    lic = owned_license(db, uid, lid, lock=True)
    event = f"reset:{request_key}"
    if db.scalar(select(m.Activation.id).where(m.Activation.license_id == lid, m.Activation.action == event)):
        return lic
    limit = int(setting(db, "self_reset_limit", "2"))
    if aid is None and lic.resets >= limit:
        raise Problem("reset_limit_reached")
    db.execute(delete(m.DeviceBinding).where(m.DeviceBinding.license_id == lid))
    if aid is None:
        lic.resets += 1
    db.add(m.Activation(license_id=lid, action=event))
    if aid is not None:
        audit(db, aid, "device_reset", lid)
    return lic


def setting(db, key, default=""):
    row = db.get(m.ApplicationSetting, key)
    return row.value if row else default


def topup(db, uid, amount, request_key):
    commerce(db)
    user(db, uid)
    amount = money(amount)
    if amount < 1 or amount > 100000:
        raise Problem("invalid_amount")
    if not setting(db, "payment_recipient") or not setting(db, "payment_card"):
        raise Problem("payments_not_configured", 503)
    existing = db.scalar(
        select(m.PaymentRequest).where(
            m.PaymentRequest.user_id == uid, m.PaymentRequest.request_key == request_key
        )
    )
    if existing:
        if existing.amount != amount:
            raise Problem("idempotency_conflict", 409)
        return existing
    pending = db.scalar(
        select(func.count())
        .select_from(m.PaymentRequest)
        .where(m.PaymentRequest.user_id == uid, m.PaymentRequest.status == "pending")
    )
    if pending >= 3:
        raise Problem("too_many_pending_payments")
    row = m.PaymentRequest(user_id=uid, amount=amount, request_key=request_key)
    db.add(row)
    db.flush()
    return row


def evidence(db, uid, pid, file_id, media_type):
    commerce(db)
    user(db, uid)
    row = db.get(m.PaymentRequest, pid)
    if not row or row.user_id != uid:
        raise Problem("payment_not_found", 404)
    if row.status != "pending":
        raise Problem("payment_already_processed", 409)
    existing = db.scalar(
        select(m.PaymentEvidence).where(
            m.PaymentEvidence.payment_id == pid, m.PaymentEvidence.file_id == file_id
        )
    )
    if not existing:
        db.add(m.PaymentEvidence(payment_id=pid, file_id=file_id, media_type=media_type))
    return row


def decide_payment(db, aid, pid, decision):
    commerce(db)
    admin(db, aid)
    row = db.get(m.PaymentRequest, pid)
    if not row:
        raise Problem("payment_not_found", 404)
    if row.status != "pending":
        if row.status != decision:
            raise Problem("payment_already_processed", 409)
        return row
    row.status, row.decided_by, row.decided_at = decision, aid, m.utcnow()
    if decision == "confirmed":
        wallet = db.get(m.Wallet, row.user_id)
        ledger(db, wallet, row.amount, ZERO, ZERO, "deposit:" + row.id, "Confirmed external UAH deposit")
    audit(db, aid, "payment_" + decision, pid, {"amount": str(row.amount)})
    return row


def quote(db, uid, plan_id):
    user(db, uid)
    plan = db.get(m.Plan, plan_id)
    if not plan or not plan.active:
        raise Problem("plan_unavailable", 404)
    # Discount redemptions are single-use purchase entitlements, valid until code expiry.
    discount = db.execute(
        select(m.PromoRedemption, m.PromoCode)
        .join(m.PromoCode, m.PromoRedemption.promo_id == m.PromoCode.id)
        .where(
            m.PromoRedemption.user_id == uid,
            m.PromoRedemption.consumed.is_(False),
            m.PromoCode.reward_type == "discount",
            m.PromoCode.active.is_(True),
            m.PromoCode.expires_at > m.utcnow(),
        )
        .order_by(m.PromoCode.value.desc())
    ).first()
    percent = min(discount[1].value, Decimal(100)) if discount else ZERO
    price = (plan.price * (1 - percent / 100)).quantize(CENT, rounding=ROUND_HALF_UP)
    wallet = db.get(m.Wallet, uid)
    return plan, discount, price, wallet


def buy(db, uid, plan_id, expected_amount, request_key):
    commerce(db)
    user(db, uid)
    previous = db.scalar(
        select(m.Purchase).where(m.Purchase.user_id == uid, m.Purchase.request_key == request_key)
    )
    if previous:
        if previous.plan_id != plan_id or previous.amount != money(expected_amount):
            raise Problem("idempotency_conflict", 409)
        if previous.status != "confirmed":
            raise Problem("purchase_refunded", 409)
        return db.get(m.License, previous.license_id)
    plan, discount, price, wallet = quote(db, uid, plan_id)
    if price != money(expected_amount):
        raise Problem("price_changed", 409)
    if wallet.bonus_debt > 0:
        raise Problem("bonus_debt_outstanding")
    if wallet.cash + wallet.bonus < price:
        raise Problem("insufficient_balance")
    # Spend bonus first. Only the actual cash-funded part generates referral revenue.
    bonus = min(wallet.bonus, price)
    cash = price - bonus
    lic = issue(db, uid, "paid", plan.duration_seconds)
    purchase = m.Purchase(
        user_id=uid,
        plan_id=plan.id,
        license_id=lic.id,
        amount=price,
        cash_spent=cash,
        bonus_spent=bonus,
        request_key=request_key,
    )
    db.add(purchase)
    db.flush()
    ledger(db, wallet, -cash, -bonus, ZERO, "purchase:" + purchase.id, "Subscription purchase UAH")
    if discount:
        discount[0].consumed = True
    referral = db.get(m.Referral, uid)
    if referral and cash > 0:
        reward = (cash * Decimal("0.30")).quantize(CENT, rounding=ROUND_HALF_UP)
        db.add(m.ReferralReward(purchase_id=purchase.id, user_id=referral.inviter_id, amount=reward))
        bonus_credit(
            db,
            db.get(m.Wallet, referral.inviter_id),
            reward,
            "referral:" + purchase.id,
            "30% of confirmed cash-funded purchase",
        )
    return lic


def refund(db, aid, purchase_id, reason):
    commerce(db)
    admin(db, aid)
    purchase = db.get(m.Purchase, purchase_id)
    if not purchase:
        raise Problem("purchase_not_found", 404)
    if purchase.status == "refunded":
        return
    lic = db.scalar(select(m.License).where(m.License.id == purchase.license_id).with_for_update())
    lic.status = "revoked"
    purchase.status = "refunded"
    wallet = db.get(m.Wallet, purchase.user_id)
    ledger(db, wallet, purchase.cash_spent, ZERO, ZERO, "refund-cash:" + purchase.id, reason)
    bonus_credit(db, wallet, purchase.bonus_spent, "refund-bonus:" + purchase.id, reason)
    reward = db.scalar(select(m.ReferralReward).where(m.ReferralReward.purchase_id == purchase.id))
    if reward and not reward.reversed:
        inviter_wallet = db.get(m.Wallet, reward.user_id)
        available = min(inviter_wallet.bonus, reward.amount)
        ledger(
            db,
            inviter_wallet,
            ZERO,
            -available,
            reward.amount - available,
            "referral-reversal:" + purchase.id,
            reason,
        )
        reward.reversed = True
    audit(db, aid, "purchase_refund", purchase_id, {"reason": reason})


def redeem(db, uid, code, request_key, license_id=None):
    commerce(db)
    user(db, uid)
    previous = db.scalar(
        select(m.PromoRedemption).where(
            m.PromoRedemption.user_id == uid, m.PromoRedemption.request_key == request_key
        )
    )
    promo = db.scalar(select(m.PromoCode).where(m.PromoCode.code == code.upper()))
    if previous:
        if not promo or previous.promo_id != promo.id:
            raise Problem("idempotency_conflict", 409)
        return promo.reward_type
    if not promo or not promo.active or promo.expires_at <= m.utcnow():
        raise Problem("promo_unavailable")
    if promo.allowed_users and uid not in promo.allowed_users:
        raise Problem("promo_unavailable")
    used = db.scalar(
        select(func.count())
        .select_from(m.PromoRedemption)
        .where(m.PromoRedemption.user_id == uid, m.PromoRedemption.promo_id == promo.id)
    )
    if used >= promo.per_user_limit or promo.uses >= promo.max_uses:
        raise Problem("promo_limit_reached")
    red = m.PromoRedemption(promo_id=promo.id, user_id=uid, request_key=request_key)
    db.add(red)
    db.flush()
    promo.uses += 1
    if promo.reward_type == "balance":
        bonus_credit(db, db.get(m.Wallet, uid), promo.value, "promo:" + red.id, "Promotional UAH credit")
    elif promo.reward_type == "license":
        issue(db, uid, "promo", int(promo.value))
    elif promo.reward_type == "extension":
        lic = owned_license(db, uid, license_id, lock=True)
        if effective_status(lic) != "active":
            raise Problem("active_license_required")
        lic.expires_at += timedelta(seconds=int(promo.value))
        db.get(m.Subscription, lic.id).ends_at = lic.expires_at
    return promo.reward_type


def profile(db, uid):
    row = user(db, uid, allow_banned=True)
    wallet = db.get(m.Wallet, uid)
    ref_count = db.scalar(select(func.count()).select_from(m.Referral).where(m.Referral.inviter_id == uid))
    earned = db.scalar(
        select(func.coalesce(func.sum(m.ReferralReward.amount), 0)).where(
            m.ReferralReward.user_id == uid, m.ReferralReward.reversed.is_(False)
        )
    )
    paid = db.scalar(
        select(func.coalesce(func.sum(m.Purchase.amount), 0)).where(
            m.Purchase.user_id == uid, m.Purchase.status == "confirmed"
        )
    )
    count = db.scalar(
        select(func.count())
        .select_from(m.Purchase)
        .where(m.Purchase.user_id == uid, m.Purchase.status == "confirmed")
    )
    active = db.scalar(
        select(func.count())
        .select_from(m.License)
        .where(m.License.user_id == uid, m.License.status == "active", m.License.expires_at > m.utcnow())
    )
    issued = db.get(m.TrialEntitlement, uid).issued
    activated = db.scalar(
        select(func.count())
        .select_from(m.License)
        .where(m.License.user_id == uid, m.License.kind == "trial", m.License.activated_at.is_not(None))
    )
    paying_refs = db.scalar(
        select(func.count(func.distinct(m.Purchase.user_id)))
        .join(m.Referral, m.Purchase.user_id == m.Referral.user_id)
        .where(m.Referral.inviter_id == uid, m.Purchase.status == "confirmed", m.Purchase.cash_spent > 0)
    )
    return {
        "telegram_id": uid,
        "username": row.username,
        "registered_at": row.created_at,
        "banned": row.banned,
        "cash": wallet.cash,
        "bonus": wallet.bonus,
        "bonus_debt": wallet.bonus_debt,
        "balance": wallet.cash + wallet.bonus,
        "referral_earned": earned,
        "referral_count": ref_count,
        "paying_referrals": paying_refs,
        "purchase_count": count,
        "purchase_total": paid,
        "active_subscriptions": active,
        "trial_issued": issued,
        "trial_used": activated,
        "trial_remaining": 5 - issued,
        "language": db.get(m.UserSettings, uid).language,
    }


def seed(db):
    commerce(db)
    for key in ["payment_card", "payment_recipient"]:
        value = getattr(settings(), key)
        if value and not db.get(m.ApplicationSetting, key):
            db.add(m.ApplicationSetting(key=key, value=value))
    for uid in settings().administrators:
        if not db.get(m.AdminUser, uid):
            db.add(m.AdminUser(user_id=uid))
    for days, price in [(1, "20"), (7, "90"), (30, "250"), (90, "600")]:
        if not db.get(m.Plan, str(days)):
            db.add(
                m.Plan(id=str(days), name=f"{days} d", duration_seconds=days * 86400, price=Decimal(price))
            )


def stats(db):
    def total(model, column, *conditions):
        return db.scalar(select(func.coalesce(func.sum(column), 0)).select_from(model).where(*conditions))

    return {
        "users": db.scalar(select(func.count()).select_from(m.User)),
        "external_deposits": total(
            m.PaymentRequest, m.PaymentRequest.amount, m.PaymentRequest.status == "confirmed"
        ),
        "sales": total(m.Purchase, m.Purchase.amount, m.Purchase.status == "confirmed"),
        "sales_cash": total(m.Purchase, m.Purchase.cash_spent, m.Purchase.status == "confirmed"),
        "sales_bonus": total(m.Purchase, m.Purchase.bonus_spent, m.Purchase.status == "confirmed"),
        "referral_rewards": total(
            m.ReferralReward, m.ReferralReward.amount, m.ReferralReward.reversed.is_(False)
        ),
        "pending_payments": db.scalar(
            select(func.count()).select_from(m.PaymentRequest).where(m.PaymentRequest.status == "pending")
        ),
    }
