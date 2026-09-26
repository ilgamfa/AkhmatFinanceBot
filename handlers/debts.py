"""Команда /debts: долги, платежи и отметка «выплачено» (Фаза 7)."""

from __future__ import annotations

from datetime import UTC, date, datetime

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

from models import Debt, DebtPayment
from models.base import DebtType, PaymentStatus
from services import debts_repo
from utils.money import format_amount, parse_amount

NO_DEBTS_TEXT = "У тебя пока нет долгов"
NOT_FOUND_TEXT = "Долг с таким номером не найден"
PAYMENT_NOT_FOUND_TEXT = "Платёж с таким номером не найден"
DELETE_LIST_TITLE = "Выбери долг для удаления:"
EDIT_LIST_TITLE = "Выбери долг для редактирования:"
CANCEL_TEXT = "Отменено"

ADD_BUTTON_TEXT = "➕ Добавить"
DELETE_BUTTON_TEXT = "🗑 Удалить"
EDIT_BUTTON_TEXT = "✏️ Редактировать"
CANCEL_BUTTON_TEXT = "❌ Отмена"
NAME_BUTTON_TEXT = "✏️ Название"
SCHEDULE_BUTTON_TEXT = "📅 Число месяца"

CALLBACK_ADD = "debts:add"
CALLBACK_EDIT_LIST = "debts:edit"
CALLBACK_DELETE_LIST = "debts:del"
CALLBACK_CANCEL = "debt_cancel"

ADD_TYPES_TEXT = (
    "Какой тип долга?\n\n"
    "📅 Регулярный\n"
    "Платёж каждый месяц в один день.\n"
    "Например: кредит, ипотека.\n\n"
    "📋 Краткосрочный\n"
    "Несколько платежей с разными датами.\n"
    "Например: кредитка, рассрочка.\n\n"
    "1️⃣ Разовый\n"
    "Один платёж в конкретную дату.\n"
    "Например: занял у друга."
)
ADDED_TEXT = "Долг добавлен. Удалить можно в /debts."
NAME_PROMPT = "Название долга? Например: Кредит"
AMOUNT_PROMPT = "Сумма платежа? Например: 46000"
DAY_PROMPT = "Число месяца? Например: 25"
COUNT_PROMPT = "Сколько платежей? Введи число"
ONE_DATE_PROMPT = "Дата платежа? Например: 25.09.2026"
EDIT_NAME_PROMPT = "Новое название долга? Например: Кредит"
EDIT_DAY_PROMPT = "Новое число месяца? Например: 25"
EDIT_AMOUNT_PROMPT = "Новая сумма платежа? Например: 50000"
EDIT_DATE_PROMPT = "Новая дата платежа? Например: 25.10.2026"

REGULAR_MONTHS = 12
MAX_SHORT_PAYMENTS = 120

DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%d.%m", "%Y-%m-%d")


class DebtAddFlow(StatesGroup):
    """Шаги добавления долга."""

    name = State()
    amount = State()
    day = State()
    count = State()
    list_date = State()
    list_amount = State()
    one_date = State()


class DebtEditFlow(StatesGroup):
    """Шаги редактирования долга и его платежей."""

    name = State()
    schedule_day = State()
    schedule_amount = State()
    payment_menu = State()
    payment_amount = State()
    payment_date = State()


def _force_reply(prompt: str) -> ForceReply:
    return ForceReply(input_field_placeholder=prompt, selective=True)


def parse_date(text: str | None, today: date | None = None) -> date | None:
    """Разбирает дату в форматах ``дд.мм[.гггг]`` или ``гггг-мм-дд``."""
    if not text:
        return None
    cleaned = text.strip()
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
        if "%Y" not in fmt and "%y" not in fmt:
            parsed = parsed.replace(year=(today or datetime.now(UTC).date()).year)
        return parsed
    return None


def _fmt_date(iso: str) -> str:
    """ISO-дату в ``дд.мм``."""
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m")
    except ValueError:
        return iso


def _fmt_full_date(iso: str) -> str:
    """ISO-дату в ``дд.мм.гггг``."""
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y")
    except ValueError:
        return iso


