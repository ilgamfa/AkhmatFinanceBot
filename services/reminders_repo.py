"""Операции с настройками напоминаний (Фаза 8)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import User
from services import users_repo

DEFAULT_EVENING_TIME = "21:00"
DEFAULT_PAYMENT_TIME = "10:00"
DEFAULT_PAYMENT_DAYS_BEFORE = 1
MAX_PAYMENT_DAYS_BEFORE = 30

_TIME_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")

_FIELDS = frozenset(
    {
        "reminder_evening_enabled",
        "reminder_evening_time",
        "reminder_payment_enabled",
        "reminder_payment_time",
        "reminder_payment_days_before",
    }
)
_TIME_FIELDS = frozenset({"reminder_evening_time", "reminder_payment_time"})
_BOOL_FIELDS = frozenset(
    {"reminder_evening_enabled", "reminder_payment_enabled"}
)


@dataclass(frozen=True)
class ReminderSettings:
    """Настройки напоминаний пользователя (значения по умолчанию — включено)."""

    evening_enabled: bool = True
    evening_time: str = DEFAULT_EVENING_TIME
    payment_enabled: bool = True
    payment_time: str = DEFAULT_PAYMENT_TIME
    payment_days_before: int = DEFAULT_PAYMENT_DAYS_BEFORE


def normalize_time(raw: str | None) -> str:
    """Приводит «9:00» / «09:00» к «09:00».

    Raises:
        ValueError: если формат не ``HH:MM`` в диапазоне 00:00–23:59.
    """
    cleaned = (raw or "").strip()
    if not _TIME_RE.match(cleaned):
        raise ValueError("Не понял время. Напиши в формате 21:00.")
    hours, minutes = cleaned.split(":")
    return f"{int(hours):02d}:{minutes}"


def normalize_days(raw: str | None) -> int:
    """Разбирает число дней до платежа (0–30).

    Raises:
        ValueError: если это не целое число в допустимом диапазоне.
    """
    cleaned = (raw or "").strip()
    if not cleaned.isdigit():
        raise ValueError("Не понял число дней. Напиши целое число, например 1.")
    value = int(cleaned)
    if not 0 <= value <= MAX_PAYMENT_DAYS_BEFORE:
        raise ValueError("Число дней должно быть от 0 до 30.")
    return value


def _to_settings(user: User) -> ReminderSettings:
    """Переносит настройки из ORM-пользователя в датакласс."""
    return ReminderSettings(
        evening_enabled=user.reminder_evening_enabled,
        evening_time=user.reminder_evening_time,
        payment_enabled=user.reminder_payment_enabled,
        payment_time=user.reminder_payment_time,
        payment_days_before=user.reminder_payment_days_before,
    )


async def get_reminder_settings(
    session: AsyncSession, telegram_id: int
) -> ReminderSettings:
    """Настройки напоминаний или значения по умолчанию для нового пользователя."""
    user = await users_repo.get_by_telegram_id(session, telegram_id)
    if user is None:
        return ReminderSettings()
    return _to_settings(user)


def _normalize_field(field: str, value: object) -> object:
    """Проверяет и приводит значение настройки к нужному типу."""
    if field in _TIME_FIELDS:
        return normalize_time(str(value))
    if field == "reminder_payment_days_before":
        if isinstance(value, int) and not isinstance(value, bool):
            if not 0 <= value <= MAX_PAYMENT_DAYS_BEFORE:
                raise ValueError("Число дней должно быть от 0 до 30.")
            return value
        return normalize_days(str(value))
    if field in _BOOL_FIELDS:
        return bool(value)
    raise ValueError(f"Неизвестная настройка: {field}")


async def update_reminder_settings(
    session: AsyncSession, telegram_id: int, **fields: object
) -> User:
    """Обновляет указанные настройки и возвращает пользователя.

    Raises:
        ValueError: если передано неизвестное поле или неверное значение.
    """
    unknown = set(fields) - _FIELDS
    if unknown:
        raise ValueError(f"Неизвестные настройки: {', '.join(sorted(unknown))}")

    user = await users_repo.get_or_create(session, telegram_id)
    for field, value in fields.items():
        setattr(user, field, _normalize_field(field, value))
    await session.commit()
    await session.refresh(user)
    return user


async def get_users_for_evening_reminder(session: AsyncSession) -> list[User]:
    """Пользователи с включённым вечерним напоминанием и пройденным онбордингом."""
    result = await session.execute(
        select(User).where(
            User.reminder_evening_enabled.is_(True),
            User.onboarding_completed.is_(True),
        )
    )
    return list(result.scalars().all())


async def get_users_for_payment_reminder(session: AsyncSession) -> list[User]:
    """Пользователи с включённым платёжным напоминанием и онбордингом."""
    result = await session.execute(
        select(User).where(
            User.reminder_payment_enabled.is_(True),
            User.onboarding_completed.is_(True),
        )
    )
    return list(result.scalars().all())


async def mark_evening_sent(
    session: AsyncSession, user: User, day: date
) -> None:
    """Запоминает дату (MSK) отправки вечернего напоминания."""
    user.reminder_evening_last_sent = day
    await session.commit()


async def mark_payment_sent(
    session: AsyncSession, user: User, day: date
) -> None:
    """Запоминает дату (MSK) отправки платёжного напоминания."""
    user.reminder_payment_last_sent = day
    await session.commit()
