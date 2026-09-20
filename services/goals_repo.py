"""Операции с целями (Фазы 4–5).

Цель принадлежит семье (``family_id``) или одиночному пользователю
(``telegram_id``). Скоуп доступа определяется по семье пользователя.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Allocation, Goal
from services import family_repo

ALLOWED_FIELDS = ("name", "target", "deadline", "priority")


def _now_iso() -> str:
    """Текущее время в ISO-формате (UTC)."""
    return datetime.now(UTC).isoformat()


def _scope(family_id: int | None, telegram_id: int):  # type: ignore[no-untyped-def]
    """Условие доступа: семейные цели либо личные цели пользователя."""
    if family_id is not None:
        return Goal.family_id == family_id
    return (Goal.telegram_id == telegram_id) & Goal.family_id.is_(None)


async def add_goal(
    session: AsyncSession,
    telegram_id: int,
    name: str,
    target: int,
    deadline: str | None,
    priority: int,
) -> Goal:
    """Добавляет цель в скоуп пользователя и возвращает её."""
    family = await family_repo.get_family(session, telegram_id)
    goal = Goal(
        telegram_id=telegram_id,
        family_id=family.id if family is not None else None,
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
    """Возвращает видимые цели пользователя по порядку добавления."""
    family = await family_repo.get_family(session, telegram_id)
    scope = _scope(family.id if family is not None else None, telegram_id)
    result = await session.execute(select(Goal).where(scope).order_by(Goal.id))
    return list(result.scalars().all())


async def get_goal(session: AsyncSession, telegram_id: int, goal_id: int) -> Goal | None:
    """Возвращает цель из скоупа пользователя или None."""
    family = await family_repo.get_family(session, telegram_id)
    scope = _scope(family.id if family is not None else None, telegram_id)
    result = await session.execute(select(Goal).where(Goal.id == goal_id, scope))
    return result.scalar_one_or_none()


async def update_goal(
    session: AsyncSession,
    telegram_id: int,
    goal_id: int,
    **fields: object,
) -> Goal | None:
    """Обновляет разрешённые поля цели. Возвращает цель или None."""
    goal = await get_goal(session, telegram_id, goal_id)
    if goal is None:
        return None
    payload = {key: value for key, value in fields.items() if key in ALLOWED_FIELDS}
    if not payload:
        return goal
    await session.execute(
        update(Goal).where(Goal.id == goal_id).values(**payload)
    )
    await session.commit()
    return await session.get(Goal, goal_id)


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
    """Прогресс цели: сумма связей с обоих счетов копилок."""
    result = await session.execute(
        select(func.coalesce(func.sum(Allocation.amount), 0)).where(
            Allocation.goal_id == goal_id
        )
    )
    return int(result.scalar_one())


async def get_progress_by_goals(
    session: AsyncSession, goal_ids: list[int]
) -> dict[int, int]:
    """Прогресс по списку целей: {goal_id: сумма связей}."""
    if not goal_ids:
        return {}
    result = await session.execute(
        select(Goal.id, func.coalesce(func.sum(Allocation.amount), 0))
        .outerjoin(Allocation, Allocation.goal_id == Goal.id)
        .where(Goal.id.in_(goal_ids))
        .group_by(Goal.id)
    )
    return {goal_id: int(total) for goal_id, total in result.all()}


def scope_condition(family_id: int | None, telegram_id: int):  # type: ignore[no-untyped-def]
    """Публичный доступ к условию скоупа (для выборок вне репозитория)."""
    return _scope(family_id, telegram_id)


__all__ = [
    "ALLOWED_FIELDS",
    "add_goal",
    "delete_goal",
    "get_goal",
    "get_goal_progress",
    "get_goals",
    "get_progress_by_goals",
    "scope_condition",
    "update_goal",
]
