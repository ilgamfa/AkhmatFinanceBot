"""Тесты /forecast Фазы 4."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from handlers.forecast import build_forecast_text
from models import User
from services import (
    accounts_repo,
    allocations_repo,
    debts_repo,
    goals_repo,
    users_repo,
)
from services.calculations import dump_income_dates

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]

FIXED_TODAY = date(2026, 9, 20)


async def _profile_user(session: AsyncSession, user_id: int = 1) -> User:
    """Создаёт пользователя с фиксированным профилем («20 числа — 50000 ₽»)."""
    user = await users_repo.get_or_create(session, user_id)
    user = await users_repo.save_onboarding_profile(
        session,
        user,
        income_type="fixed",
        income_dates=dump_income_dates([(20, 50000)]),
    )
    await accounts_repo.create_accounts(session, user_id, card_balance=12000)
    return user


async def test_forecast_calculates_exact(session: AsyncSession) -> None:
    """Прогноз: свободно + доход − долги − цели, при минусе — предупреждение.

    Прогресс цели берётся из связей копилки.
    """
    user = await _profile_user(session)
    await debts_repo.add_debt(session, 1, "Кредит", "loan", 46000, 25)
    savings = await accounts_repo.ensure_account(session, 1, "savings")
    await accounts_repo.correct_balance(session, savings.id, 50000)
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, "2027-12-25", 1)
    await allocations_repo.allocate(session, goal.id, 50000, 1)

    text = await build_forecast_text(session, user, today=FIXED_TODAY)
    assert "Прогноз на ближайший месяц:" in text
    assert "Свободно сейчас: 12 000 ₽" in text
    assert "Доход до конца месяца: 50 000 ₽" in text
    assert "Обязательные платежи: 46 000 ₽" in text
    assert "Отложить на цели: 96 667 ₽" in text
    assert "Свободно после всего: −80 667 ₽" in text
    assert "⚠️ Ты в минусе. Цели под угрозой." in text


async def test_forecast_goal_without_deadline_excluded(session: AsyncSession) -> None:
    """Цели без срока не добавляют «нужно в месяц» в прогноз."""
    user = await _profile_user(session)
    await debts_repo.add_debt(session, 1, "Кредит", "loan", 46000, 25)
    savings = await accounts_repo.ensure_account(session, 1, "savings")
    await accounts_repo.correct_balance(session, savings.id, 50000)
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)
    await allocations_repo.allocate(session, goal.id, 50000, 1)

    text = await build_forecast_text(session, user, today=FIXED_TODAY)
    assert "Отложить на цели: 0 ₽" in text
    assert "Свободно после всего: 16 000 ₽" in text


async def test_forecast_positive_no_warning(session: AsyncSession) -> None:
    """Без целей прогноз положительный — предупреждения нет."""
    user = await _profile_user(session)
    await debts_repo.add_debt(session, 1, "Кредит", "loan", 46000, 25)

    text = await build_forecast_text(session, user, today=FIXED_TODAY)
    assert "Свободно после всего: 16 000 ₽" in text
    assert "⚠️" not in text


async def test_forecast_minus_warns_via_command(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    """Команда /forecast предупреждает при минусе независимо от даты."""
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("12000")
    await send_callback("onboarding:income_fixed")
    await send_callback("onboarding:times_1")
    await send_message("10, 50000")
    await debts_repo.add_debt(session, 1, "Кредит", "loan", 999999, 25)

    text = (await send_message("/forecast"))[0]
    assert "Свободно после всего: −" in text
    assert "⚠️ Ты в минусе. Цели под угрозой." in text


async def test_forecast_requires_onboarding(send_message: Send) -> None:
    text = (await send_message("/forecast"))[0]
    assert "Сначала пройди онбординг" in text