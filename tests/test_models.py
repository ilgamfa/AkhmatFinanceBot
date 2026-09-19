"""Тесты репозитория транзакций (Фаза 2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models import Transaction
from services import transactions_repo


async def test_add_transaction_writes_to_db(session: AsyncSession) -> None:
    transaction = await transactions_repo.add_transaction(session, 555, "expense", 5000)
    assert transaction.id is not None
    assert transaction.telegram_id == 555
    assert transaction.type == "expense"
    assert transaction.amount == 5000
    assert transaction.created_at

    stored = await session.get(Transaction, transaction.id)
    assert stored is not None
    assert stored.amount == 5000


async def test_get_last_transactions_returns_latest(session: AsyncSession) -> None:
    for amount in (1000, 2000, 3000, 4000, 5000, 6000):
        await transactions_repo.add_transaction(session, 1, "expense", amount)

    last = await transactions_repo.get_last_transactions(session, 1, 3)
    assert [item.amount for item in last] == [6000, 5000, 4000]
    assert await transactions_repo.get_last_transactions(session, 999) == []


async def test_get_sum_by_period_expenses_only(session: AsyncSession) -> None:
    await transactions_repo.add_transaction(session, 1, "expense", 5000)
    await transactions_repo.add_transaction(session, 1, "expense", 1500)
    await transactions_repo.add_transaction(session, 1, "income", 100000)

    assert await transactions_repo.get_sum_by_period(session, 1, "today") == 6500
    assert await transactions_repo.get_sum_by_period(session, 1, "week") == 6500
    assert await transactions_repo.get_sum_by_period(session, 1, "month") == 6500


async def test_get_sum_by_period_excludes_old(session: AsyncSession) -> None:
    old_iso = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    transaction = Transaction(
        telegram_id=1, type="expense", amount=9999, created_at=old_iso
    )
    session.add(transaction)
    await session.commit()
    await transactions_repo.add_transaction(session, 1, "expense", 100)

    assert await transactions_repo.get_sum_by_period(session, 1, "month") == 100
    assert await transactions_repo.get_sum_by_period(session, 1, "week") == 100


async def test_get_sum_by_period_invalid(session: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await transactions_repo.get_sum_by_period(session, 1, "year")
