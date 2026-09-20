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
    account_id: int | None = None,
) -> Transaction:
    """Записывает операцию и возвращает её."""
    transaction = Transaction(
        telegram_id=telegram_id,
        account_id=account_id,
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


async def get_last_family_transactions(
    session: AsyncSession, telegram_ids: list[int], limit: int = 5
) -> list[Transaction]:
    """Последние операции всех участников семьи (сначала новые)."""
    result = await session.execute(
        select(Transaction)
        .where(Transaction.telegram_id.in_(telegram_ids))
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


async def get_balance_by_period(
    session: AsyncSession, telegram_id: int, period: str
) -> int:
    """Сальдо за период: доход + корректировки − траты.

    Суммы correction уже хранятся со знаком влияния на баланс:
    положительная — баланс вырос, отрицательная — упал.
    """
    if period not in VALID_PERIODS:
        raise ValueError(f"Неизвестный период: {period}")

    start_iso = _period_start(period).isoformat()
    result = await session.execute(
        select(Transaction.type, func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.telegram_id == telegram_id,
            Transaction.created_at >= start_iso,
        )
        .group_by(Transaction.type)
    )
    balance = 0
    for transaction_type, total in result.all():
        if transaction_type in (
            TransactionType.EXPENSE.value,
            TransactionType.SAVINGS_ADD.value,
        ):
            balance -= int(total)
        else:
            balance += int(total)
    return balance


async def get_family_balance_by_period(
    session: AsyncSession, telegram_ids: list[int], period: str
) -> int:
    """Сальдо за период по всем участникам семьи."""
    if period not in VALID_PERIODS:
        raise ValueError(f"Неизвестный период: {period}")

    start_iso = _period_start(period).isoformat()
    result = await session.execute(
        select(Transaction.type, func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.telegram_id.in_(telegram_ids),
            Transaction.created_at >= start_iso,
        )
        .group_by(Transaction.type)
    )
    balance = 0
    for transaction_type, total in result.all():
        if transaction_type in (
            TransactionType.EXPENSE.value,
            TransactionType.SAVINGS_ADD.value,
        ):
            balance -= int(total)
        else:
            balance += int(total)
    return balance
