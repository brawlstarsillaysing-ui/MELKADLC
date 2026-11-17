"""All administrative mutations enforce identity and persist audit + idempotency records."""

import json
import re
from datetime import timedelta
from urllib.parse import urlparse

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from backend import models as m
from backend import services as s
from backend.schemas import AdminAction
from backend.security import decrypt, digest, encrypt


def require(value):
    if value is None:
        raise s.Problem("missing_parameter", 422)
    return value


def safe_url(value, telegram=False):
    p = urlparse(value)
    if p.scheme != "https" or not p.netloc or p.username or p.password:
        raise s.Problem("invalid_url")
    if telegram and p.hostname != "t.me":
        raise s.Problem("invalid_url")


def execute(db, aid: int, cmd: AdminAction):
    s.commerce(db)
    s.admin(db, aid)
    payload_hash = digest(json.dumps(cmd.model_dump(mode="json"), sort_keys=True))
    old = db.get(m.AdminOperation, (aid, cmd.request_key))
    if old:
        if old.input_hash != payload_hash:
            raise s.Problem("idempotency_conflict", 409)
        return json.loads(decrypt(old.result["ciphertext"]))
    result = mutate(db, aid, cmd)
    db.flush()
    result = jsonable_encoder(result)
    db.add(
        m.AdminOperation(
            admin_id=aid,
            request_key=cmd.request_key,
            input_hash=payload_hash,
            result={"ciphertext": encrypt(json.dumps(result))},
        )
    )
    s.audit(
        db,
        aid,
        cmd.action,
        cmd.target,
        {
            k: v
            for k, v in cmd.model_dump(mode="json", exclude_none=True).items()
            if k not in {"file_id", "value"}
        },
    )
    return result


