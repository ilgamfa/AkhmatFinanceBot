"""Тесты /forecast Фазы 9: горизонты, доход, траты, вердикт."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, timedelta

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from handlers.forecast import build_forecast_text
from models import User
from services import (
    accounts_repo,
    categories_repo,
    debts_repo,
    transactions_repo,
    users_repo,
)
from services.calculations import dump_income_dates

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]

FIXED_TODAY = date(2026, 9, 20)


async def _onboard(send_message: Send, send_callback: Press) -> None:
    """Проходит онбординг с доходом 23 числа, 50 000 ₽."""
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("50000")
    await send_message("Т-Банк")
    await send_callback("onboarding:income_fixed")
    await send_callback("onboarding:times_1")
    await send_message("23, 50000")


async def _fixed_user(
    session: AsyncSession,
    entries: tuple[tuple[int, int], ...] = ((23, 50000),),
    balance: int = 50000,
    user_id: int = 1,
) -> User:
    """Пользователь с фиксированным доходом и картой."""
    user = await users_repo.get_or_create(session, user_id)
    user = await users_repo.save_onboarding_profile(
        session,
        user,
        income_type="fixed",
        income_dates=dump_income_dates(list(entries)),
    )
    await accounts_repo.create_accounts(session, user_id, card_balance=balance)
    return user


async def _irregular_user(
    session: AsyncSession, income: int | None, user_id: int = 1
) -> User:
    """Пользователь с нерегулярным доходом."""
    user = await users_repo.get_or_create(session, user_id)
    user = await users_repo.save_onboarding_profile(
        session, user, income_type="irregular", income=income
    )
    await accounts_repo.create_accounts(session, user_id)
    return user


async def _add_debt(
    session: AsyncSession, telegram_id: int, amount: int, due_date: date
) -> None:
    """Добавляет долг с единственным платежом."""
    debt = await debts_repo.create_debt(session, telegram_id, "Кредит")
    await debts_repo.add_payment(session, debt.id, amount, due_date)


# --- кнопки -------------------------------------------------------------------


async def test_forecast_shows_horizon_buttons(
    send_message: Send, send_callback: Press, bot: object
) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/forecast")
    assert "На какой срок" in replies[0]

    markup = bot.session.last_reply_markup  # type: ignore[attr-defined]
    assert isinstance(markup, InlineKeyboardMarkup)
    labels = [button.text for row in markup.inline_keyboard for button in row]
    assert labels == ["1", "3", "6", "12"]


async def test_horizon_switch_edits_message(
    send_message: Send, send_callback: Press, bot: object
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/forecast")
    await send_callback("forecast:3")
    edited = bot.session.edited  # type: ignore[attr-defined]
    assert "Прогноз на 3 месяца" in edited[-1].text


# --- расчёты ------------------------------------------------------------------


async def test_forecast_month(session: AsyncSession) -> None:
    user = await _fixed_user(session)
    category = await categories_repo.add_category(session, 1, "Продукты", "expense")
    await transactions_repo.add_transaction(
        session, 1, "expense", 90000, category_id=category.id
    )
    await _add_debt(session, 1, 10000, FIXED_TODAY + timedelta(days=5))

    text = await build_forecast_text(session, user, 1, today=FIXED_TODAY)
    assert "Прогноз на 1 месяц:" in text
    assert "Сейчас: 50 000 ₽" in text
    assert "Доход: 50 000 ₽" in text
    assert "Долги: 10 000 ₽" in text
    assert "Траты: 30 000 ₽" in text
    assert "Через 1 месяц: 60 000 ₽" in text
    assert "всё под контролем" in text


async def test_forecast_three_months(session: AsyncSession) -> None:
    user = await _fixed_user(session)
    category = await categories_repo.add_category(session, 1, "Продукты", "expense")
    await transactions_repo.add_transaction(
        session, 1, "expense", 90000, category_id=category.id
    )
    await _add_debt(session, 1, 10000, FIXED_TODAY + timedelta(days=15))

    text = await build_forecast_text(session, user, 3, today=FIXED_TODAY)
    assert "Прогноз на 3 месяца:" in text
    assert "Доход: 150 000 ₽" in text
    assert "Долги: 10 000 ₽" in text
    assert "Траты: 90 000 ₽" in text
    assert "Через 3 месяца: 100 000 ₽" in text
    assert "Средние траты в месяц:" in text
    assert "Продукты: 30 000 ₽" in text


async def test_fixed_income_sums_entries(session: AsyncSession) -> None:
    """Доход: каждое вхождение income_dates, попавшее в период."""
    user = await _fixed_user(session, entries=((23, 50000), (5, 20000)))
    text = await build_forecast_text(session, user, 3, today=FIXED_TODAY)
    assert "Доход: 210 000 ₽" in text


async def test_irregular_income_multiplied(session: AsyncSession) -> None:
    user = await _irregular_user(session, income=40000)
    three = await build_forecast_text(session, user, 3, today=FIXED_TODAY)
    one = await build_forecast_text(session, user, 1, today=FIXED_TODAY)
    assert "Доход: 120 000 ₽" in three
    assert "Доход: 40 000 ₽" in one


async def test_irregular_without_income(session: AsyncSession) -> None:
    user = await _irregular_user(session, income=None)
    text = await build_forecast_text(session, user, 3, today=FIXED_TODAY)
    assert "Доход: 0 ₽" in text
    assert "Доход нерегулярный, среднее не указано" in text


async def test_average_expenses_by_category(session: AsyncSession) -> None:
    user = await _fixed_user(session)
    category = await categories_repo.add_category(session, 1, "Продукты", "expense")
    await transactions_repo.add_transaction(
        session, 1, "expense", 60000, category_id=category.id
    )
    await transactions_repo.add_transaction(
        session, 1, "expense", 30000, category_id=category.id
    )

    text = await build_forecast_text(session, user, 3, today=FIXED_TODAY)
    assert "Средние траты в месяц:" in text
    assert "Продукты: 30 000 ₽" in text


async def test_no_expense_data(session: AsyncSession) -> None:
    user = await _fixed_user(session)
    text = await build_forecast_text(session, user, 3, today=FIXED_TODAY)
    assert "Прогноз на 3 месяца (только доходы и долги):" in text
    assert "Средние траты:* пока нет данных для расчёта." in text


# --- вердикт ------------------------------------------------------------------


async def test_negative_verdict_warns(session: AsyncSession) -> None:
    user = await _fixed_user(session, balance=1000)
    await _add_debt(session, 1, 500000, FIXED_TODAY + timedelta(days=10))
    text = await build_forecast_text(session, user, 1, today=FIXED_TODAY)
    assert "уйдёшь в минус" in text
    assert "⚠️" in text


async def test_positive_verdict_praises(session: AsyncSession) -> None:
    user = await _fixed_user(session)
    text = await build_forecast_text(session, user, 1, today=FIXED_TODAY)
    assert "всё под контролем" in text
    assert "уйдёшь в минус" not in text


async def test_forecast_requires_onboarding(send_message: Send) -> None:
    replies = await send_message("/forecast")
    assert "Сначала пройди онбординг" in replies[0]
