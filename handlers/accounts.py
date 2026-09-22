"""Команда /accounts: счета и переименование карты (Фаза 5.1)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from handlers.stats import escape_markdown, member_label
from models import Account, User
from models.account import CARD
from services import accounts_repo, family_repo, users_repo
from utils.money import format_amount

TITLE_SOLO = "*Твои счета:*"
TITLE_FAMILY = "*Счета семьи:*"

RENAME_BUTTON_TEXT = "✏️ Переименовать карту"
CALLBACK_RENAME = "accounts:rename"
RENAME_PROMPT = "Новое название карты? Например: Т-Банк, Сбер, Зарплатная"
RENAMED_TEXT = "Карта переименована: {name}"
NO_ACCOUNTS_TEXT = "Счетов пока нет. Пройди онбординг: /start"


class AccountsFlow(StatesGroup):
    """Ожидание нового названия карты."""

    rename_card = State()


def _rename_keyboard() -> InlineKeyboardMarkup:
    """Кнопка переименования карты."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=RENAME_BUTTON_TEXT, callback_data=CALLBACK_RENAME
                )
            ]
        ]
    )


def _account_line(account: Account, owner: str | None) -> str:
    """Строка счёта: «Т-Банк (карта): 50 000 ₽» / «Копилка (жена): 0 ₽»."""
    name = escape_markdown(account.name)
    amount = format_amount(account.balance or 0)
    if account.type == CARD:
        label = f"{owner}, карта" if owner else "карта"
        return f"{name} ({escape_markdown(label)}): {amount}"
    if owner:
        return f"{name} ({escape_markdown(owner)}): {amount}"
    return f"{name}: {amount}"


async def build_accounts_text(session: AsyncSession, user: User) -> str:
    """Собирает текст /accounts: свои счета или счета обоих в семье."""
    family = await family_repo.get_family(session, user.telegram_id)
    if family is None:
        accounts = await accounts_repo.get_accounts(session, user.telegram_id)
        lines = [TITLE_SOLO, ""]
        lines.extend(_account_line(account, None) for account in accounts)
        return "\n".join(lines)

    members = await family_repo.get_family_members(session, family.id)
    names = {member.telegram_id: member.first_name for member in members}
    accounts = await accounts_repo.get_family_accounts(session, family.id)
    lines = [TITLE_FAMILY, ""]
    for account in accounts:
        owner = member_label(
            account.telegram_id, user.telegram_id, names.get(account.telegram_id)
        )
        lines.append(_account_line(account, owner))
    return "\n".join(lines)


async def cmd_accounts(message: Message, session: AsyncSession) -> None:
    """Показывает счета пользователя и кнопку переименования карты."""
    if message.from_user is None:
        return
    user = await users_repo.get_by_telegram_id(session, message.from_user.id)
    if user is None or not user.onboarding_completed:
        await message.answer(NO_ACCOUNTS_TEXT)
        return

    text = await build_accounts_text(session, user)
    await message.answer(text, parse_mode="Markdown", reply_markup=_rename_keyboard())


async def on_rename_pressed(callback: CallbackQuery, state: FSMContext) -> None:
    """[✏️ Переименовать карту]: запрашивает новое название."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await state.set_state(AccountsFlow.rename_card)
    await callback.message.answer(
        RENAME_PROMPT,
        reply_markup=ForceReply(
            input_field_placeholder=RENAME_PROMPT, selective=True
        ),
    )


async def process_card_rename(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Принимает новое название карты. Копилку не переименовывает."""
    if message.from_user is None:
        await state.clear()
        return
    new_name = accounts_repo.normalize_card_name(message.text)
    await state.clear()

    account = await accounts_repo.rename_account(
        session, message.from_user.id, CARD, new_name
    )
    if account is None:
        await message.answer(NO_ACCOUNTS_TEXT)
        return
    await message.answer(RENAMED_TEXT.format(name=account.name))


def build_router() -> Router:
    """Создаёт роутер команды /accounts."""
    router = Router(name="accounts")

    router.message.register(cmd_accounts, Command("accounts"))
    router.message.register(
        process_card_rename, AccountsFlow.rename_card, ~F.text.startswith("/")
    )
    router.callback_query.register(on_rename_pressed, F.data == CALLBACK_RENAME)
    return router
