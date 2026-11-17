"""PostgreSQL persistence. Money is NUMERIC, timestamps are timezone-aware UTC."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Row:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    banned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserSettings(Base):
    __tablename__ = "user_settings"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    language: Mapped[str] = mapped_column(String(2), default="ru")
    __table_args__ = (CheckConstraint("language IN ('ru','uk','en')"),)


class TrialEntitlement(Base):
    __tablename__ = "trial_entitlements"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    issued: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (CheckConstraint("issued >= 0 AND issued <= 5"),)


class Wallet(Base):
    __tablename__ = "wallets"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    cash: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    bonus: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    bonus_debt: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    __table_args__ = (CheckConstraint("cash >= 0 AND bonus >= 0 AND bonus_debt >= 0"),)


class WalletTransaction(Row, Base):
    __tablename__ = "wallet_transactions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    cash_delta: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    bonus_delta: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    debt_delta: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    event: Mapped[str] = mapped_column(String(150), unique=True)
    reason: Mapped[str] = mapped_column(String(500))


class Plan(Base):
    __tablename__ = "subscription_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    duration_seconds: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("price > 0 AND duration_seconds > 0"),)


class License(Row, Base):
    __tablename__ = "licenses"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    key_ciphertext: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))
    duration_seconds: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="available")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    device_limit: Mapped[int] = mapped_column(Integer, default=1)
    resets: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        CheckConstraint("duration_seconds > 0 AND device_limit BETWEEN 1 AND 100 AND resets >= 0"),
        CheckConstraint("status IN ('available','active','suspended','revoked')"),
        CheckConstraint("kind IN ('trial','paid','grant','promo')"),
    )


class DeviceBinding(Row, Base):
    __tablename__ = "device_bindings"
    license_id: Mapped[str] = mapped_column(ForeignKey("licenses.id"), index=True)
    device_hash: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    __table_args__ = (UniqueConstraint("license_id", "device_hash"),)


class Activation(Row, Base):
    __tablename__ = "license_activations"
    license_id: Mapped[str] = mapped_column(ForeignKey("licenses.id"), index=True)
    device_hash: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(100))


class Subscription(Base):
    __tablename__ = "subscriptions"
    license_id: Mapped[str] = mapped_column(ForeignKey("licenses.id"), primary_key=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PaymentRequest(Row, Base):
    __tablename__ = "payment_requests"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    request_key: Mapped[str] = mapped_column(String(100))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[int | None] = mapped_column(BigInteger)
    __table_args__ = (
        UniqueConstraint("user_id", "request_key"),
        CheckConstraint("amount > 0"),
        CheckConstraint("status IN ('pending','confirmed','rejected')"),
    )


class PaymentEvidence(Row, Base):
    __tablename__ = "payment_evidence"
    payment_id: Mapped[str] = mapped_column(ForeignKey("payment_requests.id"), index=True)
    file_id: Mapped[str] = mapped_column(String(512))
    media_type: Mapped[str] = mapped_column(String(20))
    __table_args__ = (UniqueConstraint("payment_id", "file_id"),)


class Purchase(Row, Base):
    __tablename__ = "purchases"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("subscription_plans.id"))
    license_id: Mapped[str] = mapped_column(ForeignKey("licenses.id"), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    cash_spent: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    bonus_spent: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    request_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default="confirmed")
    __table_args__ = (
        UniqueConstraint("user_id", "request_key"),
        CheckConstraint("amount = cash_spent + bonus_spent AND amount >= 0"),
    )


class Referral(Base):
    __tablename__ = "referrals"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    inviter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    __table_args__ = (CheckConstraint("user_id != inviter_id"),)


class ReferralReward(Row, Base):
    __tablename__ = "referral_rewards"
    purchase_id: Mapped[str] = mapped_column(ForeignKey("purchases.id"), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reversed: Mapped[bool] = mapped_column(Boolean, default=False)


class PromoCode(Row, Base):
    __tablename__ = "promo_codes"
    code: Mapped[str] = mapped_column(String(40), unique=True)
    reward_type: Mapped[str] = mapped_column(String(20))
    value: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int] = mapped_column(Integer)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    allowed_users: Mapped[list] = mapped_column(JSON, default=list)
    __table_args__ = (
        CheckConstraint("value > 0 AND max_uses > 0 AND per_user_limit > 0"),
        CheckConstraint("uses >= 0 AND uses <= max_uses"),
        CheckConstraint("reward_type IN ('balance','license','extension','discount')"),
    )


class PromoRedemption(Row, Base):
    __tablename__ = "promo_redemptions"
    promo_id: Mapped[str] = mapped_column(ForeignKey("promo_codes.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    request_key: Mapped[str] = mapped_column(String(100))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("user_id", "request_key"),)


class AdminUser(Base):
    __tablename__ = "admin_users"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditLog(Row, Base):
    __tablename__ = "admin_audit_logs"
    admin_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class SupportTicket(Row, Base):
    __tablename__ = "support_tickets"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(4000))
    file_id: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="open")


class SupportMessage(Row, Base):
    __tablename__ = "support_messages"
    ticket_id: Mapped[str] = mapped_column(ForeignKey("support_tickets.id"), index=True)
    author_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(String(4000))


class ApplicationSetting(Base):
    __tablename__ = "application_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class RateBucket(Base):
    __tablename__ = "rate_buckets"
    bucket: Mapped[str] = mapped_column(String(100), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Broadcast(Row, Base):
    __tablename__ = "broadcasts"
    admin_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(String(4000))
    media_type: Mapped[str | None] = mapped_column(String(10))
    file_id: Mapped[str | None] = mapped_column(String(512))
    button_text: Mapped[str | None] = mapped_column(String(80))
    button_url: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="draft")


class Delivery(Base):
    __tablename__ = "broadcast_deliveries"
    broadcast_id: Mapped[str] = mapped_column(ForeignKey("broadcasts.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")


class AdminOperation(Base):
    __tablename__ = "admin_operations"
    admin_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)


Index("ix_license_owner_kind", License.user_id, License.kind)
