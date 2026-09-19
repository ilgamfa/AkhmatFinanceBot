"""Операции с обязательными платежами (Фаза 3)."""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Debt


def _now_iso() -> str:
    """Текущее время в ISO-формате (UTC)."""
    return datetime.now(UTC).isoformat()


def _clamp_day(year: int, month: int, day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def next_payment_date(payment_day: int, today: date) -> date:
    """Ближайшая дата платежа для дня месяца (текущая или следующая)."""
    candidate = _clamp_day(today.year, today.month, payment_day)
    if candidate < today:
        if today.month == 12:
            year, month = today.year + 1, 1
        else:
            year, month = today.year, today.month + 1
        candidate = _clamp_day(year, month, payment_day)
    return candidate


def payments_within(payment_day: int, today: date, days: int) -> list[date]:
    """Все даты платежа в горизонте ``days`` дней от ``today``."""
    result: list[date] = []
    limit = today + timedelta(days=days)
    candidate = next_payment_date(payment_day, today)
    while candidate <= limit:
        result.append(candidate)
        if candidate.month == 12:
            year, month = candidate.year + 1, 1
        else:
            year, month = candidate.year, candidate.month + 1
        candidate = _clamp_day(year, month, payment_day)
    return result


async def add_debt(
    session: AsyncSession,
    telegram_id: int,
    name: str,
    debt_type: str,
    amount: int,
    payment_day: int,
) -> Debt:
    """Добавляет обязательный платёж и возвращает его."""
    debt = Debt(
        telegram_id=telegram_id,
        name=name,
        type=debt_type,
        amount=amount,
        payment_day=payment_day,
        created_at=_now_iso(),
    )
    session.add(debt)
    await session.commit()
    await session.refresh(debt)
    return debt


async def get_debts(session: AsyncSession, telegram_id: int) -> list[Debt]:
    """Возвращает все долги пользователя по порядку добавления."""
    result = await session.execute(
        select(Debt).where(Debt.telegram_id == telegram_id).order_by(Debt.id)
    )
    return list(result.scalars().all())


async def get_debt(session: AsyncSession, telegram_id: int, debt_id: int) -> Debt | None:
    """Возвращает долг по id или None."""
    result = await session.execute(
        select(Debt).where(Debt.telegram_id == telegram_id, Debt.id == debt_id)
    )
    return result.scalar_one_or_none()


async def delete_debt(session: AsyncSession, telegram_id: int, debt_id: int) -> bool:
    """Удаляет долг. Возвращает True, если долг был найден."""
    result = await session.execute(
        delete(Debt).where(Debt.telegram_id == telegram_id, Debt.id == debt_id)
    )
    await session.commit()
    return result.rowcount > 0


DEBT_ALLOWED_FIELDS = ("name", "type", "amount", "payment_day")


async def update_debt(
    session: AsyncSession,
    telegram_id: int,
    debt_id: int,
    **fields: object,
) -> Debt | None:
    """Обновляет разрешённые поля долга. Возвращает долг или None."""
    payload = {key: value for key, value in fields.items() if key in DEBT_ALLOWED_FIELDS}
    if not payload:
        return await get_debt(session, telegram_id, debt_id)
    result = await session.execute(
        update(Debt)
        .where(Debt.telegram_id == telegram_id, Debt.id == debt_id)
        .values(**payload)
    )
    await session.commit()
    if result.rowcount == 0:
        return None
    return await get_debt(session, telegram_id, debt_id)


async def delete_all_debts(session: AsyncSession, telegram_id: int) -> None:
    """Удаляет все долги пользователя (для /refresh)."""
    await session.execute(delete(Debt).where(Debt.telegram_id == telegram_id))
    await session.commit()


async def get_upcoming_payments(
    session: AsyncSession,
    telegram_id: int,
    days: int = 30,
    today: date | None = None,
) -> list[tuple[date, Debt]]:
    """Платежи на ближайшие ``days`` дней: пары (дата, долг), по возрастанию даты."""
    today = today or datetime.now(UTC).date()
    debts = await get_debts(session, telegram_id)
    payments: list[tuple[date, Debt]] = []
    for debt in debts:
        for payment_date in payments_within(debt.payment_day, today, days):
            payments.append((payment_date, debt))
    payments.sort(key=lambda item: item[0])
    return payments
