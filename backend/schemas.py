from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

RequestKey = Annotated[str, StringConstraints(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9:_-]+$")]
Amount = Annotated[Decimal, Field(ge=0, le=1000000, decimal_places=2)]
UserID = Annotated[int, Field(gt=0)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Activation(Strict):
    key: Annotated[str, StringConstraints(pattern=r"^MELKA-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$")]
    device_id: UUID


class Registration(Strict):
    username: Annotated[str | None, Field(max_length=64)] = None
    inviter_id: UserID | None = None


class Language(Strict):
    language: Literal["ru", "uk", "en"]


class Request(Strict):
    request_key: RequestKey


class Buy(Request):
    plan_id: Annotated[str, Field(max_length=36)]
    expected_amount: Amount


class Topup(Request):
    amount: Amount


class Evidence(Strict):
    file_id: Annotated[str, Field(min_length=1, max_length=512)]
    media_type: Literal["photo", "document"]


class Promo(Request):
    code: Annotated[str, StringConstraints(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")]
    license_id: UUID | None = None


class Ticket(Strict):
    text: Annotated[str, Field(min_length=1, max_length=4000)]
    file_id: Annotated[str | None, Field(max_length=512)] = None


class AdminAction(Request):
    action: Literal[
        "ban",
        "unban",
        "adjust_balance",
        "grant",
        "license_update",
        "reset_device",
        "payment_confirm",
        "payment_reject",
        "refund",
        "plan_update",
        "promo_create",
        "promo_disable",
        "setting",
        "support_reply",
        "support_close",
        "broadcast_create",
        "broadcast_confirm",
        "broadcast_cancel",
        "admin_add",
        "admin_remove",
    ]
    target: Annotated[str, Field(min_length=1, max_length=100)]
    user_id: UserID | None = None
    amount: Annotated[Decimal | None, Field(ge=-1000000, le=315360000, decimal_places=2)] = None
    reason: Annotated[str, Field(min_length=3, max_length=500)]
    duration_seconds: Annotated[int | None, Field(ge=1, le=315360000)] = None
    delta_seconds: Annotated[int | None, Field(ge=-315360000, le=315360000)] = None
    device_limit: Annotated[int | None, Field(ge=1, le=100)] = None
    count: Annotated[int, Field(ge=1, le=100)] = 1
    name: Annotated[str | None, Field(min_length=1, max_length=80)] = None
    active: bool | None = None
    status: Literal["active", "available", "suspended", "revoked"] | None = None
    reward_type: Literal["balance", "license", "extension", "discount"] | None = None
    expires_at: datetime | None = None
    max_uses: Annotated[int | None, Field(ge=1, le=1000000)] = None
    per_user_limit: Annotated[int, Field(ge=1, le=10000)] = 1
    allowed_users: list[UserID] = Field(default_factory=list, max_length=1000)
    value: Annotated[str | None, Field(max_length=4000)] = None
    media_type: Literal["photo", "video"] | None = None
    file_id: Annotated[str | None, Field(max_length=512)] = None
    button_text: Annotated[str | None, Field(max_length=80)] = None
    button_url: Annotated[str | None, Field(max_length=512)] = None

    @field_validator("expires_at")
    @classmethod
    def aware_timestamp(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("UTC offset required")
        return value
