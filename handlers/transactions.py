"""Команды /minus, /plus и /correct (Фаза 2)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ForceReply, Message
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import TransactionType
from services import transactions_repo, users_repo
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


class TransactionFlow(StatesGroup):
    """Ожидание суммы после команды без аргумента."""

    awaiting_minus = State()
    awaiting_plus = State()
    awaiting_correct = State()


def _force_reply(prompt: str) -> ForceReply:
    return ForceReply(input_field_placeholder=prompt, selective=True)


async def _apply_expense(
    message: Message, session: AsyncSession, amount: int
) -> None:
    """Списывает сумму и пишет операцию expense."""
    if message.from_user is None:
        return

    user = await users_repo.get_or_create(session, message.from_user.id)
    balance = (user.free_money or 0) - amount
    user.free_money = balance
    await session.commit()

    await transactions_repo.add_transaction(
        session, message.from_user.id, TransactionType.EXPENSE.value, amount
    )

    await message.answer(
        f"Записал: −{format_amount(amount)}\nСвободно: {format_amount(balance)}"
    )
    if balance < 0:
        await message.answer(NEGATIVE_BALANCE_TEXT)


async def _apply_income(
    message: Message, session: AsyncSession, amount: int
) -> None:
    """Начисляет сумму и пишет операцию income."""
    if message.from_user is None:
        return

    user = await users_repo.get_or_create(session, message.from_user.id)
    balance = (user.free_money or 0) + amount
    user.free_money = balance
    await session.commit()

    await transactions_repo.add_transaction(
        session, message.from_user.id, TransactionType.INCOME.value, amount
    )

    await message.answer(
        f"Записал: +{format_amount(amount)}\nСвободно: {format_amount(balance)}"
    )


async def _apply_correction(
    message: Message, session: AsyncSession, new_balance: int
) -> None:
    """Задаёт новый баланс и пишет операцию correction с разницей."""
    if message.from_user is None:
        return

    user = await users_repo.get_or_create(session, message.from_user.id)
    old_balance = user.free_money or 0
    user.free_money = new_balance
    await session.commit()

    await transactions_repo.add_transaction(
        session,
        message.from_user.id,
        TransactionType.CORRECTION.value,
        new_balance - old_balance,
    )

    await message.answer(f"Баланс обновлён: {format_amount(new_balance)}")


async def cmd_minus(
    message: Message, command: CommandObject, session: AsyncSession, state: FSMContext
) -> None:
    """Трата: /minus 5000 или запрос суммы через ForceReply."""
    if command.args and command.args.strip():
        try:
            amount = parse_amount_unsigned(command.args)
        except ValueError:
            await message.answer(MINUS_PARSE_ERROR)
            return
        await _apply_expense(message, session, amount)
        return

    await state.set_state(TransactionFlow.awaiting_minus)
    await message.answer(MINUS_PROMPT, reply_markup=_force_reply(MINUS_PROMPT))


async def cmd_plus(
    message: Message, command: CommandObject, session: AsyncSession, state: FSMContext
) -> None:
    """Доход: /plus 100000 или запрос суммы через ForceReply."""
    if command.args and command.args.strip():
        try:
            amount = parse_amount(command.args)
        except ValueError:
            await message.answer(PLUS_PARSE_ERROR)
            return
        await _apply_income(message, session, amount)
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
    return router
