"""Операции с пользователями."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import User


async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    """Возвращает пользователя по Telegram ID или None."""
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_or_create(session: AsyncSession, telegram_id: int) -> User:
    """Возвращает пользователя, создавая его при первом обращении."""
    user = await get_by_telegram_id(session, telegram_id)
    if user is None:
        user = User(telegram_id=telegram_id)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def save_onboarding_profile(
    session: AsyncSession,
    user: User,
    *,
    income_type: str,
    income_dates: str | None = None,
    income: int | None = None,
) -> User:
    """Сохраняет профиль из онбординга и помечает его пройденным.

    Свободные деньги живут на карточном счёте (см. ``accounts_repo``).
    """
    user.income_type = income_type
    user.income_dates = income_dates
    user.income = income
    user.onboarding_completed = True
    await session.commit()
    await session.refresh(user)
    return user


async def skip_onboarding(session: AsyncSession, user: User) -> User:
    """Помечает онбординг пройденным без заполнения профиля."""
    user.onboarding_completed = True
    await session.commit()
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, telegram_id: int) -> None:
    """Удаляет пользователя и связанные данные.

    Счета, транзакции, долги, связи, личные цели и членство в семье.
    Если семья осталась без участников — удаляется вместе со своими целями.
    """
    from models import (
        Account,
        Allocation,
        Debt,
        Family,
        FamilyMember,
        Goal,
        Transaction,
    )
    from services import family_repo

    family = await family_repo.get_family(session, telegram_id)
    if family is not None:
        members = await family_repo.get_family_members(session, family.id)
        others = [m for m in members if m.telegram_id != telegram_id]
        if not others:
            goal_ids = select(Goal.id).where(Goal.family_id == family.id)
            await session.execute(
                delete(Allocation).where(Allocation.goal_id.in_(goal_ids))
            )
            await session.execute(delete(Goal).where(Goal.family_id == family.id))
            await session.execute(
                delete(Family).where(Family.id == family.id)
            )
    await session.execute(
        delete(FamilyMember).where(FamilyMember.telegram_id == telegram_id)
    )

    goal_ids = select(Goal.id).where(Goal.telegram_id == telegram_id)
    await session.execute(
        delete(Allocation).where(
            (Allocation.goal_id.in_(goal_ids))
            | (Allocation.telegram_id == telegram_id)
        )
    )
    await session.execute(
        delete(Transaction).where(Transaction.telegram_id == telegram_id)
    )
    await session.execute(delete(Debt).where(Debt.telegram_id == telegram_id))
    await session.execute(delete(Goal).where(Goal.telegram_id == telegram_id))
    await session.execute(delete(Account).where(Account.telegram_id == telegram_id))
    await session.execute(delete(User).where(User.telegram_id == telegram_id))
    await session.commit()
