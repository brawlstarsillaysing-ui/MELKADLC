import asyncio
import html
import json
import logging
import secrets
from contextlib import suppress
from decimal import Decimal, InvalidOperation

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from backend.schemas import AdminAction
from telegram_bot.client import API, APIError
from telegram_bot.config import settings
from telegram_bot.locales import TEXT, tr

api = API()
dp = Dispatcher()
escape = html.escape


class Flow(StatesGroup):
    amount = State()
    evidence = State()
    promo = State()
    support = State()
    admin_input = State()
    admin_confirm = State()


def markup(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=value) for label, value in row] for row in rows
        ]
    )


def nav(lang, more=None):
    rows = list(more or [])
    rows.append([(tr(lang, "back"), "menu")])
    return markup(rows)


def menu(lang):
    return nav(
        lang,
        [
            [(tr(lang, key), key)]
            for key in [
                "profile",
                "keys",
                "trial",
                "shop",
                "wallet",
                "referrals",
                "promo",
                "channel",
                "support",
                "settings",
            ]
        ],
    )


def line(lang, label, value):
    return f"{tr(lang, label)}: <b>{escape(str(value))}</b>"


def license_text(lang, lic):
    hours = Decimal(lic["duration_seconds"]) / 3600
    return "\n".join(
        [
            "<b>MELKADLC • LICENSE</b>",
            f"<code>{escape(lic['key'])}</code>",
            f"ID: <code>{lic['id']}</code>",
            lic["kind"].upper(),
            line(lang, "state", tr(lang, lic["status"])),
            line(lang, "duration", f"{hours:g} {tr(lang, 'hours')}"),
            line(lang, "activated", lic.get("activated_at") or "—"),
            line(lang, "expires", lic.get("expires_at") or "—"),
            "UTC",
        ]
    )


async def show(event, text, keyboard=None):
    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                await event.message.answer(text, reply_markup=keyboard)
    else:
        await event.answer(text, reply_markup=keyboard)


class Context(BaseMiddleware):
    async def __call__(self, handler, event, data):
        person = event.from_user
        chat = event.message.chat if isinstance(event, CallbackQuery) else event.chat
        if chat.type != "private" or not person:
            return
        lang = "ru"
        try:
            profile = await api.post(f"/bot/{person.id}/register", {"username": person.username})
            lang = profile["language"]
            data.update(lang=lang, profile=profile)
            await handler(event, data)
        except APIError as exc:
            key = exc.code if exc.code in TEXT else "invalid_input"
            await show(event, tr(lang, key), nav(lang))
        except (ValueError, KeyError, TypeError, InvalidOperation, IndexError):
            await show(event, tr(lang, "invalid_input"), nav(lang))
        finally:
            if isinstance(event, CallbackQuery):
                with suppress(TelegramBadRequest):
                    await event.answer()


# /start must register the referral before middleware can create the user.
class RegistrationContext(Context):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.text and event.text.startswith("/start "):
            payload = event.text.split(maxsplit=1)[1]
            if payload.startswith("ref_") and payload[4:].isdigit() and event.chat.type == "private":
                try:
                    await api.post(
                        f"/bot/{event.from_user.id}/register",
                        {"username": event.from_user.username, "inviter_id": int(payload[4:])},
                    )
                except APIError:
                    pass
        return await super().__call__(handler, event, data)


dp.message.middleware(RegistrationContext())
dp.callback_query.middleware(Context())


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext, lang):
    await state.clear()
    await message.answer(
        "<b>WELCOME TO MELKADLC</b>\n\n" + tr(lang, "welcome") + "\n\n" + tr(lang, "choose"),
        reply_markup=markup(
            [[("🇷🇺 Русский", "lang:ru")], [("🇺🇦 Українська", "lang:uk")], [("🇬🇧 English", "lang:en")]]
        ),
    )


