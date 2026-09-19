"""Операции с пользователями."""

from __future__ import annotations

from sqlalchemy import select
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
    free_money: int,
    income_type: str,
    income_dates: str | None = None,
    income: int | None = None,
) -> User:
    """Сохраняет профиль из онбординга и помечает его пройденным."""
    user.free_money = free_money
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
