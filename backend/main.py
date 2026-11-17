import hmac
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend import models as m
from backend import schemas as q
from backend import services as s
from backend.admin import execute
from backend.config import settings
from backend.db import engine, session
from backend.security import digest

log = logging.getLogger("melkadlc")


@asynccontextmanager
async def lifespan(app):
    # Schema changes are exclusively Alembic migrations; startup never creates tables.
    with Session(engine()) as db, db.begin():
        s.seed(db)
    yield


app = FastAPI(title="MelkaDLC API", version="0.1.0", lifespan=lifespan)
DB = Annotated[Session, Depends(session)]


@app.exception_handler(s.Problem)
async def problem_handler(request, exc):
    return JSONResponse({"error": exc.code}, status_code=exc.status)


@app.exception_handler(Exception)
async def unexpected(request, exc):
    # Do not log request bodies, tokens, SQL parameters or exception messages containing keys.
    log.error("Unhandled %s on %s", type(exc).__name__, request.url.path)
    return JSONResponse({"error": "internal_error"}, status_code=500)


def service_auth(authorization: Annotated[str, Header()] = ""):
    expected = "Bearer " + settings().service_token.get_secret_value()
    if not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise s.Problem("unauthorized", 401)


AUTH = [Depends(service_auth)]


@app.middleware("http")
async def limits(request: Request, call_next):
    if request.url.path.startswith("/v1/"):
        # Shared PostgreSQL counters survive restarts and work across API workers.
        minute = int(m.utcnow().timestamp()) // 60
        ip = request.client.host if request.client else "unknown"
        bucket = digest(f"{ip}:{minute}")
        with Session(engine()) as db, db.begin():
            stmt = insert(m.RateBucket).values(
                bucket=bucket, hits=1, expires_at=m.utcnow() + timedelta(minutes=2)
            )
            hits = db.scalar(
                stmt.on_conflict_do_update(
                    index_elements=[m.RateBucket.bucket], set_={"hits": m.RateBucket.hits + 1}
                ).returning(m.RateBucket.hits)
            )
            db.execute(delete(m.RateBucket).where(m.RateBucket.expires_at < m.utcnow()))
        if hits > 30:
            return JSONResponse({"error": "rate_limited"}, status_code=429, headers={"Retry-After": "60"})
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health(db: DB):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/v1/activate")
def activate(body: q.Activation, db: DB):
    return s.activate(db, body.key, str(body.device_id))


@app.get("/v1/license")
def status(db: DB, authorization: Annotated[str, Header()] = ""):
    if not authorization.startswith("Bearer ") or len(authorization) > 150:
        raise s.Problem("session_invalid", 401)
    return s.status(db, authorization[7:])


@app.get("/v1/updates")
def updates(db: DB):
    version = s.setting(db, "latest_version")
    return {
        "latest_version": version or None,
        "notes": s.setting(db, "update_notes"),
        "url": s.setting(db, "update_url", settings().release_url),
        "server_time": m.utcnow(),
    }


@app.post("/bot/{uid}/register", dependencies=AUTH)
def register(uid: q.UserID, body: q.Registration, db: DB):
    s.register(db, uid, body.username, body.inviter_id)
    return s.profile(db, uid)


@app.put("/bot/{uid}/language", dependencies=AUTH)
def language(uid: q.UserID, body: q.Language, db: DB):
    s.user(db, uid)
    db.get(m.UserSettings, uid).language = body.language
    return {"ok": True}


@app.get("/bot/{uid}/profile", dependencies=AUTH)
def profile(uid: q.UserID, db: DB):
    return s.profile(db, uid)


@app.get("/bot/{uid}/config", dependencies=AUTH)
def config(uid: q.UserID, db: DB):
    s.user(db, uid)
    return {k: s.setting(db, k) for k in ["payment_recipient", "payment_card", "channel_url", "support_url"]}


@app.get("/bot/{uid}/licenses", dependencies=AUTH)
def licenses(uid: q.UserID, db: DB, offset: int = Query(0, ge=0)):
    s.user(db, uid)
    return [
        s.license_view(x, True)
        for x in db.scalars(
            select(m.License)
            .where(m.License.user_id == uid)
            .order_by(m.License.created_at.desc())
            .offset(offset)
            .limit(10)
        )
    ]


