"""Операции со связями копилки и целей (Фаза 4)."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Allocation, Goal
from services import goals_repo, savings_repo


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
    """Суммы связей по целям пользователя: {goal_id: сумма}."""
    result = await session.execute(
        select(Goal.id, func.coalesce(func.sum(Allocation.amount), 0))
        .join(Allocation, Allocation.goal_id == Goal.id)
        .where(Goal.telegram_id == telegram_id)
        .group_by(Goal.id)
    )
    return {goal_id: int(total) for goal_id, total in result.all()}


async def allocate(session: AsyncSession, goal_id: int, amount: int) -> int:
    """Закрепляет сумму из копилки за целью.

    Возвращает новый прогресс цели. Бросает ValueError, если сумма
    не положительная или превышает свободное в копилке.
    """
    if amount <= 0:
        raise ValueError("Сумма должна быть больше нуля.")
    goal = await session.get(Goal, goal_id)
    if goal is None:
        raise ValueError("Цель не найдена.")
    free = await savings_repo.get_free_in_savings(session, goal.telegram_id)
    if amount > free:
        raise ValueError("Недостаточно свободных денег в копилке.")
    session.add(Allocation(goal_id=goal_id, amount=amount))
    await session.commit()
    return await goals_repo.get_goal_progress(session, goal_id)


async def unallocate(session: AsyncSession, goal_id: int, amount: int) -> int:
    """Снимает сумму с цели и возвращает новый прогресс цели.

    Бросает ValueError, если сумма не положительная или больше
    закреплённого по цели.
    """
    if amount <= 0:
        raise ValueError("Сумма должна быть больше нуля.")
    total = await goals_repo.get_goal_progress(session, goal_id)
    if amount > total:
        raise ValueError("Нельзя снять больше, чем закреплено за целью.")
    remaining = amount
    for allocation in await get_allocations_by_goal(session, goal_id):
        if remaining <= 0:
            break
        if allocation.amount <= remaining:
            remaining -= allocation.amount
            await session.delete(allocation)
        else:
            allocation.amount -= remaining
            remaining = 0
    await session.commit()
    return total - amount


async def delete_allocations_for_goal(session: AsyncSession, goal_id: int) -> None:
    """Удаляет все связи цели (при удалении цели)."""
    await session.execute(delete(Allocation).where(Allocation.goal_id == goal_id))
    await session.commit()