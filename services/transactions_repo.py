"""Операции с транзакциями Фазы 2."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Transaction
from models.base import TransactionType

VALID_PERIODS = ("today", "week", "month")


def _now_iso() -> str:
    """Текущее время в ISO-формате (UTC)."""
    return datetime.now(UTC).isoformat()


async def add_transaction(
    session: AsyncSession,
    telegram_id: int,
    transaction_type: str,
    amount: int,
) -> Transaction:
    """Записывает операцию и возвращает её."""
    transaction = Transaction(
        telegram_id=telegram_id,
        type=transaction_type,
        amount=amount,
        created_at=_now_iso(),
    )
    session.add(transaction)
    await session.commit()
    await session.refresh(transaction)
    return transaction


async def get_last_transactions(
    session: AsyncSession, telegram_id: int, limit: int = 5
) -> list[Transaction]:
    """Возвращает последние ``limit`` операций (сначала новые)."""
    result = await session.execute(
        select(Transaction)
        .where(Transaction.telegram_id == telegram_id)
        .order_by(Transaction.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


def _period_start(period: str) -> datetime:
    """Начало периода в UTC."""
    now = datetime.now(UTC)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return now - timedelta(days=7)
    if period == "month":
        return now - timedelta(days=30)
    raise ValueError(f"Неизвестный период: {period}")


async def get_sum_by_period(
    session: AsyncSession, telegram_id: int, period: str
) -> int:
    """Сумма трат (type=expense) за период today/week/month."""
    if period not in VALID_PERIODS:
        raise ValueError(f"Неизвестный период: {period}")

    start_iso = _period_start(period).isoformat()
    result = await session.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.telegram_id == telegram_id,
            Transaction.type == TransactionType.EXPENSE.value,
            Transaction.created_at >= start_iso,
        )
    )
    return int(result.scalar_one())
