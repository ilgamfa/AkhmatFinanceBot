"""Команды /start и /cancel, диплинк-приглашение в семью."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from handlers import onboarding
from handlers.family import JOINED_TEXT as FAMILY_JOINED_TEXT
from handlers.stats import build_stats_text
from services import accounts_repo, family_repo, users_repo

DEEPLINK_PREFIX = "family_"

FAMILY_NOT_FOUND = "Код не найден. Проверь и попробуй снова."
FAMILY_ALREADY = "Ты уже в семье: {name}"
FAMILY_FULL = (
    "В этой семье уже два участника. Больше человек — в подписке."
)
FAMILY_OFFER = "Тебя пригласили в семью: {name}. Присоединиться?"
FAMILY_JOIN_YES = "✅ Да"
FAMILY_JOIN_NO = "❌ Нет"
FAMILY_JOIN_CANCEL = "Отменено."


def _invite_keyboard(invite_code: str) -> InlineKeyboardMarkup:
    """Кнопки [✅ Да] / [❌ Нет] под приглашением из диплинка."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=FAMILY_JOIN_YES, callback_data=f"family_link:yes:{invite_code}"
                ),
                InlineKeyboardButton(
                    text=FAMILY_JOIN_NO, callback_data="family_link:no"
                ),
            ]
        ]
    )


async def cmd_start(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """Приветствие: интро с кнопками или сводка для вернувшихся."""
    if message.from_user is None:
        return

    user = await users_repo.get_or_create(session, message.from_user.id)
    if user.onboarding_completed:
        await message.answer("С возвращением!")
        await message.answer(
            await build_stats_text(session, user), parse_mode="Markdown"
        )
        return

    await onboarding.show_intro(message, state)


async def cmd_start_deeplink(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Обрабатывает /start family_<код> и предлагает присоединиться."""
    if message.from_user is None:
        return

    payload = (command.args or "").strip()
    if not payload.startswith(DEEPLINK_PREFIX):
        await cmd_start(message, session, state)
        return

    invite_code = payload[len(DEEPLINK_PREFIX) :]
    family = await family_repo.get_family_by_code(session, invite_code)
    if family is None:
        await message.answer(FAMILY_NOT_FOUND)
        return

    own = await family_repo.get_family(session, message.from_user.id)
    if own is not None:
        await message.answer(FAMILY_ALREADY.format(name=own.name))
        return

    members = await family_repo.get_family_members(session, family.id)
    if len(members) >= family_repo.MAX_FAMILY_MEMBERS:
        await message.answer(FAMILY_FULL)
        return

    await message.answer(
        FAMILY_OFFER.format(name=family.name),
        reply_markup=_invite_keyboard(family.invite_code),
    )


async def on_family_link_yes(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """[✅ Да]: присоединяет к семье и запускает онбординг новому участнику."""
    await callback.answer()
    if (
        callback.data is None
        or callback.from_user is None
        or not isinstance(callback.message, Message)
    ):
        return
    message = callback.message
    telegram_id = callback.from_user.id
    invite_code = callback.data.split(":", 2)[2]

    try:
        family = await family_repo.join_family(
            session, telegram_id, invite_code, callback.from_user.first_name
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(FAMILY_JOINED_TEXT.format(name=family.name))

    user = await users_repo.get_or_create(session, telegram_id)
    if user.onboarding_completed:
        await accounts_repo.create_accounts(
            session, telegram_id, family_id=family.id
        )
        await message.answer(
            await build_stats_text(session, user), parse_mode="Markdown"
        )
        return

    # Новому участнику счета создаст онбординг — сразу с балансом и family_id.
    await state.update_data(family_id=family.id)
    await onboarding.show_intro(message, state)


async def on_family_link_no(callback: CallbackQuery) -> None:
    """[❌ Нет]: отменяет присоединение."""
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(FAMILY_JOIN_CANCEL)


async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Прерывает текущий диалог."""
    await state.clear()
    await message.answer("Отменил. Начать заново — /start")


def build_router() -> Router:
    """Создаёт роутер стартовых команд."""
    router = Router(name="start")
    router.message.register(cmd_start_deeplink, CommandStart(deep_link=True))
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_cancel, Command("cancel"))
    router.callback_query.register(
        on_family_link_yes, F.data.startswith("family_link:yes:")
    )
    router.callback_query.register(on_family_link_no, F.data == "family_link:no")
    return router
