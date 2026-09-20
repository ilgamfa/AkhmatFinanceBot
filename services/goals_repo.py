"""Операции с целями (Фаза 4)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Allocation, Goal

ALLOWED_FIELDS = ("name", "target", "deadline", "priority")


def _now_iso() -> str:
    """Текущее время в ISO-формате (UTC)."""
    return datetime.now(UTC).isoformat()


async def add_goal(
    session: AsyncSession,
    telegram_id: int,
    name: str,
    target: int,
    deadline: str | None,
    priority: int,
) -> Goal:
    """Добавляет цель и возвращает её."""
    goal = Goal(
        telegram_id=telegram_id,
        name=name,
        target=target,
        deadline=deadline,
        priority=priority,
        created_at=_now_iso(),
    )
    session.add(goal)
    await session.commit()
    await session.refresh(goal)
    return goal


async def get_goals(session: AsyncSession, telegram_id: int) -> list[Goal]:
    """Возвращает все цели пользователя по порядку добавления."""
    result = await session.execute(
        select(Goal).where(Goal.telegram_id == telegram_id).order_by(Goal.id)
    )
    return list(result.scalars().all())


async def get_goal(session: AsyncSession, telegram_id: int, goal_id: int) -> Goal | None:
    """Возвращает цель по id или None."""
    result = await session.execute(
        select(Goal).where(Goal.telegram_id == telegram_id, Goal.id == goal_id)
    )
    return result.scalar_one_or_none()


async def update_goal(
    session: AsyncSession,
    telegram_id: int,
    goal_id: int,
    **fields: object,
) -> Goal | None:
    """Обновляет разрешённые поля цели. Возвращает цель или None."""
    payload = {key: value for key, value in fields.items() if key in ALLOWED_FIELDS}
    if not payload:
        return await get_goal(session, telegram_id, goal_id)
    result = await session.execute(
        update(Goal)
        .where(Goal.telegram_id == telegram_id, Goal.id == goal_id)
        .values(**payload)
    )
    await session.commit()
    if result.rowcount == 0:
        return None
    return await get_goal(session, telegram_id, goal_id)


async def delete_goal(session: AsyncSession, telegram_id: int, goal_id: int) -> bool:
    """Удаляет цель и её связи. Деньги из связей снова становятся свободными.

    Возвращает True, если цель была найдена.
    """
    goal = await get_goal(session, telegram_id, goal_id)
    if goal is None:
        return False
    await session.execute(delete(Allocation).where(Allocation.goal_id == goal_id))
    await session.execute(delete(Goal).where(Goal.id == goal_id))
    await session.commit()
    return True


async def get_goal_progress(session: AsyncSession, goal_id: int) -> int:
    """Прогресс цели: сумма связей, закреплённых из копилки."""
    result = await session.execute(
        select(func.coalesce(func.sum(Allocation.amount), 0)).where(
            Allocation.goal_id == goal_id
        )
    )
    return int(result.scalar_one())