"""Команда /debts: список долгов и кнопки управления (Фаза 3)."""

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

from models import Debt
from models.base import DebtType
from services import debts_repo
from utils.money import format_amount, parse_amount

NO_DEBTS_TEXT = "У тебя пока нет долгов"
DELETE_NOT_FOUND_TEXT = "Долг с таким номером не найден"
DELETE_DONE_PREFIX = "Долг удалён: "
DELETE_LIST_TITLE = "Выбери долг для удаления:"
CANCEL_TEXT = "Отменено"

ADD_BUTTON_TEXT = "➕ Добавить долг"
DELETE_BUTTON_TEXT = "🗑 Удалить долг"
CANCEL_BUTTON_TEXT = "❌ Отмена"

CALLBACK_ADD = "debts:add"
CALLBACK_DELETE_LIST = "debts:del"
CALLBACK_DELETE_CANCEL = "debt_del:cancel"

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
        InlineKeyboardButton(text=label, callback_data=f"debt_type:{value}")
        for value, label in TYPE_LABELS.items()
    ]
    rows = [[buttons[0], buttons[1]], [buttons[2], buttons[3]]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _manage_keyboard(has_debts: bool) -> InlineKeyboardMarkup:
    """Кнопки управления списком долгов."""
    buttons = [
        InlineKeyboardButton(text=ADD_BUTTON_TEXT, callback_data=CALLBACK_ADD)
    ]
    if has_debts:
        buttons.append(
            InlineKeyboardButton(
                text=DELETE_BUTTON_TEXT, callback_data=CALLBACK_DELETE_LIST
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def _delete_button_label(index: int, debt: Debt) -> str:
    """Текст кнопки долга в списке удаления (лимит кнопки — 64 символа)."""
    label = (
        f"{index}. {debt.name} — {format_amount(debt.amount)}, "
        f"{debt.payment_day} числа"
    )
    return label if len(label) <= 64 else label[:61] + "…"


def _delete_list_keyboard(debts: list[Debt]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=_delete_button_label(index, debt),
                callback_data=f"debt_del:{debt.id}",
            )
        ]
        for index, debt in enumerate(debts, start=1)
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=CANCEL_BUTTON_TEXT, callback_data=CALLBACK_DELETE_CANCEL
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_debts_list(debts: list[Debt]) -> str:
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


async def cmd_debts(message: Message, session: AsyncSession) -> None:
    """Показывает список долгов с кнопками управления."""
    if message.from_user is None:
        return

    debts = await debts_repo.get_debts(session, message.from_user.id)
    if not debts:
        await message.answer(
            NO_DEBTS_TEXT, reply_markup=_manage_keyboard(has_debts=False)
        )
        return
    await message.answer(
        format_debts_list(debts),
        reply_markup=_manage_keyboard(has_debts=True),
    )


async def on_add_pressed(callback: CallbackQuery, state: FSMContext) -> None:
    """[➕ Добавить долг]: запускает пошаговое добавление."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await state.set_state(DebtFlow.name)
    await callback.message.answer(
        NAME_PROMPT, reply_markup=_force_reply(NAME_PROMPT)
    )


async def on_delete_list_pressed(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[🗑 Удалить долг]: показывает список долгов с кнопками."""
    await callback.answer()
    if callback.from_user is None or not isinstance(callback.message, Message):
        return
    debts = await debts_repo.get_debts(session, callback.from_user.id)
    if not debts:
        await callback.message.answer(NO_DEBTS_TEXT)
        return
    await callback.message.answer(
        DELETE_LIST_TITLE, reply_markup=_delete_list_keyboard(debts)
    )


async def on_delete_debt_pressed(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[N. Название]: удаляет выбранный долг."""
    await callback.answer()
    if (
        callback.data is None
        or callback.from_user is None
        or not isinstance(callback.message, Message)
    ):
        return
    debt_id = int(callback.data.split(":", 1)[1])
    debt = await debts_repo.get_debt(session, callback.from_user.id, debt_id)
    if debt is None:
        await callback.message.answer(DELETE_NOT_FOUND_TEXT)
        return
    await debts_repo.delete_debt(session, callback.from_user.id, debt_id)
    await callback.message.answer(f"{DELETE_DONE_PREFIX}{debt.name}")


async def on_delete_cancel_pressed(callback: CallbackQuery) -> None:
    """[❌ Отмена]: отменяет удаление."""
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(CANCEL_TEXT)


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
    router.message.register(
        process_amount, DebtFlow.amount, ~F.text.startswith("/")
    )
    router.message.register(
        process_payment_day, DebtFlow.payment_day, ~F.text.startswith("/")
    )

    router.callback_query.register(process_type, F.data.startswith("debt_type:"))
    router.callback_query.register(on_add_pressed, F.data == CALLBACK_ADD)
    router.callback_query.register(
        on_delete_list_pressed, F.data == CALLBACK_DELETE_LIST
    )
    router.callback_query.register(
        on_delete_debt_pressed, F.data.regexp(r"^debt_del:\d+$")
    )
    router.callback_query.register(
        on_delete_cancel_pressed, F.data == CALLBACK_DELETE_CANCEL
    )
    return router