@dp.callback_query(F.data.startswith("lang:"))
async def language(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split(":")[1]
    await api.call("PUT", f"/bot/{callback.from_user.id}/language", {"language": lang})
    await state.clear()
    await show(callback, "<b>MELKADLC</b>\n" + tr(lang, "menu"), menu(lang))


@dp.callback_query(F.data.in_({"menu", "settings"}))
async def home(callback: CallbackQuery, state: FSMContext, lang):
    await state.clear()
    if callback.data == "settings":
        await show(
            callback,
            tr(lang, "choose"),
            markup(
                [
                    [("🇷🇺 Русский", "lang:ru")],
                    [("🇺🇦 Українська", "lang:uk")],
                    [("🇬🇧 English", "lang:en")],
                    [(tr(lang, "back"), "menu")],
                ]
            ),
        )
    else:
        await show(callback, "<b>MELKADLC</b>\n" + tr(lang, "menu"), menu(lang))


@dp.callback_query(F.data == "profile")
async def profile_view(callback: CallbackQuery, lang, profile):
    lines = [
        "<b>MELKADLC • PROFILE</b>",
        f"Telegram ID: <code>{profile['telegram_id']}</code>",
        "@" + escape(profile["username"] or "—"),
    ]
    for label, value in [
        ("registered", profile["registered_at"]),
        ("state", tr(lang, "account_blocked") if profile["banned"] else "ACTIVE"),
        ("balance", str(profile["balance"]) + " UAH"),
        ("cash", str(profile["cash"]) + " UAH"),
        ("bonus", str(profile["bonus"]) + " UAH"),
        ("debt", str(profile["bonus_debt"]) + " UAH"),
        ("earned", str(profile["referral_earned"]) + " UAH"),
        ("ref_count", profile["referral_count"]),
        ("subscriptions", profile["active_subscriptions"]),
        ("purchase_count", profile["purchase_count"]),
        ("purchase_total", str(profile["purchase_total"]) + " UAH"),
        ("issued", profile["trial_issued"]),
        ("used", profile["trial_used"]),
        ("remaining", profile["trial_remaining"]),
    ]:
        lines.append(line(lang, label, value))
    await show(
        callback,
        "\n".join(lines),
        nav(
            lang,
            [
                [(tr(lang, "history"), "hist:purchases:0")],
                [(tr(lang, "transactions"), "hist:wallet:0")],
                [(tr(lang, "keys"), "keys")],
                [(tr(lang, "wallet"), "wallet")],
                [(tr(lang, "referrals"), "referrals")],
            ],
        ),
    )


@dp.callback_query(F.data == "trial")
async def trial_view(callback: CallbackQuery, lang, profile):
    text = "\n".join(
        [
            "<b>MELKADLC • FREE TRIAL</b>",
            line(lang, "remaining", str(profile["trial_remaining"]) + "/5"),
            line(lang, "used", profile["trial_used"]),
            tr(lang, "trial_info"),
        ]
    )
    await show(
        callback, text, nav(lang, [[(tr(lang, "get_trial"), "get_trial")], [(tr(lang, "keys"), "keys")]])
    )


@dp.callback_query(F.data == "get_trial")
async def get_trial(callback: CallbackQuery, lang):
    lic = await api.post(f"/bot/{callback.from_user.id}/trial")
    await show(callback, license_text(lang, lic), nav(lang, [[(tr(lang, "keys"), "keys")]]))


@dp.callback_query((F.data == "keys") | F.data.startswith("keys:"))
async def key_list(callback: CallbackQuery, lang):
    offset = int(callback.data.split(":")[1]) if ":" in callback.data else 0
    rows = await api.get(f"/bot/{callback.from_user.id}/licenses", {"offset": offset})
    buttons = [
        [(f"{r['kind'].upper()} • {tr(lang, r['status'])} • {r['key'][-4:]}", "key:" + r["id"])] for r in rows
    ]
    if len(rows) == 10:
        buttons.append([(tr(lang, "next"), f"keys:{offset + 10}")])
    await show(
        callback,
        "<b>MELKADLC • LICENSES</b>" + ("" if rows else "\n" + tr(lang, "empty")),
        nav(lang, buttons),
    )


@dp.callback_query(F.data.startswith("key:"))
async def key_view(callback: CallbackQuery, lang):
    lid = callback.data.split(":")[1]
    lic = await api.get(f"/bot/{callback.from_user.id}/licenses/{lid}")
    await show(
        callback,
        license_text(lang, lic),
        nav(lang, [[(tr(lang, "reset"), "reset:" + lid)], [(tr(lang, "renew"), "shop")]]),
    )


@dp.callback_query(F.data.startswith("reset:"))
async def reset_prompt(callback: CallbackQuery, lang):
    await show(
        callback,
        tr(lang, "reset_info"),
        nav(lang, [[(tr(lang, "confirm"), "rst:" + callback.data.split(":")[1])]]),
    )


@dp.callback_query(F.data.startswith("rst:"))
async def reset(callback: CallbackQuery, lang):
    lid = callback.data.split(":")[1]
    result = await api.post(
        f"/bot/{callback.from_user.id}/licenses/{lid}/reset",
        {"request_key": f"{callback.message.message_id}:{lid}"},
    )
    await show(callback, license_text(lang, result), nav(lang))


@dp.callback_query(F.data == "shop")
async def shop(callback: CallbackQuery, lang):
    plans = await api.get(f"/bot/{callback.from_user.id}/plans")
    await show(
        callback,
        "<b>MELKADLC • PREMIUM</b>",
        nav(
            lang,
            [
                [
                    (
                        f"{Decimal(p['duration_seconds']) / 3600:g} {tr(lang, 'hours')} • {p['price']} UAH",
                        "plan:" + p["id"],
                    )
                ]
                for p in plans
            ],
        ),
    )


@dp.callback_query(F.data.startswith("plan:"))
async def plan(callback: CallbackQuery, lang):
    pid = callback.data.split(":")[1]
    row = await api.get(f"/bot/{callback.from_user.id}/quote/{pid}")
    order = secrets.token_hex(8)
    await show(
        callback,
        "\n".join(
            [
                tr(lang, "buy_info"),
                line(lang, "price", str(row["amount"]) + " UAH"),
                line(lang, "duration", f"{Decimal(row['duration_seconds']) / 3600:g} {tr(lang, 'hours')}"),
                line(lang, "balance", str(row["balance"]) + " UAH"),
            ]
        ),
        nav(lang, [[(tr(lang, "confirm"), f"buy:{pid}:{row['amount']}:{order}")]]),
    )


@dp.callback_query(F.data.startswith("buy:"))
async def buy(callback: CallbackQuery, lang):
    _, pid, amount, order = callback.data.split(":")
    lic = await api.post(
        f"/bot/{callback.from_user.id}/purchase",
        {"plan_id": pid, "expected_amount": amount, "request_key": order},
    )
    await show(callback, license_text(lang, lic), nav(lang))


@dp.callback_query(F.data == "wallet")
async def wallet(callback: CallbackQuery, state: FSMContext, lang):
    await state.set_state(Flow.amount)
    await show(callback, tr(lang, "amount_prompt"), nav(lang, [[(tr(lang, "payments"), "hist:payments:0")]]))


@dp.message(Flow.amount)
async def amount(message: Message, state: FSMContext, lang):
    value = Decimal((message.text or "").replace(",", "."))
    row = await api.post(
        f"/bot/{message.from_user.id}/payments",
        {"amount": str(value), "request_key": f"tg:{message.chat.id}:{message.message_id}"},
    )
    await state.set_state(Flow.evidence)
    await state.update_data(payment_id=row["id"])
    await message.answer(
        "\n".join(
            [
                "<b>MELKADLC • PAYMENT</b>",
                f"ID: <code>{row['id']}</code>",
                line(lang, "price", str(row["amount"]) + " UAH"),
                line(lang, "recipient", row["recipient"]),
                line(lang, "card", row["card"]),
                tr(lang, "payment_info"),
            ]
        ),
        reply_markup=nav(lang),
    )


@dp.callback_query(F.data.startswith("receipt:"))
async def receipt(callback: CallbackQuery, state: FSMContext, lang):
    await state.set_state(Flow.evidence)
    await state.update_data(payment_id=callback.data.split(":")[1])
    await show(callback, tr(lang, "receipt_prompt"), nav(lang))


async def notify_admins(bot, text, file_id=None, media_type=None, keyboard=None):
    for aid in settings().administrators:
        try:
            if media_type == "photo":
                await bot.send_photo(aid, file_id, caption=text, reply_markup=keyboard)
            elif file_id:
                await bot.send_document(aid, file_id, caption=text, reply_markup=keyboard)
            else:
                await bot.send_message(aid, text, reply_markup=keyboard)
        except (TelegramForbiddenError, TelegramBadRequest):
            logging.getLogger("melkadlc.bot").warning("Administrator notification unavailable")


@dp.message(Flow.evidence)
async def evidence(message: Message, state: FSMContext, lang):
    file_id, media = None, None
    if message.photo:
        file_id, media = message.photo[-1].file_id, "photo"
    elif message.document and message.document.mime_type == "application/pdf":
        if message.document.file_size and message.document.file_size > 20 * 1024 * 1024:
            raise ValueError()
        file_id, media = message.document.file_id, "document"
    if not file_id:
        await message.answer(tr(lang, "receipt_prompt"))
        return
    data = await state.get_data()
    pid = data["payment_id"]
    row = await api.post(
        f"/bot/{message.from_user.id}/payments/{pid}/evidence", {"file_id": file_id, "media_type": media}
    )
    await state.clear()
    await message.answer(tr(lang, "evidence_received"), reply_markup=nav(lang))
    await notify_admins(
        message.bot,
        f"<b>MELKADLC • PAYMENT</b>\n{pid}\nTelegram ID: {message.from_user.id}\n"
        f"@{escape(message.from_user.username or '—')}\n{row['amount']} UAH\n{message.date.isoformat()}",
        file_id,
        media,
        markup(
            [
                [("ПОДТВЕРДИТЬ", "payok:" + pid), ("ОТКЛОНИТЬ", "payno:" + pid)],
                [("ПРОФИЛЬ", f"aprofile:{message.from_user.id}")],
            ]
        ),
    )


@dp.callback_query(F.data.startswith("hist:"))
async def history(callback: CallbackQuery, lang):
    _, kind, raw = callback.data.split(":")
    offset = int(raw)
    rows = await api.get(f"/bot/{callback.from_user.id}/history/{kind}", {"offset": offset})
    blocks, buttons = [], []
    for row in rows:
        parts = [f"<code>{row['id']}</code>", escape(row["created_at"])]
        if "amount" in row:
            parts.append(str(row["amount"]) + " UAH")
        if "status" in row:
            parts.append(tr(lang, row["status"]))
        if "cash_delta" in row:
            parts.extend(
                [
                    line(lang, "cash", str(row["cash_delta"]) + " UAH"),
                    line(lang, "bonus", str(row["bonus_delta"]) + " UAH"),
                ]
            )
        blocks.append("\n".join(parts))
        if kind == "payments" and row["status"] == "pending":
            buttons.append([(tr(lang, "attach_receipt") + " " + row["id"][:8], "receipt:" + row["id"])])
    if len(rows) == 10:
        buttons.append([(tr(lang, "next"), f"hist:{kind}:{offset + 10}")])
    await show(
        callback,
        "<b>MELKADLC • HISTORY</b>\n\n" + ("\n\n".join(blocks) or tr(lang, "empty")),
        nav(lang, buttons),
    )


@dp.callback_query(F.data == "referrals")
async def referrals(callback: CallbackQuery, lang, profile):
    username = settings().bot_username
    link = (
        f"https://t.me/{username}?start=ref_{callback.from_user.id}" if username else tr(lang, "unavailable")
    )
    await show(
        callback,
        "\n".join(
            [
                "<b>MELKADLC • REFERRALS</b>",
                link,
                tr(lang, "referral_info"),
                line(lang, "ref_count", profile["referral_count"]),
                line(lang, "paying_refs", profile["paying_referrals"]),
                line(lang, "earned", str(profile["referral_earned"]) + " UAH"),
                line(lang, "balance", str(profile["balance"]) + " UAH"),
            ]
        ),
        nav(lang, [[(tr(lang, "transactions"), "hist:referrals:0")]]),
    )


@dp.callback_query(F.data == "promo")
async def promo(callback: CallbackQuery, state: FSMContext, lang):
    await state.set_state(Flow.promo)
    await show(callback, tr(lang, "promo_prompt"), nav(lang))


@dp.message(Flow.promo)
async def redeem(message: Message, state: FSMContext, lang):
    parts = (message.text or "").split()
    data = {"code": parts[0], "request_key": f"tg:{message.chat.id}:{message.message_id}"}
    if len(parts) == 2:
        data["license_id"] = parts[1]
    await api.post(f"/bot/{message.from_user.id}/promo", data)
    await state.clear()
    await message.answer(tr(lang, "promo_success"), reply_markup=nav(lang))


@dp.callback_query(F.data == "channel")
async def channel(callback: CallbackQuery, lang):
    config = await api.get(f"/bot/{callback.from_user.id}/config")
    url = config["channel_url"]
    keyboard = nav(lang)
    if url:
        keyboard.inline_keyboard.insert(0, [InlineKeyboardButton(text=tr(lang, "channel"), url=url)])
    await show(callback, tr(lang, "channel") if url else tr(lang, "unavailable"), keyboard)


@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery, lang):
    await show(
        callback,
        "<b>MELKADLC • SUPPORT</b>",
        nav(lang, [[(tr(lang, "new_ticket"), "new_ticket")], [(tr(lang, "my_tickets"), "tickets:0")]]),
    )


