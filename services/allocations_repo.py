"""Операции со связями копилок и целей (Фазы 4–5).

Каждый участник закрепляет деньги из своей копилки. Прогресс цели —
сумма всех связей (с обоих копилок семьи).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Allocation, Goal
from services import accounts_repo


async def get_allocations_by_goal(
    session: AsyncSession, goal_id: int
) -> list[Allocation]:
    """Связи по конкретной цели."""
    result = await session.execute(
        select(Allocation)
        .where(Allocation.goal_id == goal_id)
        .order_by(Allocation.id)
    )
    return list(result.scalars().all())


async def get_allocations_by_user(
    session: AsyncSession, telegram_id: int
) -> dict[int, int]:
    """Суммы связей пользователя: {goal_id: моя сумма}."""
    result = await session.execute(
        select(Allocation.goal_id, func.coalesce(func.sum(Allocation.amount), 0))
        .where(Allocation.telegram_id == telegram_id)
        .group_by(Allocation.goal_id)
    )
    return {goal_id: int(total) for goal_id, total in result.all()}


async def allocate(
    session: AsyncSession,
    goal_id: int,
    amount: int,
    telegram_id: int | None = None,
) -> int:
    """Закрепляет сумму из копилки за целью. Возвращает прогресс цели.

    Бросает ValueError, если сумма не положительная, цель недоступна или
    превышает свободное в копилке закрепляющего.
    """
    if amount <= 0:
        raise ValueError("Сумма должна быть больше нуля.")
    goal = await session.get(Goal, goal_id)
    if goal is None:
        raise ValueError("Цель не найдена.")
    allocator = telegram_id if telegram_id is not None else goal.telegram_id
    free = await get_free_in_savings(session, allocator)
    if amount > free:
        raise ValueError("Недостаточно свободных денег в копилке.")
    session.add(
        Allocation(goal_id=goal_id, telegram_id=allocator, amount=amount)
    )
    await session.commit()
    return await get_goal_progress_amount(session, goal_id)


async def get_goal_progress_amount(session: AsyncSession, goal_id: int) -> int:
    """Сумма всех связей по цели."""
    result = await session.execute(
        select(func.coalesce(func.sum(Allocation.amount), 0)).where(
            Allocation.goal_id == goal_id
        )
    )
    return int(result.scalar_one())


async def unallocate(session: AsyncSession, goal_id: int, amount: int) -> int:
    """Снимает с цели сумму, начиная с последней связи. Возвращает прогресс.

    Бросает ValueError, если сумма не положительная или её больше, чем
    закреплено за целью.
    """
    if amount <= 0:
        raise ValueError("Сумма должна быть больше нуля.")
    allocations = await get_allocations_by_goal(session, goal_id)
    total = sum(allocation.amount for allocation in allocations)
    if amount > total:
        raise ValueError("Нельзя снять больше, чем закреплено.")

    remaining = amount
    for allocation in reversed(allocations):
        if remaining == 0:
            break
        if allocation.amount <= remaining:
            remaining -= allocation.amount
            await session.delete(allocation)
        else:
            allocation.amount -= remaining
            remaining = 0
    await session.commit()
    return await get_goal_progress_amount(session, goal_id)


async def get_free_in_savings(session: AsyncSession, telegram_id: int) -> int:
    """Свободно в копилке: баланс минус собственные связи."""
    balance = await accounts_repo.get_balance(session, telegram_id, "savings")
    allocated = sum(
        (await get_allocations_by_user(session, telegram_id)).values()
    )
    return balance - allocated


__all__ = [
    "allocate",
    "get_allocations_by_goal",
    "get_allocations_by_user",
    "get_free_in_savings",
    "get_goal_progress_amount",
    "unallocate",
]
