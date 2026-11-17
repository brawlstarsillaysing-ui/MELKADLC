"""Run real aiogram handlers against the FastAPI application. Telegram sends are captured locally."""

import asyncio
from datetime import UTC, datetime

import httpx
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import Chat, Message, Update
from sqlalchemy.orm import Session

from backend import services as s
from backend.config import settings
from backend.db import engine


class TelegramCapture(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        return Message(
            message_id=100,
            date=datetime.now(UTC),
            chat=Chat(id=method.chat_id, type="private"),
            text=getattr(method, "text", ""),
        )

    async def stream_content(self, *args, **kwargs):
        yield b""


def test_customer_start_language_trial_and_menu(client, monkeypatch):
    from backend.main import app
    from telegram_bot import main

    async def run():
        capture = TelegramCapture()
        bot = Bot("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi", session=capture)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer " + settings().service_token.get_secret_value()},
        ) as transport:
            monkeypatch.setattr(main.api, "http", transport)
            person = {"id": 44, "is_bot": False, "first_name": "Test", "username": "test"}
            message = {
                "message_id": 1,
                "date": int(datetime.now(UTC).timestamp()),
                "chat": {"id": 44, "type": "private"},
                "from": person,
                "text": "/start",
            }
            await main.dp.feed_update(bot, Update.model_validate({"update_id": 1, "message": message}))
            assert "WELCOME TO MELKADLC" in capture.calls[-1].text
            for i, payload in enumerate(["lang:uk", "trial", "get_trial", "menu"], 2):
                await main.dp.feed_update(
                    bot,
                    Update.model_validate(
                        {
                            "update_id": i,
                            "callback_query": {
                                "id": str(i),
                                "from": person,
                                "chat_instance": "test",
                                "data": payload,
                                "message": {
                                    **message,
                                    "from": {"id": 123456789, "is_bot": True, "first_name": "Bot"},
                                },
                            },
                        }
                    ),
                )
            texts = [getattr(x, "text", "") or "" for x in capture.calls]
            assert any("MELKA-" in x for x in texts)
            assert any("Виберіть розділ" in x for x in texts)
        await bot.session.close()

    asyncio.run(run())
    with Session(engine()) as db:
        assert s.profile(db, 44)["trial_issued"] == 1
        assert s.profile(db, 44)["language"] == "uk"


def test_forged_admin_callback_does_not_mutate(client, monkeypatch):
    from backend.main import app
    from telegram_bot import main

    async def run():
        capture = TelegramCapture()
        bot = Bot("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi", session=capture)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer " + settings().service_token.get_secret_value()},
        ) as transport:
            monkeypatch.setattr(main.api, "http", transport)
            await main.dp.feed_update(
                bot,
                Update.model_validate(
                    {
                        "update_id": 50,
                        "callback_query": {
                            "id": "50",
                            "from": {"id": 55, "is_bot": False, "first_name": "Test"},
                            "chat_instance": "test",
                            "data": "actions",
                            "message": {
                                "message_id": 1,
                                "date": int(datetime.now(UTC).timestamp()),
                                "chat": {"id": 55, "type": "private"},
                                "from": {"id": 123456789, "is_bot": True, "first_name": "Bot"},
                                "text": "Menu",
                            },
                        },
                    }
                ),
            )
            assert any("Недостаточно прав" in (getattr(x, "text", "") or "") for x in capture.calls)
        await bot.session.close()

    asyncio.run(run())
