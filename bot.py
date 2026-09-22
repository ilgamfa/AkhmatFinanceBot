"""Точка входа Telegram-бота «Карманный финсоветник»."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from config import BOT_TOKEN, DB_PATH
from handlers import (
    accounts,
    allocate,
    debts,
    family,
    forecast,
    goals,
    onboarding,
    savings,
    start,
    stats,
    transactions,
)
from handlers.middlewares import DbSessionMiddleware
from models.database import Database, build_sqlite_url

logger = logging.getLogger(__name__)


def create_dispatcher(database: Database) -> Dispatcher:
    """Создаёт диспетчер, подключает middleware и роутеры."""
    dp = Dispatcher()
    dp.update.middleware(DbSessionMiddleware(database.session_factory))
    dp.include_routers(
        start.build_router(),
        transactions.build_router(),
        debts.build_router(),
        goals.build_router(),
        savings.build_router(),
        allocate.build_router(),
        family.build_router(),
        accounts.build_router(),
        forecast.build_router(),
        stats.build_router(),
        onboarding.build_router(),
    )
    return dp


async def main() -> None:
    """Поднимает БД и запускает long-polling."""
    database = Database(build_sqlite_url(DB_PATH))
    await database.init()
    bot = Bot(token=BOT_TOKEN)
    dp = create_dispatcher(database)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await database.dispose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main())
