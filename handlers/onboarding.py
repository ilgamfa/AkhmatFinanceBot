"""Онбординг Фазы 1: деньги сейчас и устройство дохода."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from models import IncomeType
from services import accounts_repo, users_repo
from services.calculations import dump_income_dates
from utils.money import parse_amount, parse_day_and_amount

INTRO_TEXT = (
    "Привет! Я твой карманный финсоветник.\n\n"
    "Чтобы я мог считать твои свободные деньги, мне нужно понять, "
    "откуда они приходят. Это займёт минуту.\n\n"
    "Я задам 3 вопроса:\n\n"
    "Сколько у тебя денег сейчас\n"
    "Как устроен твой доход\n"
    "Сумма и даты поступлений\n\n"
    "Поехали?"
)

MONEY_TEXT = "Сколько у тебя сейчас на картах и наличных? Напиши примерную сумму."
INCOME_KIND_TEXT = "Как у тебя устроен доход?"
TIMES_TEXT = "Сколько раз в месяц приходят деньги?"
FIXED_FIRST_TEXT = "Напиши первую дату и сумму. Например: 10, 30000"
FIXED_SECOND_TEXT = "Теперь вторую дату и сумму. Например: 25, 20000"
FIXED_ONE_TEXT = "Напиши дату и сумму. Например: 10, 50000"
IRREGULAR_TEXT = "Сколько в среднем выходит в месяц? Напиши примерную сумму."
FINISH_TEXT = "Готово! Теперь отправь /stats, чтобы увидеть сводку."


def _intro_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Начать", callback_data="onboarding:start"
                ),
                InlineKeyboardButton(
                    text="Позже", callback_data="onboarding:later"
                ),
            ]
        ]
    )


def _income_kind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Фиксированная",
                    callback_data="onboarding:income_fixed",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Нерегулярная",
                    callback_data="onboarding:income_irregular",
                )
            ],
        ]
    )


def _times_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="1 раз", callback_data="onboarding:times_1"
                ),
                InlineKeyboardButton(
                    text="2 раза", callback_data="onboarding:times_2"
                ),
            ]
        ]
    )


def _refresh_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data="refresh:yes"),
                InlineKeyboardButton(text="Нет", callback_data="refresh:no"),
            ]
        ]
    )


class Onboarding(StatesGroup):
    """Шаги онбординга."""

    money_now = State()
    income_kind = State()
    times_per_month = State()
    fixed_first = State()
    fixed_second = State()
    irregular_amount = State()


async def show_intro(message: Message, state: FSMContext) -> None:
    """Показывает вводный экран с кнопками."""
    await state.set_state(None)
    await message.answer(INTRO_TEXT, reply_markup=_intro_keyboard())


async def on_start_pressed(callback: CallbackQuery, state: FSMContext) -> None:
    """[Начать]: переходим к вопросу о деньгах."""
    await callback.answer()
    await state.set_state(Onboarding.money_now)
    if isinstance(callback.message, Message):
        await callback.message.answer(MONEY_TEXT)


async def on_later_pressed(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """[Позже]: пропускаем онбординг."""
    await callback.answer()
    if callback.from_user is None:
        return
    user = await users_repo.get_or_create(session, callback.from_user.id)
    await users_repo.skip_onboarding(session, user)
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Хорошо, вернёшься — напиши /start."
        )


async def process_money_now(message: Message, state: FSMContext) -> None:
    """Шаг 2: деньги сейчас (число)."""
    try:
        amount = parse_amount(message.text)
    except ValueError as exc:
        await message.answer(f"{exc}\nПопробуй ещё раз.")
        return
    await state.update_data(free_money=amount)
    await state.set_state(Onboarding.income_kind)
    await message.answer(INCOME_KIND_TEXT, reply_markup=_income_kind_keyboard())


async def on_income_kind_pressed(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Шаг 3: выбор формата дохода."""
    if callback.data is None:
        return
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    if callback.data == "onboarding:income_irregular":
        await state.update_data(income_type=IncomeType.IRREGULAR.value)
        await state.set_state(Onboarding.irregular_amount)
        await message.answer(IRREGULAR_TEXT)
        return

    await state.update_data(income_type=IncomeType.FIXED.value)
    await state.set_state(Onboarding.times_per_month)
    await message.answer(TIMES_TEXT, reply_markup=_times_keyboard())


