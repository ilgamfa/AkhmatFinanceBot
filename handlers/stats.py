"""Команда /stats — сводка Фазы 2."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from models import Transaction, User
from models.base import IncomeType, TransactionType
from services import transactions_repo, users_repo
from services.calculations import parse_income_dates
from utils.money import format_amount

router = Router(name="stats")

LAST_LIMIT = 5


def format_income_line(user: User) -> str:
    """Строка «Доход: ...» по профилю пользователя."""
    if user.income_type == IncomeType.IRREGULAR.value:
        return f"Доход: нерегулярный, в среднем {format_amount(user.income or 0)}/мес"
    entries = parse_income_dates(user.income_dates)
    if entries:
        total = sum(amount for _, amount in entries)
        if len(entries) == 1:
            day, _ = entries[0]
            return f"Доход: {format_amount(total)}, {day} числа"
        details = ", ".join(
            f"{day} — {format_amount(amount)}" for day, amount in entries
        )
        return f"Доход: {format_amount(total)} ({details})"
    if user.income:
        return f"Доход: нерегулярный, в среднем {format_amount(user.income)}/мес"
    return "Доход: не указан"


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
    return f"{title}: −{format_amount(amount)}"


async def build_stats_text(
    session: AsyncSession, user: User, today: date | None = None
) -> str:
    """Собирает текст сводки /stats."""
    today = today or datetime.now(UTC).date()
    lines = [f"Свободно: {format_amount(user.free_money or 0)}"]

    income_line = format_income_line(user)
    if income_line:
        lines.append("")
        lines.append(income_line)

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
                await transactions_repo.get_sum_by_period(
                    session, user.telegram_id, "today"
                ),
            )
        )
        lines.append(
            _period_line(
                "За неделю",
                await transactions_repo.get_sum_by_period(
                    session, user.telegram_id, "week"
                ),
            )
        )
        lines.append(
            _period_line(
                "За месяц",
                await transactions_repo.get_sum_by_period(
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