@dp.callback_query(F.data == "new_ticket")
async def new_ticket(callback: CallbackQuery, state: FSMContext, lang):
    await state.set_state(Flow.support)
    await show(callback, tr(lang, "support_prompt"), nav(lang))


@dp.message(Flow.support)
async def ticket(message: Message, state: FSMContext, lang):
    file_id = (
        message.document.file_id if message.document else message.photo[-1].file_id if message.photo else None
    )
    row = await api.post(
        f"/bot/{message.from_user.id}/support",
        {"text": message.text or message.caption or "", "file_id": file_id},
    )
    await state.clear()
    await message.answer(tr(lang, "ticket_created") + f"\n<code>{row['id']}</code>", reply_markup=nav(lang))
    await notify_admins(
        message.bot,
        f"<b>MELKADLC • SUPPORT</b>\n{row['id']}\nUser: {message.from_user.id}\n"
        + escape((message.text or message.caption or "")[:600]),
    )


@dp.callback_query(F.data.startswith("tickets:"))
async def tickets(callback: CallbackQuery, lang):
    offset = int(callback.data.split(":")[1])
    rows = await api.get(f"/bot/{callback.from_user.id}/support", {"offset": offset})
    blocks = [
        f"<code>{r['id']}</code> • {tr(lang, r['status'])}\n{escape(r['text'][:300])}\n"
        + "\n".join(escape(x[:300]) for x in r["replies"][-3:])
        for r in rows
    ]
    buttons = [[(tr(lang, "next"), f"tickets:{offset + 10}")]] if len(rows) == 10 else []
    # Telegram limits text to 4096 chars. Ticket details are paginated and truncated here.
    await show(callback, ("\n\n".join(blocks) or tr(lang, "empty"))[:3800], nav(lang, buttons))


