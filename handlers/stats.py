"""Команда /stats — сводка Фаз 2–3."""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from models import Transaction, User
from models.base import IncomeType, TransactionType
from services import debts_repo, transactions_repo, users_repo
from services.calculations import parse_income_dates
from utils.money import format_amount

router = Router(name="stats")

LAST_LIMIT = 5
UPCOMING_DAYS = 30


def format_income_lines(user: User) -> list[str]:
    """Строки блока «Доход». Пустой список — блок скрывается.

    Без скобок и запятых, чтобы Telegram не принимал текст за ссылку.
    """
    if user.income_type == IncomeType.IRREGULAR.value:
        if user.income:
            return [
                "Доход: нерегулярный",
                f"Среднее в месяц: {format_amount(user.income)}",
            ]
        return []
    entries = parse_income_dates(user.income_dates)
    if not entries:
        return []
    lines = ["Доход:"]
    for day, amount in sorted(entries, key=lambda item: item[0]):
        lines.append(f"{day} числа — {format_amount(amount)}")
    return lines


def format_date_label(created_at_iso: str, today: date) -> str:
    """Метка даты: «сегодня», «вчера» или «дд.мм»."""
    try:
        moment = datetime.fromisoformat(created_at_iso)
    except ValueError:
        return created_at_iso
    day = moment.date()
    if day == today:
        return "сегодня"
    if day == today - timedelta(days=1):
        return "вчера"
    return day.strftime("%d.%m")


def format_transaction_line(transaction: Transaction, today: date) -> str:
    """Строка последней операции со знаком и меткой даты."""
    if transaction.type == TransactionType.EXPENSE.value:
        signed = f"−{format_amount(transaction.amount)}"
    elif transaction.type == TransactionType.INCOME.value:
        signed = f"+{format_amount(transaction.amount)}"
    else:
        sign = "+" if transaction.amount >= 0 else "−"
        signed = f"{sign}{format_amount(abs(transaction.amount))}"
    return f"{signed} ({format_date_label(transaction.created_at, today)})"


def _period_line(title: str, amount: int) -> str:
    """Строка «За период» со знаком сальдо: «За сегодня: +25 800 ₽»."""
    if amount > 0:
        return f"{title}: +{format_amount(amount)}"
    if amount < 0:
        return f"{title}: −{format_amount(abs(amount))}"
    return f"{title}: {format_amount(0)}"


def format_payment_line(payment_date: date, debt: object) -> str:
    """Строка ближайшего платежа: «25.09 — Кредит: 46 000 ₽»."""
    return (
        f"{payment_date.strftime('%d.%m')} — {debt.name}: "  # type: ignore[attr-defined]
        f"{format_amount(debt.amount)}"  # type: ignore[attr-defined]
    )


def next_salary_date(user: User, today: date) -> date | None:
    """Дата следующей зарплаты (для фиксированного дохода) или None."""
    if user.income_type != IncomeType.FIXED.value:
        return None
    entries = parse_income_dates(user.income_dates)
    if not entries:
        return None
    salary_day = min(day for day, _ in entries)
    return debts_repo.next_payment_date(salary_day, today)


def end_of_month(today: date) -> date:
    """Последний день текущего календарного месяца."""
    last_day = calendar.monthrange(today.year, today.month)[1]
    return date(today.year, today.month, last_day)


async def build_stats_text(
    session: AsyncSession, user: User, today: date | None = None
) -> str:
    """Собирает текст сводки /stats."""
    today = today or datetime.now(UTC).date()
    free_money = user.free_money or 0
    lines = [f"Свободно: {format_amount(free_money)}"]

    income_lines = format_income_lines(user)
    if income_lines:
        lines.append("")
        lines.extend(income_lines)

    upcoming = await debts_repo.get_upcoming_payments(
        session, user.telegram_id, UPCOMING_DAYS, today
    )
    if upcoming:
        lines.append("")
        lines.append("Ближайшие платежи:")
        lines.extend(
            format_payment_line(payment_date, debt)
            for payment_date, debt in upcoming
        )

    debts = await debts_repo.get_debts(session, user.telegram_id)
    if debts:
        salary_date = next_salary_date(user, today)
        month_end = end_of_month(today)
        until_salary = 0
        until_month_end = 0
        for debt in debts:
            dates = debts_repo.payments_within(
                debt.payment_day, today, UPCOMING_DAYS
            )
            if salary_date is not None:
                until_salary += sum(
                    debt.amount
                    for payment_date in dates
                    if payment_date <= salary_date
                )
            until_month_end += sum(
                debt.amount for payment_date in dates if payment_date <= month_end
            )

        lines.append("")
        if salary_date is not None:
            lines.append(
                f"Свободно до ЗП: {format_amount(free_money - until_salary)}"
            )
        lines.append(
            f"Свободно до конца месяца: "
            f"{format_amount(free_money - until_month_end)}"
        )

    last = await transactions_repo.get_last_transactions(
        session, user.telegram_id, LAST_LIMIT
    )
    if last:
        lines.append("")
        lines.append("Последние операции:")
        lines.extend(format_transaction_line(item, today) for item in last)

        lines.append("")
        lines.append(
            _period_line(
                "За сегодня",
                await transactions_repo.get_balance_by_period(
                    session, user.telegram_id, "today"
                ),
            )
        )
        lines.append(
            _period_line(
                "За неделю",
                await transactions_repo.get_balance_by_period(
                    session, user.telegram_id, "week"
                ),
            )
        )
        lines.append(
            _period_line(
                "За месяц",
                await transactions_repo.get_balance_by_period(
                    session, user.telegram_id, "month"
                ),
            )
        )

    return "\n".join(lines)


async def cmd_stats(message: Message, session: AsyncSession) -> None:
    """Показывает сводку: баланс, доход, операции и суммы за период."""
    if message.from_user is None:
        return

    user = await users_repo.get_by_telegram_id(session, message.from_user.id)
    if user is None or not user.onboarding_completed:
        await message.answer("Сначала пройди онбординг: /start")
        return

    await message.answer(await build_stats_text(session, user))


def build_router() -> Router:
    """Создаёт роутер сводки."""
    router = Router(name="stats")
    router.message.register(cmd_stats, Command("stats"))
    return router
