"""Команда /reminders — настройка уведомлений (Фаза 8)."""

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

from services import reminders_repo, users_repo
from services.reminders_repo import ReminderSettings

NEED_ONBOARDING = "Сначала пройди онбординг: /start"

HEADER = "⚙️ *Настройки уведомлений*"
EVENING_PROMPT = "Напиши время вечернего напоминания в формате 21:00."
PAYMENT_TIME_PROMPT = "Напиши время напоминания о платеже в формате 10:00."
PAYMENT_DAYS_PROMPT = (
    "За сколько дней напоминать о платеже? Напиши число, например 1."
)
ALL_ON_TEXT = "Включил напоминания. Изменить можно в /reminders."

OFFER_TEXT = (
    "Хочешь, чтобы я напоминал тебе о важном?\n\n"
    "📝 Вечернее «Запиши траты»\n"
    "💳 Напоминание о платеже за день"
)

CALLBACK_ON = "reminders:on"
CALLBACK_SETTINGS = "reminders:settings"
CALLBACK_TOGGLE_EVENING = "reminders:toggle_evening"
CALLBACK_TOGGLE_PAYMENT = "reminders:toggle_payment"
CALLBACK_EDIT_EVENING = "reminders:edit_evening"
CALLBACK_EDIT_PAYMENT_TIME = "reminders:edit_payment_time"
CALLBACK_EDIT_PAYMENT_DAYS = "reminders:edit_payment_days"


class Reminders(StatesGroup):
    """Шаги редактирования настроек напоминаний."""

    evening_time = State()
    payment_time = State()
    payment_days = State()


def _days_phrase(days: int) -> str:
    """«за 1 день» / «за 3 дн.»."""
    return "за 1 день" if days == 1 else f"за {days} дн."


def _settings_text(settings: ReminderSettings) -> str:
    """Текст экрана настроек."""
    evening = f"📝 Вечернее: {settings.evening_time}"
    if not settings.evening_enabled:
        evening += " (выключено)"
    payment = (
        f"💳 Платежи: {_days_phrase(settings.payment_days_before)}, "
        f"{settings.payment_time}"
    )
    if not settings.payment_enabled:
        payment += " (выключено)"
    return f"{HEADER}\n\n{evening}\n{payment}"


def _settings_keyboard(settings: ReminderSettings) -> InlineKeyboardMarkup:
    """Кнопки: изменить время/дни и включить-выключить."""
    evening_toggle = "🔕 Выключить" if settings.evening_enabled else "🔔 Включить"
    payment_toggle = "🔕 Выключить" if settings.payment_enabled else "🔔 Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Изменить", callback_data=CALLBACK_EDIT_EVENING
                ),
                InlineKeyboardButton(
                    text=evening_toggle, callback_data=CALLBACK_TOGGLE_EVENING
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Время", callback_data=CALLBACK_EDIT_PAYMENT_TIME
                ),
                InlineKeyboardButton(
                    text="📆 Дни", callback_data=CALLBACK_EDIT_PAYMENT_DAYS
                ),
                InlineKeyboardButton(
                    text=payment_toggle, callback_data=CALLBACK_TOGGLE_PAYMENT
                ),
            ],
        ]
    )


def build_offer_keyboard() -> InlineKeyboardMarkup:
    """Кнопки предложения напоминаний в онбординге."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Включить всё", callback_data=CALLBACK_ON),
                InlineKeyboardButton(
                    text="⚙️ Настроить", callback_data=CALLBACK_SETTINGS
                ),
            ]
        ]
    )


async def _send_settings(
    target: Message, session: AsyncSession, telegram_id: int
) -> None:
    """Отправляет экран настроек отдельным сообщением."""
    settings = await reminders_repo.get_reminder_settings(session, telegram_id)
    await target.answer(
        _settings_text(settings),
        parse_mode="Markdown",
        reply_markup=_settings_keyboard(settings),
    )


async def cmd_reminders(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """Показывает текущие настройки напоминаний."""
    if message.from_user is None:
        return
    user = await users_repo.get_by_telegram_id(session, message.from_user.id)
    if user is None or not user.onboarding_completed:
        await message.answer(NEED_ONBOARDING)
        return
    await state.clear()
    await _send_settings(message, session, message.from_user.id)


async def on_enable_all(callback: CallbackQuery, session: AsyncSession) -> None:
    """[✅ Включить всё]: оставляет значения по умолчанию включёнными."""
    await callback.answer()
    if callback.from_user is None:
        return
    await reminders_repo.update_reminder_settings(
        session,
        callback.from_user.id,
        reminder_evening_enabled=True,
        reminder_payment_enabled=True,
    )
    if isinstance(callback.message, Message):
        await callback.message.answer(ALL_ON_TEXT)


async def on_settings(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    """[⚙️ Настроить]: открывает экран настроек."""
    await callback.answer()
    if callback.from_user is None or not isinstance(callback.message, Message):
        return
    await state.clear()
    await _send_settings(callback.message, session, callback.from_user.id)


async def _rerender(callback: CallbackQuery, session: AsyncSession) -> None:
    """Перерисовывает экран настроек после изменения."""
    if callback.from_user is None or not isinstance(callback.message, Message):
        return
    settings = await reminders_repo.get_reminder_settings(
        session, callback.from_user.id
    )
    try:
        await callback.message.edit_text(
            _settings_text(settings),
            parse_mode="Markdown",
            reply_markup=_settings_keyboard(settings),
        )
    except TelegramBadRequest:
        pass


async def on_toggle_evening(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[🔕/🔔] для вечернего напоминания."""
    await callback.answer()
    if callback.from_user is None:
        return
    settings = await reminders_repo.get_reminder_settings(
        session, callback.from_user.id
    )
    await reminders_repo.update_reminder_settings(
        session,
        callback.from_user.id,
        reminder_evening_enabled=not settings.evening_enabled,
    )
    await _rerender(callback, session)