ADMIN_RESOURCES = [
    "users",
    "subscriptions",
    "licenses",
    "payments",
    "promos",
    "purchases",
    "referrals",
    "plans",
    "support",
    "settings",
    "audit",
    "broadcasts",
    "evidence",
    "activations",
    "redemptions",
]
ADMIN_ACTIONS = [
    "ban",
    "unban",
    "adjust_balance",
    "grant",
    "license_update",
    "reset_device",
    "refund",
    "plan_update",
    "promo_create",
    "promo_disable",
    "setting",
    "support_reply",
    "support_close",
    "broadcast_create",
    "admin_add",
    "admin_remove",
]


@dp.message(Command("admin"))
async def admin_menu(message: Message, state: FSMContext, lang):
    await api.get(f"/admin/{message.from_user.id}/me")
    await state.clear()
    await message.answer(
        "<b>MELKADLC CONTROL CENTER</b>",
        reply_markup=nav(
            lang,
            [[(name, "alist:" + name + ":0")] for name in ADMIN_RESOURCES]
            + [[("Статистика / Finance", "astats")], [("Действие / Action", "actions")]],
        ),
    )


@dp.callback_query(F.data == "astats")
async def stats(callback: CallbackQuery, lang):
    row = await api.get(f"/admin/{callback.from_user.id}/stats")
    await show(
        callback,
        "<b>MELKADLC • FINANCE</b>\n<pre>" + escape(json.dumps(row, ensure_ascii=False, indent=2)) + "</pre>",
        nav(lang),
    )


