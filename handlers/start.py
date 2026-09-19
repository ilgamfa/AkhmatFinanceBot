"""Команды /start и /cancel."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from handlers import onboarding
from handlers.stats import build_stats_text
from services import users_repo


async def cmd_start(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """Приветствие: интро с кнопками или сводка для вернувшихся."""
    if message.from_user is None:
        return

    user = await users_repo.get_or_create(session, message.from_user.id)
    if user.onboarding_completed:
        await message.answer("С возвращением!")
        await message.answer(await build_stats_text(session, user))
        return

    await onboarding.show_intro(message, state)


async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Прерывает текущий диалог."""
    await state.clear()
    await message.answer("Отменил. Начать заново — /start")


def build_router() -> Router:
    """Создаёт роутер стартовых команд."""
    router = Router(name="start")
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_cancel, Command("cancel"))
    return router
