"""Тесты вердикта «хватает / не хватает» (чистая логика, Фаза 5.1)."""

from __future__ import annotations

from datetime import date

from models import Debt
from services.stats_service import build_payment_verdicts

DAY = date(2026, 9, 25)
NEXT_DAY = date(2026, 9, 26)


def _debt(
    name: str = "Кредит", amount: int = 46000, owner: int = 1
) -> Debt:
    return Debt(
        telegram_id=owner,
        name=name,
        type="loan",
        amount=amount,
        payment_day=25,
        created_at="2026-09-01T00:00:00+00:00",
    )


def test_verdict_enough() -> None:
    groups = build_payment_verdicts(
        [(DAY, _debt(amount=46000), 1, "Ильгам")], {1: 50000}
    )
    assert len(groups) == 1
    verdict = groups[0][0]
    assert verdict.free == 50000
    assert verdict.shortfall == 0


def test_verdict_short() -> None:
    groups = build_payment_verdicts(
        [(DAY, _debt(amount=61000), 1, "Жена")], {1: 30000}
    )
    verdict = groups[0][0]
    assert verdict.free == 30000
    assert verdict.shortfall == 31000


def test_verdict_cumulative_same_day() -> None:
    """Платежи в один день вычитаются последовательно."""
    payments = [
        (DAY, _debt("Кредит", 30000), 1, "Ильгам"),
        (DAY, _debt("Ипотека", 30000), 1, "Ильгам"),
    ]
    groups = build_payment_verdicts(payments, {1: 50000})
    first, second = groups[0]
    assert (first.free, first.shortfall) == (50000, 0)
    assert (second.free, second.shortfall) == (20000, 10000)


def test_verdict_not_cumulative_between_days() -> None:
    """Между днями остаток сбрасывается."""
    payments = [
        (DAY, _debt("Кредит", 40000), 1, "Ильгам"),
        (NEXT_DAY, _debt("Ипотека", 40000), 1, "Ильгам"),
    ]
    groups = build_payment_verdicts(payments, {1: 50000})
    assert len(groups) == 2
    assert groups[0][0].free == 50000
    assert groups[0][0].shortfall == 0
    assert groups[1][0].free == 50000
    assert groups[1][0].shortfall == 0


def test_verdict_negative_balance() -> None:
    groups = build_payment_verdicts(
        [(DAY, _debt(amount=46000), 1, "Ильгам")], {1: -5000}
    )
    verdict = groups[0][0]
    assert verdict.free == -5000
    assert verdict.shortfall == 51000


def test_verdict_owners_are_independent() -> None:
    """У каждого владельца свой остаток внутри дня."""
    payments = [
        (DAY, _debt("Кредит", 40000, owner=1), 1, "Ильгам"),
        (DAY, _debt("Ипотека", 40000, owner=2), 2, "Жена"),
    ]
    groups = build_payment_verdicts(payments, {1: 50000, 2: 30000})
    first, second = groups[0]
    assert (first.free, first.shortfall) == (50000, 0)
    assert (second.free, second.shortfall) == (30000, 10000)


def test_verdict_empty() -> None:
    assert build_payment_verdicts([], {}) == []