@dp.callback_query(F.data.startswith("alist:"))
async def admin_list(callback: CallbackQuery, lang):
    _, resource, raw = callback.data.split(":")
    rows = await api.get(f"/admin/{callback.from_user.id}/list/{resource}", {"offset": int(raw)})
    # Send a JSON document for full rows; chat preview is bounded.
    body = json.dumps(rows, ensure_ascii=False, indent=2)
    buttons = [[("Действие / Action", "actions")]]
    if len(rows) == 10:
        buttons.append([(tr(lang, "next"), f"alist:{resource}:{int(raw) + 10}")])
    await show(
        callback, "<b>MELKADLC • ADMIN</b>\n<pre>" + escape(body[:2600]) + "</pre>", nav(lang, buttons)
    )
    if len(body) > 2600:
        from aiogram.types import BufferedInputFile

        await callback.message.answer_document(BufferedInputFile(body.encode(), filename=resource + ".json"))


@dp.callback_query(F.data.startswith("aprofile:"))
async def admin_profile(callback: CallbackQuery, lang):
    row = await api.get(f"/admin/{callback.from_user.id}/user/{callback.data.split(':')[1]}")
    await show(
        callback, "<pre>" + escape(json.dumps(row, ensure_ascii=False, indent=2)) + "</pre>", nav(lang)
    )