@app.get("/bot/{uid}/licenses/{lid}", dependencies=AUTH)
def license_detail(uid: q.UserID, lid: str, db: DB):
    s.user(db, uid)
    return s.license_view(s.owned_license(db, uid, lid), True)


@app.post("/bot/{uid}/trial", dependencies=AUTH)
def trial(uid: q.UserID, db: DB):
    return s.license_view(s.trial(db, uid), True)


@app.post("/bot/{uid}/licenses/{lid}/reset", dependencies=AUTH)
def reset(uid: q.UserID, lid: str, body: q.Request, db: DB):
    return s.license_view(s.reset_device(db, uid, lid, body.request_key), True)


@app.get("/bot/{uid}/plans", dependencies=AUTH)
def plans(uid: q.UserID, db: DB):
    s.user(db, uid)
    return [
        {"id": p.id, "name": p.name, "price": p.price, "duration_seconds": p.duration_seconds}
        for p in db.scalars(select(m.Plan).where(m.Plan.active.is_(True)).order_by(m.Plan.duration_seconds))
    ]


@app.get("/bot/{uid}/quote/{pid}", dependencies=AUTH)
def quote(uid: q.UserID, pid: str, db: DB):
    plan, discount, amount, wallet = s.quote(db, uid, pid)
    return {
        "plan_id": plan.id,
        "name": plan.name,
        "amount": amount,
        "duration_seconds": plan.duration_seconds,
        "balance": wallet.cash + wallet.bonus,
    }


@app.post("/bot/{uid}/purchase", dependencies=AUTH)
def purchase(uid: q.UserID, body: q.Buy, db: DB):
    return s.license_view(s.buy(db, uid, body.plan_id, body.expected_amount, body.request_key), True)


@app.post("/bot/{uid}/payments", dependencies=AUTH)
def topup(uid: q.UserID, body: q.Topup, db: DB):
    row = s.topup(db, uid, body.amount, body.request_key)
    return {
        "id": row.id,
        "amount": row.amount,
        "status": row.status,
        "recipient": s.setting(db, "payment_recipient"),
        "card": s.setting(db, "payment_card"),
    }


@app.post("/bot/{uid}/payments/{pid}/evidence", dependencies=AUTH)
def evidence(uid: q.UserID, pid: str, body: q.Evidence, db: DB):
    row = s.evidence(db, uid, pid, body.file_id, body.media_type)
    return {"id": row.id, "status": row.status, "amount": row.amount}


@app.get("/bot/{uid}/history/{kind}", dependencies=AUTH)
def history(uid: q.UserID, kind: str, db: DB, offset: int = Query(0, ge=0)):
    s.user(db, uid)
    models = {
        "purchases": m.Purchase,
        "wallet": m.WalletTransaction,
        "payments": m.PaymentRequest,
        "referrals": m.ReferralReward,
    }
    model = models.get(kind)
    if not model:
        raise s.Problem("not_found", 404)
    rows = db.scalars(
        select(model).where(model.user_id == uid).order_by(model.created_at.desc()).offset(offset).limit(10)
    )
    return [
        {c.name: getattr(row, c.name) for c in model.__table__.columns if c.name not in {"request_key"}}
        for row in rows
    ]


@app.post("/bot/{uid}/promo", dependencies=AUTH)
def promo(uid: q.UserID, body: q.Promo, db: DB):
    return {
        "reward_type": s.redeem(
            db, uid, body.code, body.request_key, str(body.license_id) if body.license_id else None
        )
    }


@app.post("/bot/{uid}/support", dependencies=AUTH)
def ticket(uid: q.UserID, body: q.Ticket, db: DB):
    s.user(db, uid)
    row = m.SupportTicket(user_id=uid, subject=body.text, file_id=body.file_id)
    db.add(row)
    db.flush()
    return {"id": row.id, "status": row.status}