async def _get_owned_payment(
    session: AsyncSession, telegram_id: int, payment_id: int
) -> DebtPayment | None:
    """Платёж пользователя по id или None (чужой платёж не отдаём)."""
    payment = await debts_repo.get_payment(session, payment_id)
    if payment is None:
        return None
    debt = await session.get(Debt, payment.debt_id)
    if debt is None or debt.telegram_id != telegram_id:
        return None
    return payment


def _method_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📅 Регулярный", callback_data="debt_method:regular"
                ),
                InlineKeyboardButton(
                    text="📋 Краткосрочный", callback_data="debt_method:short"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="1️⃣ Разовый", callback_data="debt_method:one"
                )
            ],
        ]
    )


def _manage_keyboard(has_debts: bool) -> InlineKeyboardMarkup:
    """Кнопки управления списком долгов."""
    rows = [[InlineKeyboardButton(text=ADD_BUTTON_TEXT, callback_data=CALLBACK_ADD)]]
    if has_debts:
        rows.append(
            [
                InlineKeyboardButton(
                    text=EDIT_BUTTON_TEXT, callback_data=CALLBACK_EDIT_LIST
                ),
                InlineKeyboardButton(
                    text=DELETE_BUTTON_TEXT, callback_data=CALLBACK_DELETE_LIST
                ),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _debt_button_label(index: int, debt: Debt) -> str:
    return f"{index}. {debt.name}"[:64]


def _debt_list_keyboard(
    debts: list[Debt], callback_prefix: str
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=_debt_button_label(index, debt),
                callback_data=f"{callback_prefix}:{debt.id}",
            )
        ]
        for index, debt in enumerate(debts, start=1)
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=CANCEL_BUTTON_TEXT, callback_data=CALLBACK_CANCEL
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _payment_button_label(index: int, payment: DebtPayment) -> str:
    mark = "✅" if payment.status == PaymentStatus.PAID.value else "⏳"
    label = (
        f"{index}. #{payment.id} — {format_amount(payment.amount)}, "
        f"{_fmt_date(payment.due_date)} {mark}"
    )
    return label if len(label) <= 64 else label[:61] + "…"


def _debt_detail_keyboard(
    debt: Debt, payments: list[DebtPayment]
) -> InlineKeyboardMarkup:
    """Карточка долга: правка названия и (для регулярного) графика."""
    rows = [
        [
            InlineKeyboardButton(
                text=NAME_BUTTON_TEXT, callback_data=f"debt_ename:{debt.id}"
            )
        ]
    ]
    if debt.type == DebtType.REGULAR.value:
        rows.append(
            [
                InlineKeyboardButton(
                    text=SCHEDULE_BUTTON_TEXT,
                    callback_data=f"debt_eschedule:{debt.id}",
                )
            ]
        )
    else:
        rows.extend(
            [
                InlineKeyboardButton(
                    text=_payment_button_label(index, payment),
                    callback_data=f"debt_pedit:{payment.id}",
                )
            ]
            for index, payment in enumerate(payments, start=1)
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=CANCEL_BUTTON_TEXT, callback_data=CALLBACK_CANCEL
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _payment_fields_keyboard() -> InlineKeyboardMarkup:
    """Меню платежа: сумма и дата (без удаления)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сумма", callback_data="debt_pfield:amount"),
                InlineKeyboardButton(text="Дата", callback_data="debt_pfield:date"),
            ],
            [
                InlineKeyboardButton(
                    text=CANCEL_BUTTON_TEXT, callback_data=CALLBACK_CANCEL
                )
            ],
        ]
    )


def _debt_line(index: int, debt: Debt, payments: list[DebtPayment]) -> str:
    """Строка списка долгов в зависимости от типа."""
    pending = [
        payment
        for payment in payments
        if payment.status == PaymentStatus.PENDING.value
    ]
    if not payments:
        return f"{index}. {debt.name} — нет платежей"
    if debt.type == DebtType.ONE.value:
        payment = payments[0]
        return (
            f"{index}. {debt.name} — {format_amount(payment.amount)}, "
            f"{_fmt_full_date(payment.due_date)}"
        )
    nearest = pending[0] if pending else payments[0]
    if debt.type == DebtType.REGULAR.value:
        day = date.fromisoformat(nearest.due_date).day
        return f"{index}. {debt.name} — {format_amount(nearest.amount)}/мес, {day} числа"
    count = len(pending) if pending else len(payments)
    if not pending:
        return f"{index}. {debt.name} — {count} платежа"
    return (
        f"{index}. {debt.name} — {count} платежа, "
        f"следующий {_fmt_date(nearest.due_date)}"
    )


async def _debt_summary_lines(
    session: AsyncSession, debts: list[Debt]
) -> list[str]:
    """Строки списка долгов (без итоговой строки)."""
    lines: list[str] = []
    for index, debt in enumerate(debts, start=1):
        payments = await debts_repo.get_payments(session, debt.id)
        lines.append(_debt_line(index, debt, payments))
    return lines


async def _show_debt_detail(
    message: Message, session: AsyncSession, debt: Debt
) -> None:
    """Показывает долг и его платежи с кнопками редактирования."""
    payments = await debts_repo.get_payments(session, debt.id)
    lines = [f"*{debt.name}*", ""]
    if payments:
        for index, payment in enumerate(payments, start=1):
            mark = "✅" if payment.status == PaymentStatus.PAID.value else "⏳"
            lines.append(
                f"{index}. #{payment.id} — {format_amount(payment.amount)}, "
                f"{_fmt_date(payment.due_date)} {mark}"
            )
    else:
        lines.append("Платежей пока нет.")
    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=_debt_detail_keyboard(debt, payments),
    )


async def cmd_debts(message: Message, session: AsyncSession) -> None:
    """Показывает список долгов."""
    if message.from_user is None:
        return

    debts = await debts_repo.get_debts(session, message.from_user.id)
    if not debts:
        await message.answer(
            NO_DEBTS_TEXT, reply_markup=_manage_keyboard(has_debts=False)
        )
        return
    lines = ["Твои долги:", ""]
    lines.extend(await _debt_summary_lines(session, debts))
    await message.answer(
        "\n".join(lines), reply_markup=_manage_keyboard(has_debts=True)
    )


# --- добавление --------------------------------------------------------------


async def on_add_pressed(callback: CallbackQuery, state: FSMContext) -> None:
    """[➕ Добавить]: показывает описания типов и кнопки выбора."""
    await callback.answer()
    await state.clear()
    if not isinstance(callback.message, Message):
        return
    await callback.message.answer(ADD_TYPES_TEXT, reply_markup=_method_keyboard())


async def on_method_pressed(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор типа долга: спрашивает название."""
    await callback.answer()
    if callback.data is None or not isinstance(callback.message, Message):
        return
    method = callback.data.split(":", 1)[1]
    await state.update_data(method=method)
    await state.set_state(DebtAddFlow.name)
    await callback.message.answer(NAME_PROMPT, reply_markup=_force_reply(NAME_PROMPT))


async def process_name(message: Message, state: FSMContext) -> None:
    """Шаг 1: название долга."""
    name = (message.text or "").strip()
    if not name:
        await message.answer("Напиши название. Например: Кредит")
        return
    data = await state.get_data()
    await state.update_data(name=name)
    if data.get("method") == DebtType.SHORT.value:
        await state.set_state(DebtAddFlow.count)
        await message.answer(COUNT_PROMPT, reply_markup=_force_reply(COUNT_PROMPT))
        return
    await state.set_state(DebtAddFlow.amount)
    await message.answer(AMOUNT_PROMPT, reply_markup=_force_reply(AMOUNT_PROMPT))


async def process_amount(message: Message, state: FSMContext) -> None:
    """Шаг 2: сумма (регулярный или разовый)."""
    try:
        amount = parse_amount(message.text)
    except ValueError:
        await message.answer("Не понял сумму. Напиши число, например: 46000")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше нуля. Попробуй ещё раз.")
        return

    data = await state.get_data()
    await state.update_data(amount=amount)
    if data.get("method") == DebtType.ONE.value:
        await state.set_state(DebtAddFlow.one_date)
        await message.answer(
            ONE_DATE_PROMPT, reply_markup=_force_reply(ONE_DATE_PROMPT)
        )
        return
    await state.set_state(DebtAddFlow.day)
    await message.answer(DAY_PROMPT, reply_markup=_force_reply(DAY_PROMPT))


async def process_day(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Шаг 3 (регулярный): число месяца и генерация 12 платежей."""
    if message.from_user is None:
        await state.clear()
        return
    cleaned = (message.text or "").strip()
    if not cleaned.isdigit() or not 1 <= int(cleaned) <= 31:
        await message.answer("Нужно число от 1 до 31. Попробуй ещё раз.")
        return

    data = await state.get_data()
    await state.clear()
    debt = await debts_repo.create_debt(
        session,
        message.from_user.id,
        data["name"],
        DebtType.REGULAR.value,
    )
    first = debts_repo.next_payment_date(int(cleaned), datetime.now(UTC).date())
    for due_date in debts_repo.monthly_dates(first, REGULAR_MONTHS):
        await debts_repo.add_payment(session, debt.id, data["amount"], due_date)
    await message.answer(ADDED_TEXT)


async def process_count(message: Message, state: FSMContext) -> None:
    """Шаг 2 (краткосрочный): количество платежей."""
    cleaned = (message.text or "").strip()
    if not cleaned.isdigit() or not 1 <= int(cleaned) <= MAX_SHORT_PAYMENTS:
        await message.answer(
            f"Нужно число от 1 до {MAX_SHORT_PAYMENTS}. Попробуй ещё раз."
        )
        return
    count = int(cleaned)
    await state.update_data(count=count, index=0, payments=[])
    await state.set_state(DebtAddFlow.list_date)
    await message.answer(
        f"Дата платежа 1 из {count}? Например: 25.09.2026",
        reply_markup=_force_reply("Дата платежа"),
    )


async def process_list_date(message: Message, state: FSMContext) -> None:
    """Шаг 3 (краткосрочный): дата очередного платежа."""
    parsed = parse_date(message.text)
    if parsed is None:
        await message.answer("Не понял дату. Напиши, например: 25.09.2026")
        return
    await state.update_data(pending_date=parsed.isoformat())
    await state.set_state(DebtAddFlow.list_amount)
    await message.answer(
        "Сумма платежа? Например: 46000",
        reply_markup=_force_reply("Сумма платежа"),
    )


async def process_list_amount(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Шаг 4 (краткосрочный): сумма платежа и переход к следующему."""
    if message.from_user is None:
        await state.clear()
        return
    try:
        amount = parse_amount(message.text)
    except ValueError:
        await message.answer("Не понял сумму. Напиши число, например: 46000")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше нуля. Попробуй ещё раз.")
        return

    data = await state.get_data()
    payments = list(data.get("payments", []))
    payments.append([data["pending_date"], amount])
    index = int(data.get("index", 0)) + 1
    count = int(data["count"])
    if index < count:
        await state.update_data(payments=payments, index=index)
        await state.set_state(DebtAddFlow.list_date)
        await message.answer(
            f"Дата платежа {index + 1} из {count}? Например: 25.10.2026",
            reply_markup=_force_reply("Дата платежа"),
        )
        return

    await state.clear()
    debt = await debts_repo.create_debt(
        session,
        message.from_user.id,
        data["name"],
        DebtType.SHORT.value,
    )
    for due_date, payment_amount in payments:
        await debts_repo.add_payment(
            session, debt.id, payment_amount, date.fromisoformat(due_date)
        )
    await message.answer(ADDED_TEXT)


async def process_one_date(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Шаг 3 (разовый): дата и сохранение."""
    if message.from_user is None:
        await state.clear()
        return
    parsed = parse_date(message.text)
    if parsed is None:
        await message.answer("Не понял дату. Напиши, например: 25.09.2026")
        return

    data = await state.get_data()
    await state.clear()
    debt = await debts_repo.create_debt(
        session,
        message.from_user.id,
        data["name"],
        DebtType.ONE.value,
    )
    await debts_repo.add_payment(session, debt.id, data["amount"], parsed)
    await message.answer(ADDED_TEXT)


# --- удаление ----------------------------------------------------------------


async def on_delete_list_pressed(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[🗑 Удалить]: показывает список долгов."""
    await callback.answer()
    if callback.from_user is None or not isinstance(callback.message, Message):
        return
    debts = await debts_repo.get_debts(session, callback.from_user.id)
    if not debts:
        await callback.message.answer(NO_DEBTS_TEXT)
        return
    await callback.message.answer(
        DELETE_LIST_TITLE, reply_markup=_debt_list_keyboard(debts, "debt_del")
    )


async def on_delete_debt_pressed(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Удаляет выбранный долг вместе с платежами."""
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
        await callback.message.answer(NOT_FOUND_TEXT)
        return
    await debts_repo.delete_debt(session, debt_id)
    await callback.message.answer(f"Долг удалён: {debt.name}")


# --- редактирование ----------------------------------------------------------


async def on_edit_list_pressed(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[✏️ Редактировать]: показывает список долгов."""
    await callback.answer()
    if callback.from_user is None or not isinstance(callback.message, Message):
        return
    debts = await debts_repo.get_debts(session, callback.from_user.id)
    if not debts:
        await callback.message.answer(NO_DEBTS_TEXT)
        return
    await callback.message.answer(
        EDIT_LIST_TITLE, reply_markup=_debt_list_keyboard(debts, "debt_edit")
    )


async def on_edit_debt_pressed(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Показывает долг и его платежи."""
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
        await callback.message.answer(NOT_FOUND_TEXT)
        return
    await _show_debt_detail(callback.message, session, debt)


async def on_edit_name_pressed(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """[✏️ Название]: запрашивает новое имя долга."""
    await callback.answer()
    if (
        callback.data is None
        or callback.from_user is None
        or not isinstance(callback.message, Message)
    ):
        return
    debt_id = int(callback.data.split(":", 1)[1])
    if await debts_repo.get_debt(session, callback.from_user.id, debt_id) is None:
        await callback.message.answer(NOT_FOUND_TEXT)
        return
    await state.set_state(DebtEditFlow.name)
    await state.update_data(debt_id=debt_id)
    await callback.message.answer(
        EDIT_NAME_PROMPT, reply_markup=_force_reply(EDIT_NAME_PROMPT)
    )


async def process_edit_name(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Новое имя долга."""
    name = (message.text or "").strip()
    if not name:
        await message.answer("Напиши название. Например: Кредит")
        return
    data = await state.get_data()
    debt_id = data.get("debt_id")
    await state.clear()
    if debt_id is None or message.from_user is None:
        await message.answer(NOT_FOUND_TEXT)
        return
    if await debts_repo.get_debt(session, message.from_user.id, int(debt_id)) is None:
        await message.answer(NOT_FOUND_TEXT)
        return
    debt = await debts_repo.rename_debt(session, int(debt_id), name)
    if debt is None:
        await message.answer(NOT_FOUND_TEXT)
        return
    await message.answer(f"Долг переименован: {debt.name}")


async def on_edit_schedule_pressed(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """[📅 Число месяца]: запрашивает новое число месяца для регулярного долга."""
    await callback.answer()
    if (
        callback.data is None
        or callback.from_user is None
        or not isinstance(callback.message, Message)
    ):
        return
    debt_id = int(callback.data.split(":", 1)[1])
    debt = await debts_repo.get_debt(session, callback.from_user.id, debt_id)
    if debt is None or debt.type != DebtType.REGULAR.value:
        await callback.message.answer(NOT_FOUND_TEXT)
        return
    await state.set_state(DebtEditFlow.schedule_day)
    await state.update_data(debt_id=debt_id)
    await callback.message.answer(
        EDIT_DAY_PROMPT, reply_markup=_force_reply(EDIT_DAY_PROMPT)
    )


async def process_schedule_day(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Новое число месяца регулярного долга."""
    if message.from_user is None:
        await state.clear()
        return
    cleaned = (message.text or "").strip()
    if not cleaned.isdigit() or not 1 <= int(cleaned) <= 31:
        await message.answer("Нужно число от 1 до 31. Попробуй ещё раз.")
        return
    await state.update_data(day=int(cleaned))
    await state.set_state(DebtEditFlow.schedule_amount)
    await message.answer(
        EDIT_AMOUNT_PROMPT, reply_markup=_force_reply(EDIT_AMOUNT_PROMPT)
    )


async def process_schedule_amount(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Новая сумма регулярного долга: платежи пересобираются."""
    if message.from_user is None:
        await state.clear()
        return
    try:
        amount = parse_amount(message.text)
    except ValueError:
        await message.answer("Не понял сумму. Напиши число, например: 46000")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше нуля. Попробуй ещё раз.")
        return
    data = await state.get_data()
    debt_id = data.get("debt_id")
    day = data.get("day")
    await state.clear()
    if debt_id is None or day is None:
        await message.answer(NOT_FOUND_TEXT)
        return
    debt = await debts_repo.get_debt(session, message.from_user.id, int(debt_id))
    if debt is None:
        await message.answer(NOT_FOUND_TEXT)
        return
    await debts_repo.update_debt_schedule(session, int(debt_id), amount, int(day))
    await message.answer(
        f"Регулярный долг обновлён: {format_amount(amount)}/мес, {day} числа"
    )


async def on_payment_pressed(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Показывает меню платежа (сумма / дата / удалить)."""
    await callback.answer()
    if callback.data is None or not isinstance(callback.message, Message):
        return
    payment_id = int(callback.data.split(":", 1)[1])
    if callback.from_user is None:
        return
    payment = await _get_owned_payment(session, callback.from_user.id, payment_id)
    if payment is None:
        await callback.message.answer(PAYMENT_NOT_FOUND_TEXT)
        return
    await state.set_state(DebtEditFlow.payment_menu)
    await state.update_data(payment_id=payment_id, debt_id=payment.debt_id)
    await callback.message.answer(
        f"Платёж #{payment.id} — {format_amount(payment.amount)}, "
        f"{_fmt_date(payment.due_date)}. Что изменить?",
        reply_markup=_payment_fields_keyboard(),
    )


async def on_payment_field_pressed(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """[Сумма/Дата] для выбранного платежа."""
    await callback.answer()
    if callback.data is None or not isinstance(callback.message, Message):
        return
    field = callback.data.split(":", 1)[1]
    data = await state.get_data()
    payment_id = data.get("payment_id")
    if payment_id is None:
        await state.clear()
        await callback.message.answer(CANCEL_TEXT)
        return

    if callback.from_user is None:
        await state.clear()
        return
    owned = await _get_owned_payment(
        session, callback.from_user.id, int(payment_id)
    )
    if owned is None:
        await state.clear()
        await callback.message.answer(PAYMENT_NOT_FOUND_TEXT)
        return

    if field == "amount":
        await state.set_state(DebtEditFlow.payment_amount)
        prompt = EDIT_AMOUNT_PROMPT
    else:
        await state.set_state(DebtEditFlow.payment_date)
        prompt = EDIT_DATE_PROMPT
    await callback.message.answer(prompt, reply_markup=_force_reply(prompt))


async def process_payment_amount(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Новая сумма платежа."""
    try:
        amount = parse_amount(message.text)
    except ValueError:
        await message.answer("Не понял сумму. Напиши число, например: 46000")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше нуля. Попробуй ещё раз.")
        return
    data = await state.get_data()
    payment_id = data.get("payment_id")
    await state.clear()
    if payment_id is None or message.from_user is None:
        await message.answer(PAYMENT_NOT_FOUND_TEXT)
        return
    owned = await _get_owned_payment(session, message.from_user.id, int(payment_id))
    if owned is None:
        await message.answer(PAYMENT_NOT_FOUND_TEXT)
        return
    payment = await debts_repo.update_payment(session, int(payment_id), amount=amount)
    if payment is None:
        await message.answer(PAYMENT_NOT_FOUND_TEXT)
        return
    await message.answer(
        f"Платёж обновлён: {format_amount(payment.amount)}, "
        f"{_fmt_date(payment.due_date)}"
    )


async def process_payment_date(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Новая дата платежа."""
    parsed = parse_date(message.text)
    if parsed is None:
        await message.answer("Не понял дату. Напиши, например: 25.10.2026")
        return
    data = await state.get_data()
    payment_id = data.get("payment_id")
    await state.clear()
    if payment_id is None or message.from_user is None:
        await message.answer(PAYMENT_NOT_FOUND_TEXT)
        return
    owned = await _get_owned_payment(session, message.from_user.id, int(payment_id))
    if owned is None:
        await message.answer(PAYMENT_NOT_FOUND_TEXT)
        return
    payment = await debts_repo.update_payment(
        session, int(payment_id), due_date=parsed
    )
    if payment is None:
        await message.answer(PAYMENT_NOT_FOUND_TEXT)
        return
    await message.answer(
        f"Платёж обновлён: {format_amount(payment.amount)}, "
        f"{_fmt_date(payment.due_date)}"
    )


async def on_cancel_pressed(callback: CallbackQuery, state: FSMContext) -> None:
    """[❌ Отмена]: сбрасывает диалог."""
    await callback.answer()
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.answer(CANCEL_TEXT)


def build_router() -> Router:
    """Создаёт роутер команды /debts."""
    router = Router(name="debts")

    router.message.register(cmd_debts, Command("debts"))
    router.message.register(process_name, DebtAddFlow.name, ~F.text.startswith("/"))
    router.message.register(process_amount, DebtAddFlow.amount, ~F.text.startswith("/"))
    router.message.register(
        process_day, DebtAddFlow.day, ~F.text.startswith("/")
    )
    router.message.register(
        process_count, DebtAddFlow.count, ~F.text.startswith("/")
    )
    router.message.register(
        process_list_date, DebtAddFlow.list_date, ~F.text.startswith("/")
    )
    router.message.register(
        process_list_amount, DebtAddFlow.list_amount, ~F.text.startswith("/")
    )
    router.message.register(
        process_one_date, DebtAddFlow.one_date, ~F.text.startswith("/")
    )
    router.message.register(
        process_edit_name, DebtEditFlow.name, ~F.text.startswith("/")
    )
    router.message.register(
        process_schedule_day, DebtEditFlow.schedule_day, ~F.text.startswith("/")
    )
    router.message.register(
        process_schedule_amount, DebtEditFlow.schedule_amount, ~F.text.startswith("/")
    )
    router.message.register(
        process_payment_amount, DebtEditFlow.payment_amount, ~F.text.startswith("/")
    )
    router.message.register(
        process_payment_date, DebtEditFlow.payment_date, ~F.text.startswith("/")
    )

    router.callback_query.register(on_add_pressed, F.data == CALLBACK_ADD)
    router.callback_query.register(
        on_method_pressed, F.data.startswith("debt_method:")
    )
    router.callback_query.register(
        on_delete_list_pressed, F.data == CALLBACK_DELETE_LIST
    )
    router.callback_query.register(
        on_delete_debt_pressed, F.data.regexp(r"^debt_del:\d+$")
    )
    router.callback_query.register(
        on_edit_list_pressed, F.data == CALLBACK_EDIT_LIST
    )
    router.callback_query.register(
        on_edit_debt_pressed, F.data.regexp(r"^debt_edit:\d+$")
    )
    router.callback_query.register(
        on_edit_name_pressed, F.data.regexp(r"^debt_ename:\d+$")
    )
    router.callback_query.register(
        on_edit_schedule_pressed, F.data.regexp(r"^debt_eschedule:\d+$")
    )
    router.callback_query.register(
        on_payment_pressed, F.data.regexp(r"^debt_pedit:\d+$")
    )
    router.callback_query.register(
        on_payment_field_pressed, F.data.startswith("debt_pfield:")
    )
    router.callback_query.register(on_cancel_pressed, F.data == CALLBACK_CANCEL)
    return router