@dp.callback_query(F.data == "actions")
async def action_menu(callback: CallbackQuery, state: FSMContext, lang):
    await api.get(f"/admin/{callback.from_user.id}/me")
    await state.set_state(Flow.admin_input)
    await show(
        callback,
        "<b>MELKADLC • ADMIN</b>\n"
        + "Действия / Actions:\n<code>"
        + escape(", ".join(ADMIN_ACTIONS))
        + "</code>\n\n"
        + "Отправьте JSON с параметрами. Схема и примеры: docs/ADMIN.md. Сначала будет предпросмотр.\n"
        + "Send a JSON action. A preview is required before changes.\n\n"
        + '<pre>{"action":"grant","target":"user","user_id":123456,"duration_seconds":86400,"reason":"Manual grant"}</pre>',
        nav(lang),
    )


@dp.message(Flow.admin_input)
async def action_input(message: Message, state: FSMContext, lang):
    await api.get(f"/admin/{message.from_user.id}/me")
    payload = json.loads(message.text or "")
    payload["request_key"] = secrets.token_hex(16)
    command = AdminAction.model_validate(payload)
    await state.update_data(admin_command=command.model_dump(mode="json"))
    await state.set_state(Flow.admin_confirm)
    if command.action == "broadcast_create":
        keyboard = None
        if command.button_url:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=command.button_text, url=command.button_url)]]
            )
        # Actual message preview before approving creation. Sending requires another confirmation.
        if command.media_type == "photo":
            await message.answer_photo(command.file_id, caption=escape(command.value), reply_markup=keyboard)
        elif command.media_type == "video":
            await message.answer_video(command.file_id, caption=escape(command.value), reply_markup=keyboard)
        else:
            await message.answer(escape(command.value), reply_markup=keyboard)
    await message.answer(
        "<b>MELKADLC • PREVIEW</b>\n<pre>"
        + escape(json.dumps(payload, ensure_ascii=False, indent=2)[:2600])
        + "</pre>",
        reply_markup=nav(lang, [[(tr(lang, "confirm"), "admin_apply")]]),
    )


