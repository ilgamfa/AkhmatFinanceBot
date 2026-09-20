"""Операции с копилкой (Фаза 4)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Allocation, Goal, Savings


async def get_savings(session: AsyncSession, telegram_id: int) -> int:
    """Баланс копилки пользователя (0, если копилка ещё не создана)."""
    result = await session.execute(
        select(Savings.balance).where(Savings.telegram_id == telegram_id)
    )
    balance = result.scalar_one_or_none()
    return int(balance) if balance is not None else 0


async def add_to_savings(
    session: AsyncSession, telegram_id: int, amount: int
) -> int:
    """Пополняет копилку и возвращает новый баланс.

    Создаёт запись, если копилки ещё нет.
    """
    if amount <= 0:
        raise ValueError("Сумма пополнения должна быть больше нуля.")
    savings = await session.get(Savings, telegram_id)
    if savings is None:
        savings = Savings(telegram_id=telegram_id, balance=0)
        session.add(savings)
    savings.balance = (savings.balance or 0) + amount
    await session.commit()
    await session.refresh(savings)
    return savings.balance


async def get_allocated_total(session: AsyncSession, telegram_id: int) -> int:
    """Сумма всех связей копилки с целями пользователя."""
    result = await session.execute(
        select(func.coalesce(func.sum(Allocation.amount), 0))
        .join(Goal, Allocation.goal_id == Goal.id)
        .where(Goal.telegram_id == telegram_id)
    )
    return int(result.scalar_one())


async def get_free_in_savings(session: AsyncSession, telegram_id: int) -> int:
    """Свободно в копилке: баланс минус закреплённое по целям."""
    balance = await get_savings(session, telegram_id)
    allocated = await get_allocated_total(session, telegram_id)
    return balance - allocated