async def on_times_pressed(callback: CallbackQuery, state: FSMContext) -> None:
    """Шаг 4A: сколько раз в месяц приходят деньги."""
    if callback.data is None:
        return
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    if callback.data == "onboarding:times_2":
        await state.update_data(times=2)
        await state.set_state(Onboarding.fixed_first)
        await message.answer(FIXED_FIRST_TEXT)
        return

    await state.update_data(times=1)
    await state.set_state(Onboarding.fixed_first)
    await message.answer(FIXED_ONE_TEXT)


async def process_fixed_first(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Шаг 4A.1 / первая дата при двух поступлениях."""
    try:
        entry = parse_day_and_amount(message.text)
    except ValueError as exc:
        await message.answer(f"{exc}\nПопробуй ещё раз.")
        return

    data = await state.get_data()
    await state.update_data(fixed_first=entry)
    if data.get("times") == 2:
        await state.set_state(Onboarding.fixed_second)
        await message.answer(FIXED_SECOND_TEXT)
        return
    await _finish(message, state, session, entries=[entry])


async def process_fixed_second(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Шаг 4A.2: вторая дата при двух поступлениях."""
    try:
        entry = parse_day_and_amount(message.text)
    except ValueError as exc:
        await message.answer(f"{exc}\nПопробуй ещё раз.")
        return

    data = await state.get_data()
    first = data.get("fixed_first")
    entries = [tuple(first), entry] if first else [entry]
    await _finish(message, state, session, entries=entries)


async def process_irregular_amount(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Шаг 4B: средний доход в месяц (irregular)."""
    try:
        amount = parse_amount(message.text)
    except ValueError as exc:
        await message.answer(f"{exc}\nПопробуй ещё раз.")
        return
    await _finish(message, state, session, irregular_income=amount)


async def _finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    *,
    entries: list[tuple[int, int]] | None = None,
    irregular_income: int | None = None,
) -> None:
    """Сохраняет профиль и завершает онбординг."""
    if message.from_user is None:
        await state.clear()
        return

    data = await state.get_data()
    user = await users_repo.get_or_create(session, message.from_user.id)
    income_type = data.get("income_type") or IncomeType.FIXED.value

    income_dates = dump_income_dates(entries) if entries else None
    card_balance = int(data.get("free_money") or 0)
    family_id = data.get("family_id")
    await users_repo.save_onboarding_profile(
        session,
        user,
        income_type=income_type,
        income_dates=income_dates,
        income=irregular_income,
    )
    await accounts_repo.create_accounts(
        session,
        message.from_user.id,
        family_id=family_id,
        card_balance=card_balance,
    )
    await state.clear()
    await message.answer(FINISH_TEXT)


async def cmd_refresh(message: Message, state: FSMContext) -> None:
    """Запрашивает подтверждение сброса данных."""
    await state.clear()
    await message.answer(
        "Точно сбросить все данные и начать заново?",
        reply_markup=_refresh_keyboard(),
    )


async def on_refresh_yes(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """[Да]: удаляет данные пользователя и запускает онбординг заново."""
    await callback.answer()
    if callback.from_user is None or not isinstance(callback.message, Message):
        return
    await users_repo.delete_user(session, callback.from_user.id)
    await state.clear()
    await show_intro(callback.message, state)


async def on_refresh_no(callback: CallbackQuery, state: FSMContext) -> None:
    """[Нет]: отменяет сброс."""
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer("Отменено")


def build_router() -> Router:
    """Создаёт роутер онбординга."""
    router = Router(name="onboarding")

    router.message.register(cmd_refresh, Command("refresh"))
    router.callback_query.register(
        on_start_pressed, F.data == "onboarding:start"
    )
    router.callback_query.register(
        on_later_pressed, F.data == "onboarding:later"
    )
    router.callback_query.register(
        on_income_kind_pressed,
        F.data.in_({"onboarding:income_fixed", "onboarding:income_irregular"}),
    )
    router.callback_query.register(
        on_times_pressed, F.data.in_({"onboarding:times_1", "onboarding:times_2"})
    )
    router.callback_query.register(on_refresh_yes, F.data == "refresh:yes")
    router.callback_query.register(on_refresh_no, F.data == "refresh:no")

    router.message.register(process_money_now, Onboarding.money_now)
    router.message.register(process_fixed_first, Onboarding.fixed_first)
    router.message.register(process_fixed_second, Onboarding.fixed_second)
    router.message.register(process_irregular_amount, Onboarding.irregular_amount)
    return router
