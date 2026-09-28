"""Операции с долгами и их платежами (Фаза 7)."""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Debt, DebtPayment
from models.base import DebtType, PaymentStatus


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


def monthly_dates(first_date: date, months: int) -> list[date]:
    """Даты ``months`` ежемесячных платежей начиная с ``first_date``.

    День месяца сохраняется; если в месяце меньше дней — берётся последний.
    """
    result: list[date] = []
    for offset in range(months):
        month_index = first_date.month - 1 + offset
        year = first_date.year + month_index // 12
        month = month_index % 12 + 1
        result.append(_clamp_day(year, month, first_date.day))
    return result


# --- долги -------------------------------------------------------------------


async def create_debt(
    session: AsyncSession,
    telegram_id: int,
    name: str,
    debt_type: str = DebtType.REGULAR.value,
) -> Debt:
    """Создаёт долг указанного типа и возвращает его."""
    debt = Debt(
        telegram_id=telegram_id,
        name=name,
        type=debt_type,
        created_at=_now_iso(),
    )
    session.add(debt)
    await session.commit()
    await session.refresh(debt)
    return debt


async def get_debts(session: AsyncSession, telegram_id: int) -> list[Debt]:
    """Возвращает долги пользователя по порядку добавления."""
    result = await session.execute(
        select(Debt).where(Debt.telegram_id == telegram_id).order_by(Debt.id)
    )
    return list(result.scalars().all())


async def get_debt(
    session: AsyncSession, telegram_id: int, debt_id: int
) -> Debt | None:
    """Возвращает долг по id или None."""
    result = await session.execute(
        select(Debt).where(Debt.telegram_id == telegram_id, Debt.id == debt_id)
    )
    return result.scalar_one_or_none()


async def rename_debt(session: AsyncSession, debt_id: int, name: str) -> Debt | None:
    """Переименовывает долг. Возвращает долг или None."""
    result = await session.execute(
        update(Debt).where(Debt.id == debt_id).values(name=name)
    )
    await session.commit()
    if result.rowcount == 0:
        return None
    return await session.get(Debt, debt_id)


async def delete_debt(session: AsyncSession, debt_id: int) -> bool:
    """Удаляет долг вместе с его платежами. True, если долг был найден."""
    await session.execute(delete(DebtPayment).where(DebtPayment.debt_id == debt_id))
    result = await session.execute(delete(Debt).where(Debt.id == debt_id))
    await session.commit()
    return result.rowcount > 0


async def update_debt_schedule(
    session: AsyncSession,
    debt_id: int,
    amount: int,
    day: int,
    months: int = 12,
) -> list[DebtPayment]:
    """Пересобирает платежи регулярного долга: новое число месяца и сумма.

    Старые платежи удаляются, вместо них создаётся ``months`` новых
    начиная с ближайшего ``day`` числа.
    """
    await session.execute(delete(DebtPayment).where(DebtPayment.debt_id == debt_id))
    first = next_payment_date(day, datetime.now(UTC).date())
    created: list[DebtPayment] = []
    for due_date in monthly_dates(first, months):
        created.append(await add_payment(session, debt_id, amount, due_date))
    return created


# --- платежи -----------------------------------------------------------------


async def add_payment(
    session: AsyncSession, debt_id: int, amount: int, due_date: date
) -> DebtPayment:
    """Добавляет платёж к долгу и возвращает его."""
    payment = DebtPayment(
        debt_id=debt_id,
        amount=amount,
        due_date=due_date.isoformat(),
        status=PaymentStatus.PENDING.value,
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)
    return payment


async def get_payments(session: AsyncSession, debt_id: int) -> list[DebtPayment]:
    """Возвращает платежи долга по возрастанию даты."""
    result = await session.execute(
        select(DebtPayment)
        .where(DebtPayment.debt_id == debt_id)
        .order_by(DebtPayment.due_date, DebtPayment.id)
    )
    return list(result.scalars().all())


async def get_payment(session: AsyncSession, payment_id: int) -> DebtPayment | None:
    """Возвращает платёж по id или None."""
    return await session.get(DebtPayment, payment_id)


async def update_payment(
    session: AsyncSession,
    payment_id: int,
    *,
    amount: int | None = None,
    due_date: date | None = None,
) -> DebtPayment | None:
    """Обновляет сумму и/или дату платежа. Возвращает платёж или None."""
    payload: dict[str, object] = {}
    if amount is not None:
        payload["amount"] = amount
    if due_date is not None:
        payload["due_date"] = due_date.isoformat()
    if payload:
        await session.execute(
            update(DebtPayment).where(DebtPayment.id == payment_id).values(**payload)
        )
        await session.commit()
    return await session.get(DebtPayment, payment_id)


async def mark_paid(session: AsyncSession, payment_id: int) -> DebtPayment | None:
    """Помечает платёж оплаченным. Возвращает платёж или None."""
    payment = await session.get(DebtPayment, payment_id)
    if payment is None:
        return None
    payment.status = PaymentStatus.PAID.value
    payment.paid_at = _now_iso()
    await session.commit()
    await session.refresh(payment)
    return payment


# --- выборки для /stats и /forecast ------------------------------------------


async def get_pending_payments(
    session: AsyncSession,
    telegram_id: int,
    from_date: date,
    to_date: date,
) -> list[tuple[DebtPayment, Debt]]:
    """Неоплаченные платежи пользователя с ``due_date`` в ``from_date..to_date``.

    Возвращает пары ``(платёж, долг)`` по возрастанию даты.
    """
    stmt = (
        select(DebtPayment, Debt)
        .join(Debt, DebtPayment.debt_id == Debt.id)
        .where(
            Debt.telegram_id == telegram_id,
            DebtPayment.status == PaymentStatus.PENDING.value,
            DebtPayment.due_date >= from_date.isoformat(),
            DebtPayment.due_date <= to_date.isoformat(),
        )
        .order_by(DebtPayment.due_date, DebtPayment.id)
    )
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def get_paid_payments(
    session: AsyncSession,
    telegram_id: int,
    month: date,
    today: date | None = None,
) -> list[tuple[DebtPayment, Debt]]:
    """Платежи месяца ``month`` с уже прошедшей датой (``due_date < today``).

    Статус платежа не учитывается: прошедший по дате платёж считается
    выплаченным. Возвращает пары ``(платёж, долг)`` по возрастанию даты.
    """
    today = today or datetime.now(UTC).date()
    first = date(month.year, month.month, 1)
    stmt = (
        select(DebtPayment, Debt)
        .join(Debt, DebtPayment.debt_id == Debt.id)
        .where(
            Debt.telegram_id == telegram_id,
            DebtPayment.due_date >= first.isoformat(),
            DebtPayment.due_date < today.isoformat(),
        )
        .order_by(DebtPayment.due_date, DebtPayment.id)
    )
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]
