"""Команда /debts: список, добавление и удаление долгов (Фаза 3)."""

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

from models.base import DebtType
from services import debts_repo
from utils.money import format_amount, parse_amount

NO_DEBTS_TEXT = "У тебя пока нет долгов. Добавь через /debts add"
DELETE_NOT_FOUND_TEXT = "Долг с таким номером не найден"
DELETE_DONE_TEXT = "Долг удалён"

NAME_PROMPT = "Название долга? Например: Кредит"
TYPE_PROMPT = "Тип долга?"
AMOUNT_PROMPT = "Сумма платежа? Например: 46000"
DAY_PROMPT = "День месяца? Например: 25"

TYPE_LABELS = {
    DebtType.LOAN.value: "Кредит",
    DebtType.MORTGAGE.value: "Ипотека",
    DebtType.CREDIT_CARD.value: "Кредитка",
    DebtType.INSTALLMENT.value: "Рассрочка",
}


class DebtFlow(StatesGroup):
    """Шаги добавления долга."""

    name = State()
    type = State()
    amount = State()
    payment_day = State()


def _force_reply(prompt: str) -> ForceReply:
    return ForceReply(input_field_placeholder=prompt, selective=True)


def _type_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=label, callback_data=f"debt_type:{value}"
        )
        for value, label in TYPE_LABELS.items()
    ]
    rows = [[buttons[0], buttons[1]], [buttons[2], buttons[3]]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_debts_list(debts: list) -> str:
    """Собирает текст списка долгов с итогом."""
    lines = ["Твои долги:", ""]
    total = 0
    for index, debt in enumerate(debts, start=1):
        total += debt.amount
        lines.append(
            f"{index}. {debt.name} — {format_amount(debt.amount)}, "
            f"{debt.payment_day} числа"
        )
    lines.append("")
    lines.append(f"Итого в месяц: {format_amount(total)}")
    return "\n".join(lines)


async def cmd_debts(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """Показывает список, добавляет или удаляет долг."""
    if message.from_user is None:
        return

    args = (command.args or "").split()
    if args and args[0] == "add":
        await state.set_state(DebtFlow.name)
        await message.answer(NAME_PROMPT, reply_markup=_force_reply(NAME_PROMPT))
        return

    if args and args[0] == "del":
        if len(args) < 2 or not args[1].isdigit():
            await message.answer("Укажи номер долга. Например: /debts del 2")
            return
        deleted = await debts_repo.delete_debt(
            session, message.from_user.id, int(args[1])
        )
        await message.answer(DELETE_DONE_TEXT if deleted else DELETE_NOT_FOUND_TEXT)
        return

    debts = await debts_repo.get_debts(session, message.from_user.id)
    if not debts:
        await message.answer(NO_DEBTS_TEXT)
        return
    await message.answer(format_debts_list(debts))


async def process_name(message: Message, state: FSMContext) -> None:
    """Шаг 1: название долга."""
    name = (message.text or "").strip()
    if not name:
        await message.answer("Напиши название. Например: Кредит")
        return
    await state.update_data(name=name)
    await state.set_state(DebtFlow.type)
    await message.answer(TYPE_PROMPT, reply_markup=_type_keyboard())


async def process_type(callback: CallbackQuery, state: FSMContext) -> None:
    """Шаг 2: тип долга (кнопки)."""
    if callback.data is None:
        return
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    debt_type = callback.data.split(":", 1)[1]
    await state.update_data(debt_type=debt_type)
    await state.set_state(DebtFlow.amount)
    await message.answer(AMOUNT_PROMPT, reply_markup=_force_reply(AMOUNT_PROMPT))


async def process_amount(message: Message, state: FSMContext) -> None:
    """Шаг 3: сумма платежа."""
    try:
        amount = parse_amount(message.text)
    except ValueError:
        await message.answer("Не понял сумму. Напиши число, например: 46000")
        return
    await state.update_data(amount=amount)
    await state.set_state(DebtFlow.payment_day)
    await message.answer(DAY_PROMPT, reply_markup=_force_reply(DAY_PROMPT))


async def process_payment_day(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Шаг 4: день месяца и сохранение долга."""
    if message.from_user is None:
        await state.clear()
        return

    cleaned = (message.text or "").strip()
    if not cleaned.isdigit() or not 1 <= int(cleaned) <= 31:
        await message.answer("Нужно число от 1 до 31. Попробуй ещё раз.")
        return

    data = await state.get_data()
    await state.clear()
    debt = await debts_repo.add_debt(
        session,
        message.from_user.id,
        data["name"],
        data["debt_type"],
        data["amount"],
        int(cleaned),
    )
    await message.answer(
        f"Долг добавлен: {debt.name} — {format_amount(debt.amount)}, "
        f"{debt.payment_day} числа"
    )


def build_router() -> Router:
    """Создаёт роутер команды /debts."""
    router = Router(name="debts")
    router.message.register(cmd_debts, Command("debts"))
    router.message.register(
        process_name, DebtFlow.name, ~F.text.startswith("/")
    )
    router.callback_query.register(process_type, F.data.startswith("debt_type:"))
    router.message.register(
        process_amount, DebtFlow.amount, ~F.text.startswith("/")
    )
    router.message.register(
        process_payment_day, DebtFlow.payment_day, ~F.text.startswith("/")
    )
    return router
