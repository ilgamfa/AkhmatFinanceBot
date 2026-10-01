"""Логика напоминаний (Фаза 8): проверка записей, выборка платежей и тексты."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Debt, DebtPayment, Transaction, User
from services import debts_repo
from services.calculations import day_bounds_utc
from services.stats_service import PaymentVerdict
from utils.money import format_amount

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

EVENING_TEXT = "Привет! Как прошёл день? Не забудь записать траты."


def now_moscow(now: datetime | None = None) -> datetime:
    """Текущее время в Europe/Moscow (или переданное для тестов)."""
    return now or datetime.now(MOSCOW_TZ)


def moscow_today(now: datetime | None = None) -> date:
    """Сегодняшняя дата по Europe/Moscow."""
    return now_moscow(now).date()


def _day_bounds_utc(day: date) -> tuple[str, str]:
    """Границы суток MSK в UTC (``created_at`` хранится в UTC, ISO)."""
    return day_bounds_utc(day)


async def has_transactions_today(
    session: AsyncSession, telegram_id: int, today: date
) -> bool:
    """Были ли у пользователя записи за сутки ``today`` по Europe/Moscow."""
    start_iso, end_iso = _day_bounds_utc(today)
    result = await session.execute(
        select(Transaction.id)
        .where(
            Transaction.telegram_id == telegram_id,
            Transaction.created_at >= start_iso,
            Transaction.created_at < end_iso,
        )
        .limit(1)
    )
    return result.first() is not None


async def check_evening_reminder(
    session: AsyncSession, user: User, today: date
) -> bool:
    """Нужно ли отправить вечернее напоминание.

    ``True`` — сегодня записей нет и напоминание ещё не отправлялось.
    """
    if user.reminder_evening_last_sent == today:
        return False
    return not await has_transactions_today(session, user.telegram_id, today)


async def get_upcoming_payments(
    session: AsyncSession,
    telegram_id: int,
    days_before: int,
    today: date,
) -> list[tuple[DebtPayment, Debt]]:
    """Неоплаченные платежи, срок которых наступит через ``days_before`` дней."""
    target = today + timedelta(days=days_before)
    return await debts_repo.get_pending_payments(session, telegram_id, target, target)


def day_word(days_before: int) -> str:
    """Слово для заголовка: «Сегодня» / «Завтра» / «Через N дн.»."""
    if days_before <= 0:
        return "Сегодня"
    if days_before == 1:
        return "Завтра"
    return f"Через {days_before} дн."


def compose_evening_text() -> str:
    """Текст вечернего напоминания."""
    return EVENING_TEXT


def _format_balance(amount: int) -> str:
    """Баланс со знаком: отрицательный — «−5 000 ₽» (U+2212)."""
    if amount < 0:
        return f"−{format_amount(abs(amount))}"
    return format_amount(amount)


def _verdict_tail(free: int, shortfall: int) -> str:
    """Хвост вердикта: «хватает ✅» или «не хватает ❌ (нужно ещё X ₽)»."""
    if shortfall <= 0:
        return f"Свободно: {_format_balance(free)} — хватает ✅"
    return (
        f"Свободно: {_format_balance(free)} — "
        f"не хватает ❌ (нужно ещё {format_amount(shortfall)})"
    )


def compose_payment_text(
    days_before: int,
    verdicts: list[PaymentVerdict],
) -> str:
    """Текст платёжного напоминания с вердиктом «хватает / не хватает».

    Вердикты приходят уже посчитанными со сквозным балансом и доходом
    владельца (та же логика, что в ``/stats``). Несколько платежей в один
    день — нумерованным списком.
    """
    word = day_word(days_before)

    if len(verdicts) == 1:
        verdict = verdicts[0]
        return (
            f"{word} платёж по «{verdict.debt_name}»: "
            f"{format_amount(verdict.amount)}. "
            f"{_verdict_tail(verdict.free, verdict.shortfall)}"
        )

    lines = [f"{word} платежи:"]
    for index, verdict in enumerate(verdicts, start=1):
        lines.append(
            f"{index}. {verdict.debt_name}: {format_amount(verdict.amount)} — "
            f"{_verdict_tail(verdict.free, verdict.shortfall)}"
        )
    return "\n".join(lines)