async def on_toggle_payment(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[🔕/🔔] для платёжного напоминания."""
    await callback.answer()
    if callback.from_user is None:
        return
    settings = await reminders_repo.get_reminder_settings(
        session, callback.from_user.id
    )
    await reminders_repo.update_reminder_settings(
        session,
        callback.from_user.id,
        reminder_payment_enabled=not settings.payment_enabled,
    )
    await _rerender(callback, session)


async def on_edit_evening(callback: CallbackQuery, state: FSMContext) -> None:
    """[✏️ Изменить]: спрашивает новое время вечернего напоминания."""
    await callback.answer()
    await state.set_state(Reminders.evening_time)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            EVENING_PROMPT,
            reply_markup=ForceReply(input_field_placeholder="21:00", selective=True),
        )


async def on_edit_payment_time(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """[✏️ Время]: спрашивает новое время платёжного напоминания."""
    await callback.answer()
    await state.set_state(Reminders.payment_time)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            PAYMENT_TIME_PROMPT,
            reply_markup=ForceReply(input_field_placeholder="10:00", selective=True),
        )


async def on_edit_payment_days(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """[📆 Дни]: спрашивает, за сколько дней напоминать."""
    await callback.answer()
    await state.set_state(Reminders.payment_days)
    if isinstance(callback.message, Message):
        await callback.message.answer(PAYMENT_DAYS_PROMPT)


async def _save_and_show(
    message: Message, session: AsyncSession, state: FSMContext, **fields: object
) -> None:
    """Сохраняет настройки, сбрасывает состояние и показывает экран."""
    if message.from_user is None:
        await state.clear()
        return
    await reminders_repo.update_reminder_settings(
        session, message.from_user.id, **fields
    )
    await state.clear()
    await _send_settings(message, session, message.from_user.id)


async def process_evening_time(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """Сохраняет новое время вечернего напоминания (HH:MM)."""
    try:
        value = reminders_repo.normalize_time(message.text)
    except ValueError as exc:
        await message.answer(f"{exc}\nПопробуй ещё раз.")
        return
    await _save_and_show(
        message, session, state, reminder_evening_time=value
    )


async def process_payment_time(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """Сохраняет новое время платёжного напоминания (HH:MM)."""
    try:
        value = reminders_repo.normalize_time(message.text)
    except ValueError as exc:
        await message.answer(f"{exc}\nПопробуй ещё раз.")
        return
    await _save_and_show(
        message, session, state, reminder_payment_time=value
    )


async def process_payment_days(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """Сохраняет число дней до платежа (0–30)."""
    try:
        value = reminders_repo.normalize_days(message.text)
    except ValueError as exc:
        await message.answer(f"{exc}\nПопробуй ещё раз.")
        return
    await _save_and_show(
        message, session, state, reminder_payment_days_before=value
    )


def build_router() -> Router:
    """Создаёт роутер настроек напоминаний."""
    router = Router(name="reminders")
    router.message.register(cmd_reminders, Command("reminders"))
    router.callback_query.register(on_enable_all, F.data == CALLBACK_ON)
    router.callback_query.register(on_settings, F.data == CALLBACK_SETTINGS)
    router.callback_query.register(
        on_toggle_evening, F.data == CALLBACK_TOGGLE_EVENING
    )
    router.callback_query.register(
        on_toggle_payment, F.data == CALLBACK_TOGGLE_PAYMENT
    )
    router.callback_query.register(
        on_edit_evening, F.data == CALLBACK_EDIT_EVENING
    )
    router.callback_query.register(
        on_edit_payment_time, F.data == CALLBACK_EDIT_PAYMENT_TIME
    )
    router.callback_query.register(
        on_edit_payment_days, F.data == CALLBACK_EDIT_PAYMENT_DAYS
    )
    router.message.register(process_evening_time, Reminders.evening_time)
    router.message.register(process_payment_time, Reminders.payment_time)
    router.message.register(process_payment_days, Reminders.payment_days)
    return router
