"""Точка входа Telegram-бота «Карманный финсоветник»."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

from config import BOT_TOKEN

logger = logging.getLogger(__name__)

START_MESSAGE = "Привет! Я твой карманный финсоветник."


async def cmd_start(message: Message) -> None:
    """Отправляет приветствие в ответ на команду /start."""
    await message.answer(START_MESSAGE)


def create_dispatcher() -> Dispatcher:
    """Создаёт диспетчер и регистрирует обработчики."""
    dp = Dispatcher()
    dp.message.register(cmd_start, CommandStart())
    return dp


async def main() -> None:
    """Запускает бота в режиме long-polling."""
    bot = Bot(token=BOT_TOKEN)
    dp = create_dispatcher()
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main())