@dp.callback_query(Flow.admin_confirm, F.data == "admin_apply")
async def action_apply(callback: CallbackQuery, state: FSMContext, lang):
    payload = (await state.get_data())["admin_command"]
    result = await api.post(f"/admin/{callback.from_user.id}/action", payload)
    await state.clear()
    buttons = []
    if payload["action"] == "broadcast_create":
        buttons.append([("ОТПРАВИТЬ / SEND", "broadcast:" + result["id"])])
    await show(
        callback,
        "<pre>" + escape(json.dumps(result, ensure_ascii=False, indent=2)[:3000]) + "</pre>",
        nav(lang, buttons),
    )


@dp.callback_query(F.data.startswith("broadcast:"))
async def broadcast_confirm(callback: CallbackQuery, lang):
    bid = callback.data.split(":")[1]
    await api.post(
        f"/admin/{callback.from_user.id}/action",
        {
            "action": "broadcast_confirm",
            "target": bid,
            "request_key": "broadcast:" + bid,
            "reason": "Confirmed after preview",
        },
    )
    await show(callback, tr(lang, "ok"), nav(lang))


@dp.callback_query(F.data.startswith("payok:") | F.data.startswith("payno:"))
async def payment_confirmation(callback: CallbackQuery, state: FSMContext, lang):
    await api.get(f"/admin/{callback.from_user.id}/me")
    kind, pid = callback.data.split(":")
    payload = {
        "action": "payment_confirm" if kind == "payok" else "payment_reject",
        "target": pid,
        "request_key": kind + ":" + pid,
        "reason": "Administrator verified actual incoming payment" if kind == "payok" else "Payment rejected",
    }
    await state.update_data(admin_command=payload)
    await state.set_state(Flow.admin_confirm)
    await show(
        callback,
        "Подтвердите решение после проверки фактического поступления. / Confirm after checking actual receipt.\n"
        + f"<code>{pid}</code>\n"
        + payload["action"],
        nav(lang, [[(tr(lang, "confirm"), "admin_apply")]]),
    )


@dp.message()
async def fallback(message: Message, lang):
    await message.answer(tr(lang, "menu"), reply_markup=menu(lang))


async def broadcast_worker(bot):
    while True:
        try:
            deliveries = await api.get("/worker/deliveries")
            for row in deliveries:
                keyboard = None
                if row["button_url"]:
                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text=row["button_text"], url=row["button_url"])]
                        ]
                    )
                state = "sent"
                try:
                    if row["media_type"] == "photo":
                        await bot.send_photo(
                            row["user_id"], row["file_id"], caption=escape(row["text"]), reply_markup=keyboard
                        )
                    elif row["media_type"] == "video":
                        await bot.send_video(
                            row["user_id"], row["file_id"], caption=escape(row["text"]), reply_markup=keyboard
                        )
                    else:
                        await bot.send_message(row["user_id"], escape(row["text"]), reply_markup=keyboard)
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(min(exc.retry_after + 1, 60))
                    continue
                except (TelegramForbiddenError, TelegramBadRequest):
                    state = "failed"
                await api.post(f"/worker/deliveries/{row['broadcast_id']}/{row['user_id']}/{state}")
                await asyncio.sleep(0.05)
        except APIError:
            logging.getLogger("melkadlc.bot").warning("Broadcast service unavailable")
        await asyncio.sleep(3)


async def main():
    # Library request logs can include the bot token in URLs; keep them disabled.
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").disabled = True
    bot = Bot(
        settings().bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    me = await bot.get_me()
    if settings().bot_username and me.username.lower() != settings().bot_username.lower():
        raise RuntimeError("Configured bot username does not match the token")
    worker = asyncio.create_task(broadcast_worker(bot))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        await api.http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
