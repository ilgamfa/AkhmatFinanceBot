"""Сквозной прогноз платежей с учётом дохода владельца (Фаза 9.1).

Оркестратор: собирает балансы карт и будущие поступления владельцев и
передаёт их в чистый расчёт ``stats_service.build_payment_verdicts``.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from services import accounts_repo, income_repo, stats_service, users_repo

# тип платежа: (дата, сумма, имя долга, owner_id, имя владельца)
Payment = tuple[date, int, str, int, str]


async def build_verdicts(
    session: AsyncSession,
    payments: list[Payment],
    today: date,
) -> list[list[stats_service.PaymentVerdict]]:
    """Вердикты по платежам с доходом владельца и сквозным балансом.

    Доход берётся только у владельца долга и только до даты самого позднего
    платежа. Владельцы без платежей в расчёт не попадают.
    """
    if not payments:
        return []

    until = max(item[0] for item in payments)
    owner_ids = sorted({item[3] for item in payments})

    balances: dict[int, int] = {}
    incomes: dict[int, list[tuple[date, int]]] = {}
    for owner_id in owner_ids:
        balances[owner_id] = await accounts_repo.get_balance(
            session, owner_id, "card"
        )
        user = await users_repo.get_by_telegram_id(session, owner_id)
        if user is not None:
            incomes[owner_id] = await income_repo.get_income_events(
                session, user, today, until
            )

    ordered = sorted(payments, key=lambda item: item[0])
    return stats_service.build_payment_verdicts(ordered, balances, incomes)
