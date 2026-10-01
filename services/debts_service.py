"""Обслуживание графика долгов для экранов (Фаза 9.1).

Ленивая нормализация: прошедшие платежи считаются оплаченными, а
«бесконечные» регулярные долги получают новый год платежей. Здесь же —
правило видимости долгов в списке ``/debts``.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from models import Debt, DebtPayment
from models.base import DebtType, PaymentStatus
from services import debts_repo


async def normalize_debts(
    session: AsyncSession, telegram_id: int, today: date
) -> None:
    """Приводит платежи пользователя к текущей дате.

    Прошедшие по дате платежи помечаются оплаченными, а регулярные долги без
    pending-платежей продлеваются на следующий год.
    """
    await debts_repo.close_overdue_payments(session, telegram_id, today)
    await debts_repo.extend_finished_regular(session, telegram_id, today)


async def list_visible_debts(
    session: AsyncSession, telegram_id: int, today: date
) -> list[tuple[Debt, list[DebtPayment]]]:
    """Долги для списка ``/debts`` вместе с их платежами.

    Регулярный долг виден всегда, пока не удалён. Краткосрочный и разовый
    исчезают, когда у них не осталось неоплаченных платежей.
    """
    visible: list[tuple[Debt, list[DebtPayment]]] = []
    for debt in await debts_repo.get_debts(session, telegram_id):
        payments = await debts_repo.get_payments(session, debt.id)
        if debt.type != DebtType.REGULAR.value and not any(
            payment.status == PaymentStatus.PENDING.value for payment in payments
        ):
            continue
        visible.append((debt, payments))
    return visible