@app.get("/bot/{uid}/support", dependencies=AUTH)
def tickets(uid: q.UserID, db: DB, offset: int = Query(0, ge=0)):
    s.user(db, uid)
    result = []
    for row in db.scalars(
        select(m.SupportTicket)
        .where(m.SupportTicket.user_id == uid)
        .order_by(m.SupportTicket.created_at.desc())
        .offset(offset)
        .limit(10)
    ):
        messages = db.scalars(
            select(m.SupportMessage)
            .where(m.SupportMessage.ticket_id == row.id)
            .order_by(m.SupportMessage.created_at)
            .limit(50)
        )
        result.append(
            {"id": row.id, "text": row.subject, "status": row.status, "replies": [x.text for x in messages]}
        )
    return result


@app.get("/admin/{aid}/me", dependencies=AUTH)
def admin_me(aid: q.UserID, db: DB):
    s.admin(db, aid)
    return {"ok": True}


@app.post("/admin/{aid}/action", dependencies=AUTH)
def action(aid: q.UserID, body: q.AdminAction, db: DB):
    return execute(db, aid, body)


@app.get("/admin/{aid}/stats", dependencies=AUTH)
def statistics(aid: q.UserID, db: DB):
    s.admin(db, aid)
    return s.stats(db)


@app.get("/admin/{aid}/user/{uid}", dependencies=AUTH)
def admin_profile(aid: q.UserID, uid: q.UserID, db: DB):
    s.admin(db, aid)
    return s.profile(db, uid)


@app.get("/admin/{aid}/list/{resource}", dependencies=AUTH)
def admin_list(
    aid: q.UserID, resource: str, db: DB, offset: int = Query(0, ge=0), user_id: int | None = None
):
    s.admin(db, aid)
    models = {
        "users": m.User,
        "licenses": m.License,
        "subscriptions": m.Subscription,
        "payments": m.PaymentRequest,
        "evidence": m.PaymentEvidence,
        "promos": m.PromoCode,
        "redemptions": m.PromoRedemption,
        "purchases": m.Purchase,
        "referrals": m.Referral,
        "rewards": m.ReferralReward,
        "plans": m.Plan,
        "audit": m.AuditLog,
        "support": m.SupportTicket,
        "settings": m.ApplicationSetting,
        "activations": m.Activation,
        "wallet": m.WalletTransaction,
        "broadcasts": m.Broadcast,
    }
    model = models.get(resource)
    if not model:
        raise s.Problem("not_found", 404)
    query = select(model)
    if user_id is not None and hasattr(model, "user_id"):
        query = query.where(model.user_id == user_id)
    ordering = (
        model.created_at.desc() if hasattr(model, "created_at") else list(model.__table__.primary_key)[0]
    )
    rows = db.scalars(query.order_by(ordering).offset(offset).limit(10))
    return [
        {
            col.name: getattr(row, col.name)
            for col in model.__table__.columns
            if col.name not in {"key_hash", "key_ciphertext", "device_hash", "token_hash"}
        }
        for row in rows
    ]


@app.get("/admin/{aid}/broadcast/{bid}", dependencies=AUTH)
def broadcast(aid: q.UserID, bid: str, db: DB):
    s.admin(db, aid)
    row = db.get(m.Broadcast, bid)
    if not row:
        raise s.Problem("broadcast_not_found", 404)
    return {c.name: getattr(row, c.name) for c in m.Broadcast.__table__.columns}


@app.get("/worker/deliveries", dependencies=AUTH)
def deliveries(db: DB):
    # One bot worker is supported. Telegram sends cannot share a DB transaction.
    rows = db.execute(
        select(m.Delivery, m.Broadcast)
        .join(m.Broadcast)
        .where(m.Delivery.status == "pending", m.Broadcast.status == "ready")
        .limit(20)
    )
    return [
        {
            "broadcast_id": d.broadcast_id,
            "user_id": d.user_id,
            "text": b.text,
            "media_type": b.media_type,
            "file_id": b.file_id,
            "button_text": b.button_text,
            "button_url": b.button_url,
        }
        for d, b in rows
    ]


@app.post("/worker/deliveries/{bid}/{uid}/{state}", dependencies=AUTH)
def delivered(bid: str, uid: q.UserID, state: str, db: DB):
    if state not in {"sent", "failed"}:
        raise s.Problem("invalid_status")
    row = db.get(m.Delivery, (bid, uid))
    if not row:
        raise s.Problem("not_found", 404)
    row.status = state
    return {"ok": True}
