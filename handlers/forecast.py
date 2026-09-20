"""Команда /forecast — прогноз на ближайший месяц (Фаза 4)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from models import User
from models.base import IncomeType
from services import (
    allocations_repo,
    debts_repo,
    goals_repo,
    users_repo,
)
from services.calculations import end_of_month, monthly_goal_amount, parse_income_dates
from utils.money import format_amount

NEGATIVE_WARNING = "⚠️ Ты в минусе. Цели под угрозой."


def _signed(amount: int) -> str:
    """Форматирует сумму со знаком: минус — как «−111 500 ₽»."""
    if amount < 0:
        return f"−{format_amount(abs(amount))}"
    return format_amount(amount)


def income_until_month_end(user: User, today: date) -> int:
    """Доход до конца месяца.

    Фиксированный доход — суммы income_dates, чей следующий платёж попадает
    в текущий месяц; нерегулярный — средний `users.income`.
    """
    month_end = end_of_month(today)
    if user.income_type == IncomeType.IRREGULAR.value:
        return user.income or 0
    entries = parse_income_dates(user.income_dates)
    total = 0
    for day, amount in entries:
        if debts_repo.next_payment_date(day, today) <= month_end:
            total += amount
    return total


async def build_forecast_text(
    session: AsyncSession, user: User, today: date | None = None
) -> str:
    """Собирает текст прогноза: свободно + доход − долги − цели."""
    today = today or datetime.now(UTC).date()
    free_money = user.free_money or 0
    income = income_until_month_end(user, today)

    month_end = end_of_month(today)
    days_to_month_end = (month_end - today).days
    debts_total = 0
    for debt in await debts_repo.get_debts(session, user.telegram_id):
        debts_total += debt.amount * len(
            debts_repo.payments_within(debt.payment_day, today, days_to_month_end)
        )

    goals = await goals_repo.get_goals(session, user.telegram_id)
    allocated = await allocations_repo.get_allocations_by_user(
        session, user.telegram_id
    )
    goals_monthly = 0
    for goal in goals:
        monthly = monthly_goal_amount(
            allocated.get(goal.id, 0), goal.target, goal.deadline, today
        )
        if monthly is not None:
            goals_monthly += monthly

    after = free_money + income - debts_total - goals_monthly

    lines = [
        "Прогноз на ближайший месяц:",
        "",
        f"Свободно сейчас: {format_amount(free_money)}",
        f"Доход до конца месяца: {format_amount(income)}",
        f"Обязательные платежи: {format_amount(debts_total)}",
        f"Отложить на цели: {format_amount(goals_monthly)}",
        "",
        f"Свободно после всего: {_signed(after)}",
    ]
    if after < 0:
        lines.append(NEGATIVE_WARNING)
    return "\n".join(lines)


async def cmd_forecast(message: Message, session: AsyncSession) -> None:
    """Показывает прогноз на ближайший месяц."""
    if message.from_user is None:
        return

    user = await users_repo.get_by_telegram_id(session, message.from_user.id)
    if user is None or not user.onboarding_completed:
        await message.answer("Сначала пройди онбординг: /start")
        return

    await message.answer(await build_forecast_text(session, user))


def build_router() -> Router:
    """Создаёт роутер команды /forecast."""
    router = Router(name="forecast")
    router.message.register(cmd_forecast, Command("forecast"))
    return router