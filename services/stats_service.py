"""Логика вердикта «хватает / не хватает» по платежам (Фаза 5.1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from models import Debt


@dataclass(frozen=True)
class PaymentVerdict:
    """Вердикт по одному платежу внутри дня."""

    payment_date: date
    debt: Debt
    owner_name: str
    free: int
    shortfall: int


def build_payment_verdicts(
    payments: list[tuple[date, Debt, int, str]],
    balances: dict[int, int],
) -> list[list[PaymentVerdict]]:
    """Группирует платежи по дням и считает вердикт «хватает / не хватает».

    ``payments`` — список ``(дата, долг, owner_id, имя владельца)``,
    отсортированный по дате. ``balances`` — свободные деньги (баланс карты)
    владельца по его ``telegram_id``.

    Внутри одного дня платежи вычитаются последовательно по каждому
    владельцу (накопительно). Между днями остаток сбрасывается. Доход
    (``income``) не учитывается.
    """
    groups: list[list[PaymentVerdict]] = []
    current_date: date | None = None
    remaining: dict[int, int] = {}

    for payment_date, debt, owner_id, owner_name in payments:
        if payment_date != current_date:
            current_date = payment_date
            remaining = {}
            groups.append([])
        if owner_id not in remaining:
            remaining[owner_id] = balances.get(owner_id, 0)
        free = remaining[owner_id]
        shortfall = max(0, debt.amount - free)
        groups[-1].append(
            PaymentVerdict(
                payment_date=payment_date,
                debt=debt,
                owner_name=owner_name,
                free=free,
                shortfall=shortfall,
            )
        )
        remaining[owner_id] = free - debt.amount

    return groups
