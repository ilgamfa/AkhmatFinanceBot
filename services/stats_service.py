"""Логика вердикта «хватает / не хватает» по платежам (Фаза 5.1, 9.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class PaymentVerdict:
    """Вердикт по одному платежу внутри дня."""

    payment_date: date
    debt_name: str
    amount: int
    owner_name: str
    free: int
    shortfall: int
    # Доход владельца, учтённый при расчёте этого платежа (только фиксированный).
    income: int = 0
    income_events: tuple[tuple[date, int], ...] = field(default=())


def build_payment_verdicts(
    payments: list[tuple[date, int, str, int, str]],
    balances: dict[int, int],
    incomes: dict[int, list[tuple[date, int]]] | None = None,
) -> list[list[PaymentVerdict]]:
    """Группирует платежи по дням и считает вердикт «хватает / не хватает».

    ``payments`` — список ``(дата, сумма, имя долга, owner_id, имя владельца)``,
    отсортированный по дате. ``balances`` — свободные деньги (баланс карты)
    владельца по его ``telegram_id``. ``incomes`` — будущие поступления
    ``(дата, сумма)`` владельца, по возрастанию даты.

    Баланс ведётся сквозным: доход прибавляется раньше платежей своего дня,
    остаток переносится на следующие дни. Доход учитывается только у владельца
    долга и только до даты платежа включительно. Нерегулярный доход не
    передаётся — тогда вердикт считается по одному балансу.
    """
    incomes = incomes or {}
    groups: list[list[PaymentVerdict]] = []
    current_date: date | None = None
    running: dict[int, int] = {}
    pointers: dict[int, int] = {}

    for payment_date, amount, debt_name, owner_id, owner_name in payments:
        if payment_date != current_date:
            current_date = payment_date
            groups.append([])
        if owner_id not in running:
            running[owner_id] = balances.get(owner_id, 0)
        events = incomes.get(owner_id, [])
        pointer = pointers.get(owner_id, 0)
        applied: list[tuple[date, int]] = []
        while pointer < len(events) and events[pointer][0] <= payment_date:
            income_date, income_amount = events[pointer]
            running[owner_id] += income_amount
            applied.append((income_date, income_amount))
            pointer += 1
        pointers[owner_id] = pointer
        free = running[owner_id]
        shortfall = max(0, amount - free)
        groups[-1].append(
            PaymentVerdict(
                payment_date=payment_date,
                debt_name=debt_name,
                amount=amount,
                owner_name=owner_name,
                free=free,
                shortfall=shortfall,
                income=sum(item[1] for item in applied),
                income_events=tuple(applied),
            )
        )
        running[owner_id] = free - amount

    return groups