def mutate(db, aid, c):
    action, target = c.action, c.target
    if action in {"ban", "unban", "adjust_balance", "grant"}:
        uid = require(c.user_id)
        person = s.user(db, uid, allow_banned=True)
        if action in {"ban", "unban"}:
            person.banned = action == "ban"
        elif action == "adjust_balance":
            # Manual credits are bonus, never external revenue. Cash comes only from deposits.
            amount = s.money(require(c.amount))
            wallet = db.get(m.Wallet, uid)
            if amount >= 0:
                s.bonus_credit(db, wallet, amount, f"admin:{aid}:{c.request_key}", c.reason)
            elif wallet.bonus + amount < 0:
                raise s.Problem("insufficient_balance")
            else:
                s.ledger(db, wallet, s.ZERO, amount, s.ZERO, f"admin:{aid}:{c.request_key}", c.reason)
        else:
            return {
                "licenses": [
                    s.license_view(
                        s.issue(db, uid, "grant", require(c.duration_seconds), c.device_limit or 1), True
                    )
                    for _ in range(c.count)
                ]
            }
        return {"ok": True}
    if action in {"license_update", "reset_device"}:
        lic = db.scalar(select(m.License).where(m.License.id == target).with_for_update())
        if not lic:
            raise s.Problem("license_not_found", 404)
        if action == "reset_device":
            return s.license_view(s.reset_device(db, lic.user_id, lic.id, c.request_key, aid))
        if c.device_limit is not None:
            from sqlalchemy import func

            count = db.scalar(
                select(func.count()).select_from(m.DeviceBinding).where(m.DeviceBinding.license_id == lic.id)
            )
            if c.device_limit < count:
                raise s.Problem("reset_devices_first")
            lic.device_limit = c.device_limit
        if c.delta_seconds is not None:
            if lic.expires_at:
                lic.expires_at += timedelta(seconds=c.delta_seconds)
                db.get(m.Subscription, lic.id).ends_at = lic.expires_at
            else:
                lic.duration_seconds = max(1, lic.duration_seconds + c.delta_seconds)
        if c.status is not None:
            if c.status == "available" and lic.activated_at:
                raise s.Problem("cannot_restart_license")
            if c.status == "active" and not lic.activated_at:
                raise s.Problem("activation_required")
            lic.status = c.status
        return s.license_view(lic)
    if action in {"payment_confirm", "payment_reject"}:
        row = s.decide_payment(db, aid, target, "confirmed" if action == "payment_confirm" else "rejected")
        return {"id": row.id, "user_id": row.user_id, "status": row.status}
    if action == "refund":
        s.refund(db, aid, target, c.reason)
        return {"ok": True}
    if action == "plan_update":
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", target):
            raise s.Problem("invalid_plan_id")
        plan = db.get(m.Plan, target)
        if c.amount is not None:
            s.money(c.amount)
        if not plan:
            plan = m.Plan(
                id=target,
                name=require(c.name),
                price=require(c.amount),
                duration_seconds=require(c.duration_seconds),
            )
            db.add(plan)
        for attr, value in [
            ("name", c.name),
            ("price", c.amount),
            ("duration_seconds", c.duration_seconds),
            ("active", c.active),
        ]:
            if value is not None:
                if attr == "price" and value <= 0:
                    raise s.Problem("invalid_amount")
                setattr(plan, attr, value)
        return {"ok": True}
    if action == "promo_create":
        code = target.upper()
        if not re.fullmatch(r"[A-Z0-9_-]{1,40}", code):
            raise s.Problem("invalid_promo_code")
        if db.scalar(select(m.PromoCode).where(m.PromoCode.code == code)):
            raise s.Problem("promo_exists", 409)
        value, expiry, reward_type = require(c.amount), require(c.expires_at), require(c.reward_type)
        if reward_type == "balance":
            s.money(value)
        if value <= 0 or expiry <= m.utcnow() or (reward_type == "discount" and value > 100):
            raise s.Problem("invalid_promo")
        if reward_type in {"license", "extension"} and (value != int(value) or value > 315360000):
            raise s.Problem("invalid_duration")
        db.add(
            m.PromoCode(
                code=code,
                reward_type=reward_type,
                value=value,
                expires_at=expiry,
                max_uses=require(c.max_uses),
                per_user_limit=c.per_user_limit,
                allowed_users=c.allowed_users,
            )
        )
        return {"ok": True}
    if action == "promo_disable":
        promo = db.scalar(select(m.PromoCode).where(m.PromoCode.code == target.upper()))
        if not promo:
            raise s.Problem("promo_unavailable", 404)
        promo.active = False
        return {"ok": True}
    if action == "setting":
        if target not in {
            "payment_recipient",
            "payment_card",
            "channel_url",
            "support_url",
            "self_reset_limit",
            "latest_version",
            "update_notes",
            "update_url",
        }:
            raise s.Problem("invalid_setting")
        value = require(c.value)
        if target.endswith("url") and value:
            safe_url(value, telegram=target in {"channel_url", "support_url"})
        if target == "self_reset_limit" and (not value.isdigit() or int(value) > 100):
            raise s.Problem("invalid_setting")
        if target == "payment_card" and not re.fullmatch(r"[0-9 ]{16,25}", value):
            raise s.Problem("invalid_setting")
        row = db.get(m.ApplicationSetting, target)
        if row:
            row.value = value
        else:
            db.add(m.ApplicationSetting(key=target, value=value))
        return {"ok": True}
    if action in {"support_reply", "support_close"}:
        ticket = db.get(m.SupportTicket, target)
        if not ticket:
            raise s.Problem("ticket_not_found", 404)
        if action == "support_close":
            ticket.status = "closed"
        else:
            db.add(m.SupportMessage(ticket_id=target, author_id=aid, text=require(c.value)))
            ticket.status = "answered"
        return {"ok": True, "user_id": ticket.user_id}
    if action == "broadcast_create":
        if bool(c.file_id) != bool(c.media_type) or bool(c.button_url) != bool(c.button_text):
            raise s.Problem("invalid_broadcast")
        if c.button_url:
            safe_url(c.button_url)
        message = require(c.value)
        if c.file_id and len(message) > 1024:
            raise s.Problem("caption_too_long")
        row = m.Broadcast(
            admin_id=aid,
            text=message,
            media_type=c.media_type,
            file_id=c.file_id,
            button_text=c.button_text,
            button_url=c.button_url,
        )
        db.add(row)
        db.flush()
        return {"id": row.id, "status": row.status}
    if action in {"broadcast_confirm", "broadcast_cancel"}:
        row = db.get(m.Broadcast, target)
        if not row or row.admin_id != aid:
            raise s.Problem("broadcast_not_found", 404)
        if row.status != "draft":
            raise s.Problem("broadcast_already_processed", 409)
        row.status = "ready" if action == "broadcast_confirm" else "cancelled"
        if row.status == "ready":
            for uid in db.scalars(select(m.User.id).where(m.User.banned.is_(False))):
                db.add(m.Delivery(broadcast_id=row.id, user_id=uid))
        return {"ok": True}
    if action in {"admin_add", "admin_remove"}:
        uid = require(c.user_id)
        if uid == aid and action == "admin_remove":
            raise s.Problem("cannot_remove_self")
        row = db.get(m.AdminUser, uid)
        if not row:
            row = m.AdminUser(user_id=uid)
            db.add(row)
        row.active = action == "admin_add"
        return {"ok": True}
    raise s.Problem("unknown_action")
