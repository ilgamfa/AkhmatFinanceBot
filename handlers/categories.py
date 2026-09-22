"""Команда /categories: список и управление категориями (Фаза 6)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
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

from handlers.stats import escape_markdown
from models import Category
from models.base import CategoryType
from services import categories_repo, users_repo

TITLE = "*Твои категории:*"
EXPENSE_TITLE = "*Траты:*"
INCOME_TITLE = "*Доходы:*"
NO_ONBOARDING_TEXT = "Сначала пройди онбординг: /start"

ADD_BUTTON = "➕ Добавить"
DELETE_BUTTON = "🗑 Удалить"
CANCEL_BUTTON = "❌ Отмена"

CALLBACK_ADD = "categories:add"
CALLBACK_DELETE = "categories:delete"
CALLBACK_DELETE_CANCEL = "categories_del:cancel"
CALLBACK_DELETE_PREFIX = "categories_del:"

ADD_PROMPT = "Название новой категории трат? Например: Кофе"
ADD_EMPTY_NAME = "Напиши название категории. Например: Кофе"
ADDED_TEXT = "Категория добавлена: {name}"
DELETE_LIST_TITLE = "Выбери категорию для удаления:"
NO_CUSTOM_TEXT = "Пока нет своих категорий для удаления."
DELETED_TEXT = "Категория удалена: {name}"


class CategoryFlow(StatesGroup):
    """Ожидание названия новой категории."""

    add_name = State()


def _force_reply(prompt: str) -> ForceReply:
    return ForceReply(input_field_placeholder=prompt, selective=True)


def _manage_keyboard() -> InlineKeyboardMarkup:
    """Кнопки [➕ Добавить] и [🗑 Удалить]."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=ADD_BUTTON, callback_data=CALLBACK_ADD),
                InlineKeyboardButton(
                    text=DELETE_BUTTON, callback_data=CALLBACK_DELETE
                ),
            ]
        ]
    )


def _delete_keyboard(categories: list[Category]) -> InlineKeyboardMarkup:
    """Кнопки пользовательских категорий и отмены."""
    rows = [
        [
            InlineKeyboardButton(
                text=category.name,
                callback_data=f"{CALLBACK_DELETE_PREFIX}{category.id}",
            )
        ]
        for category in categories
    ]
    rows.append(
        [InlineKeyboardButton(text=CANCEL_BUTTON, callback_data=CALLBACK_DELETE_CANCEL)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def build_categories_text(
    session: AsyncSession, telegram_id: int
) -> str:
    """Собирает текст /categories: траты и доходы отдельными блоками."""
    lines = [TITLE]
    sections = (
        (CategoryType.EXPENSE.value, EXPENSE_TITLE),
        (CategoryType.INCOME.value, INCOME_TITLE),
    )
    for category_type, title in sections:
        categories = await categories_repo.get_categories(
            session, telegram_id, category_type
        )
        names = ", ".join(escape_markdown(category.name) for category in categories)
        lines.append("")
        lines.append(f"{title} {names}")
    return "\n".join(lines)


async def _custom_categories(
    session: AsyncSession, telegram_id: int
) -> list[Category]:
    """Пользовательские категории обоих типов."""
    expense = await categories_repo.get_categories(
        session, telegram_id, CategoryType.EXPENSE.value
    )
    income = await categories_repo.get_categories(
        session, telegram_id, CategoryType.INCOME.value
    )
    return [category for category in (*expense, *income) if category.is_custom]


async def cmd_categories(message: Message, session: AsyncSession) -> None:
    """Показывает категории пользователя и кнопки управления."""
    if message.from_user is None:
        return
    user = await users_repo.get_by_telegram_id(session, message.from_user.id)
    if user is None or not user.onboarding_completed:
        await message.answer(NO_ONBOARDING_TEXT)
        return

    text = await build_categories_text(session, message.from_user.id)
    await message.answer(text, parse_mode="Markdown", reply_markup=_manage_keyboard())


async def on_add_pressed(callback: CallbackQuery, state: FSMContext) -> None:
    """[➕ Добавить]: запрашивает название новой категории трат."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await state.set_state(CategoryFlow.add_name)
    await callback.message.answer(
        ADD_PROMPT, reply_markup=_force_reply(ADD_PROMPT)
    )


async def process_add_name(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Создаёт пользовательскую категорию расходов."""
    if message.from_user is None:
        await state.clear()
        return
    name = categories_repo.normalize_name(message.text)
    if not name:
        await message.answer(ADD_EMPTY_NAME)
        return
    await state.clear()
    category = await categories_repo.add_category(
        session,
        message.from_user.id,
        name,
        CategoryType.EXPENSE.value,
        is_custom=True,
    )
    await message.answer(ADDED_TEXT.format(name=category.name))


async def on_delete_pressed(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[🗑 Удалить]: показывает пользовательские категории для удаления."""
    await callback.answer()
    if callback.from_user is None or not isinstance(callback.message, Message):
        return
    categories = await _custom_categories(session, callback.from_user.id)
    if not categories:
        await callback.message.answer(NO_CUSTOM_TEXT)
        return
    await callback.message.answer(
        DELETE_LIST_TITLE, reply_markup=_delete_keyboard(categories)
    )


async def on_delete_picked(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[Название]: удаляет выбранную пользовательскую категорию."""
    await callback.answer()
    if (
        callback.data is None
        or callback.from_user is None
        or not isinstance(callback.message, Message)
    ):
        return
    raw = callback.data[len(CALLBACK_DELETE_PREFIX) :]
    if not raw.isdigit():
        return
    category = await categories_repo.get_category(
        session, callback.from_user.id, int(raw)
    )
    if category is None or not category.is_custom:
        return
    name = category.name
    await categories_repo.delete_category(
        session, callback.from_user.id, category.id
    )
    try:
        await callback.message.edit_text(DELETED_TEXT.format(name=escape_markdown(name)))
    except TelegramBadRequest:
        await callback.message.answer(DELETED_TEXT.format(name=escape_markdown(name)))


async def on_delete_cancel(callback: CallbackQuery) -> None:
    """[❌ Отмена]: убирает список удаления."""
    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text("Отменено")
        except TelegramBadRequest:
            pass


def build_router() -> Router:
    """Создаёт роутер команды /categories."""
    router = Router(name="categories")

    router.message.register(cmd_categories, Command("categories"))
    router.message.register(
        process_add_name, CategoryFlow.add_name, ~F.text.startswith("/")
    )
    router.callback_query.register(on_add_pressed, F.data == CALLBACK_ADD)
    router.callback_query.register(on_delete_pressed, F.data == CALLBACK_DELETE)
    router.callback_query.register(
        on_delete_cancel, F.data == CALLBACK_DELETE_CANCEL
    )
    router.callback_query.register(
        on_delete_picked, F.data.regexp(r"^categories_del:\d+$")
    )
    return router
