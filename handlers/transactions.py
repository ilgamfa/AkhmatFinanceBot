"""Команды /minus, /plus и /correct, выбор категории (Фазы 2 и 6)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
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

from models import Category, Transaction
from models.base import CategoryType, TransactionType
from services import accounts_repo, categories_repo, transactions_repo, users_repo
from utils.money import format_amount, parse_amount, parse_amount_unsigned

MINUS_PROMPT = "Напиши сумму траты. Например: 5000"
PLUS_PROMPT = "Напиши сумму дохода. Например: 100000"
CORRECT_PROMPT = "Напиши новую сумму свободных денег. Например: 12000"
MINUS_PARSE_ERROR = "Не понял сумму. Напиши число, например: 5000"
PLUS_PARSE_ERROR = "Не понял сумму. Напиши число, например: 100000"
CORRECT_PARSE_ERROR = "Не понял сумму. Напиши число, например: 12000"
NEGATIVE_BALANCE_TEXT = (
    "Внимание: баланс ушёл в минус. "
    "Возможно, ты забыл внести доход. Используй /correct."
)

# --- категории (Фаза 6) ---
CATEGORY_OWN_BUTTON = "➕ Своя"
CATEGORY_NONE_BUTTON = "❌ Без категории"
CATEGORY_PICK_EXPENSE = "Выбери категорию траты:"
CATEGORY_PICK_INCOME = "Выбери категорию дохода:"
CATEGORY_NAME_PROMPT = "Название категории? Например: Кофе"
CATEGORY_EMPTY_NAME = "Напиши название категории. Например: Кофе"
CATEGORY_NOT_FOUND = "Категория «{name}» не найдена — записал без категории."
CATEGORY_SAVED = "Категория: {name} ✅"
CATEGORY_NONE_SAVED = "Записал без категории."
CATEGORY_ADDED = "Добавил категорию: {name} ✅"

CALLBACK_CATEGORY_PICK = "cat_pick:"
CALLBACK_CATEGORY_OWN = "cat_own:"
CALLBACK_CATEGORY_NONE = "cat_none:"


class TransactionFlow(StatesGroup):
    """Ожидание суммы после команды без аргумента."""

    awaiting_minus = State()
    awaiting_plus = State()
    awaiting_correct = State()
    # Ожидание названия своей категории; данные — category_tx_id, category_type.
    awaiting_category_name = State()


def _force_reply(prompt: str) -> ForceReply:
    return ForceReply(input_field_placeholder=prompt, selective=True)


def _parse_transaction_args(
    raw: str, *, unsigned: bool
) -> tuple[int, str | None]:
    """Разбирает аргументы команды: первый токен — сумма, остаток — категория."""
    parts = raw.strip().split(maxsplit=1)
    amount = parse_amount_unsigned(parts[0]) if unsigned else parse_amount(parts[0])
    category_name = parts[1].strip() if len(parts) > 1 else None
    return amount, category_name or None


def _category_keyboard(
    categories: list[Category], transaction_id: int
) -> InlineKeyboardMarkup:
    """Кнопки категорий: названия, затем [➕ Своя] / [❌ Без категории]."""
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(categories), 2):
        rows.append(
            [
                InlineKeyboardButton(
                    text=category.name,
                    callback_data=(
                        f"{CALLBACK_CATEGORY_PICK}{transaction_id}:{category.id}"
                    ),
                )
                for category in categories[index : index + 2]
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=CATEGORY_OWN_BUTTON,
                callback_data=f"{CALLBACK_CATEGORY_OWN}{transaction_id}",
            ),
            InlineKeyboardButton(
                text=CATEGORY_NONE_BUTTON,
                callback_data=f"{CALLBACK_CATEGORY_NONE}{transaction_id}",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_category_buttons(
    message: Message,
    session: AsyncSession,
    telegram_id: int,
    transaction_id: int,
    category_type: str,
) -> None:
    """Показывает кнопки категорий для уже записанной операции."""
    categories = await categories_repo.get_categories(
        session, telegram_id, category_type
    )
    if not categories:
        return
    prompt = (
        CATEGORY_PICK_INCOME
        if category_type == CategoryType.INCOME.value
        else CATEGORY_PICK_EXPENSE
    )
    await message.answer(
        prompt, reply_markup=_category_keyboard(categories, transaction_id)
    )


async def _apply_expense(
    message: Message,
    session: AsyncSession,
    amount: int,
    category_name: str | None = None,
) -> None:
    """Списывает сумму с карты, пишет expense и предлагает категорию."""
    if message.from_user is None:
        return

    telegram_id = message.from_user.id
    await users_repo.get_or_create(session, telegram_id)
    card = await accounts_repo.ensure_account(session, telegram_id, "card")
    balance = card.balance - amount
    card.balance = balance
    await session.commit()
    await session.refresh(card)

    category = None
    if category_name:
        category = await categories_repo.find_by_name(
            session, telegram_id, category_name, CategoryType.EXPENSE.value
        )

    transaction = await transactions_repo.add_transaction(
        session,
        telegram_id,
        TransactionType.EXPENSE.value,
        amount,
        card.id,
        category.id if category is not None else None,
    )

    lines = [f"Записал: −{format_amount(amount)}", f"Свободно: {format_amount(balance)}"]
    if category is not None:
        lines.append(f"Категория: {category.name}")
    await message.answer("\n".join(lines))
    if balance < 0:
        await message.answer(NEGATIVE_BALANCE_TEXT)

    if category is not None:
        return
    if category_name:
        await message.answer(CATEGORY_NOT_FOUND.format(name=category_name))
    await _show_category_buttons(
        message, session, telegram_id, transaction.id, CategoryType.EXPENSE.value
    )


async def _apply_income(
    message: Message,
    session: AsyncSession,
    amount: int,
    category_name: str | None = None,
) -> None:
    """Начисляет сумму на карту, пишет income и предлагает категорию."""
    if message.from_user is None:
        return

    telegram_id = message.from_user.id
    await users_repo.get_or_create(session, telegram_id)
    card = await accounts_repo.ensure_account(session, telegram_id, "card")
    balance = card.balance + amount
    card.balance = balance
    await session.commit()
    await session.refresh(card)

    category = None
    if category_name:
        category = await categories_repo.find_by_name(
            session, telegram_id, category_name, CategoryType.INCOME.value
        )

    transaction = await transactions_repo.add_transaction(
        session,
        telegram_id,
        TransactionType.INCOME.value,
        amount,
        card.id,
        category.id if category is not None else None,
    )

    lines = [f"Записал: +{format_amount(amount)}", f"Свободно: {format_amount(balance)}"]
    if category is not None:
        lines.append(f"Категория: {category.name}")
    await message.answer("\n".join(lines))

    if category is not None:
        return
    if category_name:
        await message.answer(CATEGORY_NOT_FOUND.format(name=category_name))
    await _show_category_buttons(
        message, session, telegram_id, transaction.id, CategoryType.INCOME.value
    )


async def _apply_correction(
    message: Message, session: AsyncSession, new_balance: int
) -> None:
    """Задаёт новый баланс карты и пишет операцию correction с разницей."""
    if message.from_user is None:
        return

    await users_repo.get_or_create(session, message.from_user.id)
    card = await accounts_repo.ensure_account(session, message.from_user.id, "card")
    old_balance = card.balance
    card.balance = new_balance
    await session.commit()
    await session.refresh(card)

    await transactions_repo.add_transaction(
        session,
        message.from_user.id,
        TransactionType.CORRECTION.value,
        new_balance - old_balance,
        card.id,
    )

    await message.answer(f"Баланс обновлён: {format_amount(new_balance)}")


async def cmd_minus(
    message: Message, command: CommandObject, session: AsyncSession, state: FSMContext
) -> None:
    """Трата: /minus 5000 [категория] или запрос суммы через ForceReply."""
    if command.args and command.args.strip():
        try:
            amount, category_name = _parse_transaction_args(
                command.args, unsigned=True
            )
        except ValueError:
            await message.answer(MINUS_PARSE_ERROR)
            return
        await _apply_expense(message, session, amount, category_name)
        return

    await state.set_state(TransactionFlow.awaiting_minus)
    await message.answer(MINUS_PROMPT, reply_markup=_force_reply(MINUS_PROMPT))


async def cmd_plus(
    message: Message, command: CommandObject, session: AsyncSession, state: FSMContext
) -> None:
    """Доход: /plus 100000 [категория] или запрос суммы через ForceReply."""
    if command.args and command.args.strip():
        try:
            amount, category_name = _parse_transaction_args(
                command.args, unsigned=False
            )
        except ValueError:
            await message.answer(PLUS_PARSE_ERROR)
            return
        await _apply_income(message, session, amount, category_name)
        return

    await state.set_state(TransactionFlow.awaiting_plus)
    await message.answer(PLUS_PROMPT, reply_markup=_force_reply(PLUS_PROMPT))


async def cmd_correct(
    message: Message, command: CommandObject, session: AsyncSession, state: FSMContext
) -> None:
    """Выравнивание баланса: /correct 12000 или запрос суммы через ForceReply."""
    if command.args and command.args.strip():
        try:
            new_balance = parse_amount(command.args)
        except ValueError:
            await message.answer(CORRECT_PARSE_ERROR)
            return
        await _apply_correction(message, session, new_balance)
        return

    await state.set_state(TransactionFlow.awaiting_correct)
    await message.answer(CORRECT_PROMPT, reply_markup=_force_reply(CORRECT_PROMPT))


async def process_awaiting_minus(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """Принимает сумму траты после ForceReply."""
    try:
        amount = parse_amount_unsigned(message.text)
    except ValueError:
        await message.answer(MINUS_PARSE_ERROR)
        return
    await state.clear()
    await _apply_expense(message, session, amount)


async def process_awaiting_plus(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """Принимает сумму дохода после ForceReply."""
    try:
        amount = parse_amount(message.text)
    except ValueError:
        await message.answer(PLUS_PARSE_ERROR)
        return
    await state.clear()
    await _apply_income(message, session, amount)


async def process_awaiting_correct(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """Принимает новую сумму баланса после ForceReply."""
    try:
        new_balance = parse_amount(message.text)
    except ValueError:
        await message.answer(CORRECT_PARSE_ERROR)
        return
    await state.clear()
    await _apply_correction(message, session, new_balance)


# --- выбор категории (Фаза 6) -------------------------------------------------


async def _own_transaction(
    session: AsyncSession, telegram_id: int, transaction_id: int
) -> Transaction | None:
    """Операция пользователя по id или None."""
    transaction = await session.get(Transaction, transaction_id)
    if transaction is None or transaction.telegram_id != telegram_id:
        return None
    return transaction


def _callback_transaction_id(data: str, prefix: str) -> int | None:
    """Извлекает id операции из callback_data."""
    raw = data[len(prefix) :]
    return int(raw) if raw.isdigit() else None


async def _safe_edit(message: Message, text: str) -> None:
    """Редактирует сообщение, убирая клавиатуру; игнорирует ошибки Telegram."""
    try:
        await message.edit_text(text)
    except TelegramBadRequest:
        pass


async def on_category_pick(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[Категория]: сохраняет category_id у операции."""
    await callback.answer()
    if (
        callback.data is None
        or callback.from_user is None
        or not isinstance(callback.message, Message)
    ):
        return

    body = callback.data[len(CALLBACK_CATEGORY_PICK) :]
    parts = body.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return
    transaction_id, category_id = int(parts[0]), int(parts[1])

    if await _own_transaction(session, callback.from_user.id, transaction_id) is None:
        return
    category = await categories_repo.get_category(
        session, callback.from_user.id, category_id
    )
    if category is None:
        return
    await transactions_repo.set_category(session, transaction_id, category.id)
    await _safe_edit(callback.message, CATEGORY_SAVED.format(name=category.name))


