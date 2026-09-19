"""Операции с целями (Фаза 4)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Goal

ALLOWED_FIELDS = ("name", "target", "saved", "deadline", "priority")


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


async def update_goal_saved(
    session: AsyncSession, telegram_id: int, goal_id: int, amount: int
) -> Goal | None:
    """Обновляет накопленную сумму цели."""
    return await update_goal(session, telegram_id, goal_id, saved=amount)


async def delete_goal(session: AsyncSession, telegram_id: int, goal_id: int) -> bool:
    """Удаляет цель. Возвращает True, если цель была найдена."""
    result = await session.execute(
        delete(Goal).where(Goal.telegram_id == telegram_id, Goal.id == goal_id)
    )
    await session.commit()
    return result.rowcount > 0


async def delete_all_goals(session: AsyncSession, telegram_id: int) -> None:
    """Удаляет все цели пользователя (для /refresh)."""
    await session.execute(delete(Goal).where(Goal.telegram_id == telegram_id))
    await session.commit()