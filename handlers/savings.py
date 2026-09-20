"""Команда /savings: копилка и пополнение (Фаза 4)."""

from __future__ import annotations

from aiogram import F, Router
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

from models import Goal
from models.base import TransactionType
from services import (
    allocations_repo,
    goals_repo,
    savings_repo,
    transactions_repo,
    users_repo,
)
from services.calculations import goal_emoji
from utils.money import format_amount, parse_amount

NO_SAVINGS_TEXT = "Копилка пуста"
ADD_PROMPT = "Сумма пополнения?"
ADD_PARSE_ERROR = "Не понял сумму. Напиши число, например: 50000"
ADD_FORMAT_ERROR = "Формат: /savings add 50000"
POSITIVE_ERROR = "Сумма должна быть больше нуля."

ADD_BUTTON_TEXT = "➕ Пополнить"
ALLOCATE_BUTTON_TEXT = "💰 Распределить"

CALLBACK_ADD = "savings:add"
CALLBACK_ALLOCATE = "alloc:start"


class SavingsFlow(StatesGroup):
    """Ожидание суммы пополнения копилки."""

    add_amount = State()


def _force_reply(prompt: str) -> ForceReply:
    return ForceReply(input_field_placeholder=prompt, selective=True)


def _manage_keyboard() -> InlineKeyboardMarkup:
    """Кнопки управления копилкой."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=ADD_BUTTON_TEXT, callback_data=CALLBACK_ADD
                ),
                InlineKeyboardButton(
                    text=ALLOCATE_BUTTON_TEXT, callback_data=CALLBACK_ALLOCATE
                ),
            ]
        ]
    )


def format_savings_text(
    goals: list[Goal],
    allocated_by_goal: dict[int, int],
    balance: int,
    free: int,
) -> str:
    """Собирает текст копилки: баланс, закреплённое по целям, свободное."""
    lines = [f"Копилка: {format_amount(balance)}"]
    rows = [
        f"{goal_emoji(goal.name)} {goal.name}: "
        f"{format_amount(allocated_by_goal.get(goal.id, 0))}"
        for goal in goals
        if allocated_by_goal.get(goal.id, 0)
    ]
    if rows:
        lines.append("")
        lines.append("Закреплено за целями:")
        lines.extend(rows)
    lines.append("")
    lines.append(f"Свободно в копилке: {format_amount(free)}")
    return "\n".join(lines)


async def _apply_amount(
    message: Message, session: AsyncSession, raw: str
) -> None:
    """Пополняет копилку: свободные деньги ≥ сумма, минус из free_money."""
    if message.from_user is None:
        return
    try:
        amount = parse_amount(raw)
    except ValueError:
        await message.answer(ADD_PARSE_ERROR)
        return
    if amount <= 0:
        await message.answer(POSITIVE_ERROR)
        return

    user = await users_repo.get_or_create(session, message.from_user.id)
    free_money = user.free_money or 0
    if amount > free_money:
        await message.answer(
            f"Недостаточно свободных денег. Свободно: {format_amount(free_money)}"
        )
        return

    user.free_money = free_money - amount
    await session.commit()

    balance = await savings_repo.add_to_savings(session, message.from_user.id, amount)
    await transactions_repo.add_transaction(
        session,
        message.from_user.id,
        TransactionType.SAVINGS_ADD.value,
        amount,
    )
    free_savings = await savings_repo.get_free_in_savings(
        session, message.from_user.id
    )
    await message.answer(
        f"Пополнено: {format_amount(amount)}\n"
        f"Копилка: {format_amount(balance)}\n"
        f"Свободно: {format_amount(free_savings)}"
    )


async def _show_savings(message: Message, session: AsyncSession) -> None:
    """Показывает копилку с распределением."""
    if message.from_user is None:
        return
    telegram_id = message.from_user.id
    balance = await savings_repo.get_savings(session, telegram_id)
    if balance <= 0:
        await message.answer(NO_SAVINGS_TEXT, reply_markup=_manage_keyboard())
        return

    goals = await goals_repo.get_goals(session, telegram_id)
    allocated = await allocations_repo.get_allocations_by_user(
        session, telegram_id
    )
    free = await savings_repo.get_free_in_savings(session, telegram_id)
    await message.answer(
        format_savings_text(goals, allocated, balance, free),
        reply_markup=_manage_keyboard(),
    )


async def cmd_savings(
    message: Message, command: CommandObject, session: AsyncSession
) -> None:
    """Команда /savings: показывает копилку или пополняет её (/savings add N)."""
    args = (command.args or "").strip()
    if args:
        parts = args.split(maxsplit=1)
        if parts[0].lower() != "add" or len(parts) != 2:
            await message.answer(ADD_FORMAT_ERROR)
            return
        await _apply_amount(message, session, parts[1])
        return
    await _show_savings(message, session)


async def on_add_pressed(callback: CallbackQuery, state: FSMContext) -> None:
    """[➕ Пополнить]: запрашивает сумму пополнения."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await state.set_state(SavingsFlow.add_amount)
    await callback.message.answer(ADD_PROMPT, reply_markup=_force_reply(ADD_PROMPT))


async def process_add_amount(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Принимает сумму пополнения после ForceReply."""
    if message.from_user is None:
        await state.clear()
        return
    raw = message.text or ""
    await state.clear()
    await _apply_amount(message, session, raw)


def build_router() -> Router:
    """Создаёт роутер команды /savings."""
    router = Router(name="savings")

    router.message.register(cmd_savings, Command("savings"))
    router.message.register(
        process_add_amount, SavingsFlow.add_amount, ~F.text.startswith("/")
    )
    router.callback_query.register(on_add_pressed, F.data == CALLBACK_ADD)
    return router