async def on_category_own(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    """[➕ Своя]: запрашивает название новой категории."""
    await callback.answer()
    if (
        callback.data is None
        or callback.from_user is None
        or not isinstance(callback.message, Message)
    ):
        return

    transaction_id = _callback_transaction_id(
        callback.data, CALLBACK_CATEGORY_OWN
    )
    if transaction_id is None:
        return
    transaction = await _own_transaction(
        session, callback.from_user.id, transaction_id
    )
    if transaction is None:
        return

    await state.set_state(TransactionFlow.awaiting_category_name)
    await state.update_data(
        category_tx_id=transaction.id, category_type=transaction.type
    )
    await callback.message.answer(
        CATEGORY_NAME_PROMPT, reply_markup=_force_reply(CATEGORY_NAME_PROMPT)
    )


async def on_category_none(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[❌ Без категории]: оставляет операцию без категории."""
    await callback.answer()
    if (
        callback.data is None
        or callback.from_user is None
        or not isinstance(callback.message, Message)
    ):
        return

    transaction_id = _callback_transaction_id(
        callback.data, CALLBACK_CATEGORY_NONE
    )
    if transaction_id is None:
        return
    if await _own_transaction(session, callback.from_user.id, transaction_id) is None:
        return
    await _safe_edit(callback.message, CATEGORY_NONE_SAVED)


async def process_category_name(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Принимает название своей категории и привязывает её к операции."""
    if message.from_user is None:
        await state.clear()
        return

    data = await state.get_data()
    transaction_id = data.get("category_tx_id")
    category_type = data.get("category_type", CategoryType.EXPENSE.value)
    name = categories_repo.normalize_name(message.text)
    if not name:
        await message.answer(CATEGORY_EMPTY_NAME)
        return

    await state.clear()
    if transaction_id is None:
        return
    transaction = await _own_transaction(
        session, message.from_user.id, transaction_id
    )
    if transaction is None:
        return

    category = await categories_repo.add_category(
        session, message.from_user.id, name, category_type, is_custom=True
    )
    await transactions_repo.set_category(session, transaction.id, category.id)
    await message.answer(CATEGORY_ADDED.format(name=category.name))


def build_router() -> Router:
    """Создаёт роутер команд операций."""
    router = Router(name="transactions")
    router.message.register(cmd_minus, Command("minus"))
    router.message.register(cmd_plus, Command("plus"))
    router.message.register(cmd_correct, Command("correct"))
    router.message.register(
        process_awaiting_minus, TransactionFlow.awaiting_minus, ~F.text.startswith("/")
    )
    router.message.register(
        process_awaiting_plus, TransactionFlow.awaiting_plus, ~F.text.startswith("/")
    )
    router.message.register(
        process_awaiting_correct, TransactionFlow.awaiting_correct, ~F.text.startswith("/")
    )
    router.message.register(
        process_category_name,
        TransactionFlow.awaiting_category_name,
        ~F.text.startswith("/"),
    )
    router.callback_query.register(
        on_category_pick, F.data.startswith(CALLBACK_CATEGORY_PICK)
    )
    router.callback_query.register(
        on_category_own, F.data.startswith(CALLBACK_CATEGORY_OWN)
    )
    router.callback_query.register(
        on_category_none, F.data.startswith(CALLBACK_CATEGORY_NONE)
    )
    return router
