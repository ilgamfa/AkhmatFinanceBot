"""Общие фикстуры для тестов."""

from __future__ import annotations

import itertools
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import Database

# Тестовый токен: config.py требует BOT_TOKEN, поэтому задаём до импорта bot.
os.environ.setdefault("BOT_TOKEN", "123456:TEST")


class StubSession(BaseSession):
    """Сессия вместо сети: запоминает исходящие сообщения."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[SendMessage] = []
        self.last_reply_markup: object | None = None

    async def make_request(self, bot: Bot, method, timeout=None):  # type: ignore[override]
        if isinstance(method, SendMessage):
            self.sent.append(method)
            self.last_reply_markup = method.reply_markup
            message = Message(
                message_id=len(self.sent),
                date=datetime.now(UTC),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text or "",
            )
            return message
        return True

    async def stream_content(  # type: ignore[override]
        self,
        url,
        headers=None,
        timeout=30,
        chunk_size=65536,
        raise_for_status=True,
    ):
        if False:  # pragma: no cover - пустой асинхронный генератор
            yield b""

    async def close(self) -> None:
        return None


@pytest_asyncio.fixture
async def database() -> AsyncIterator[Database]:
    """In-memory SQLite с общей соединением на время теста."""
    db = Database("sqlite+aiosqlite:///:memory:", use_static_pool=True)
    await db.init()
    try:
        yield db
    finally:
        await db.dispose()


@pytest_asyncio.fixture
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    """Асинхронная сессия к тестовой БД."""
    async with database.session_factory() as db_session:
        yield db_session


@pytest_asyncio.fixture
async def bot() -> AsyncIterator[Bot]:
    """Бот со стабом сессии вместо сети."""
    bot = Bot(token="123456:TEST", session=StubSession())
    yield bot
    await bot.session.close()


@pytest_asyncio.fixture
async def dispatcher(database: Database) -> Dispatcher:
    """Диспетчер бота, подключённый к тестовой БД."""
    from bot import create_dispatcher

    return create_dispatcher(database)


@pytest_asyncio.fixture
async def send_message(
    bot: Bot, dispatcher: Dispatcher
) -> AsyncIterator[Callable[..., Awaitable[list[str]]]]:
    """Возвращает функцию отправки сообщения боту и сбора ответов."""
    counter = itertools.count(1)

    async def _send(
        text: str, *, user_id: int = 1, first_name: str = "Test"
    ) -> list[str]:
        update_id = next(counter)
        update = Update(
            update_id=update_id,
            message=Message(
                message_id=update_id,
                date=datetime.now(UTC),
                chat=Chat(id=user_id, type="private"),
                from_user=TgUser(id=user_id, is_bot=False, first_name=first_name),
                text=text,
            ),
        )
        before = len(bot.session.sent)
        await dispatcher.feed_update(bot, update)
        return [message.text or "" for message in bot.session.sent[before:]]

    yield _send


@pytest_asyncio.fixture
async def send_callback(
    bot: Bot, dispatcher: Dispatcher
) -> AsyncIterator[Callable[..., Awaitable[list[str]]]]:
    """Возвращает функцию нажатия inline-кнопки и сбора ответов бота."""
    counter = itertools.count(1000)

    async def _press(
        data: str, *, user_id: int = 1, first_name: str = "Test"
    ) -> list[str]:
        update_id = next(counter)
        update = Update(
            update_id=update_id,
            callback_query=CallbackQuery(
                id=f"cb{update_id}",
                from_user=TgUser(id=user_id, is_bot=False, first_name=first_name),
                chat_instance=str(user_id),
                data=data,
                message=Message(
                    message_id=update_id,
                    date=datetime.now(UTC),
                    chat=Chat(id=user_id, type="private"),
                    from_user=TgUser(id=999, is_bot=True, first_name="Bot"),
                    text="prompt",
                ),
            ),
        )
        before = len(bot.session.sent)
        await dispatcher.feed_update(bot, update)
        return [message.text or "" for message in bot.session.sent[before:]]

    yield _press
