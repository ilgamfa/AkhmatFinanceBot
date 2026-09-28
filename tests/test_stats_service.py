"""Тесты вердикта «хватает / не хватает» (чистая логика, Фаза 5.1)."""

from __future__ import annotations

from datetime import date

from services.stats_service import build_payment_verdicts

DAY = date(2026, 9, 25)
NEXT_DAY = date(2026, 9, 26)


def test_verdict_enough() -> None:
    groups = build_payment_verdicts(
        [(DAY, 46000, "Кредит", 1, "Ильгам")], {1: 50000}
    )
    assert len(groups) == 1
    verdict = groups[0][0]
    assert verdict.free == 50000
    assert verdict.shortfall == 0


def test_verdict_short() -> None:
    groups = build_payment_verdicts(
        [(DAY, 61000, "Ипотека", 1, "Жена")], {1: 30000}
    )
    verdict = groups[0][0]
    assert verdict.free == 30000
    assert verdict.shortfall == 31000


def test_verdict_cumulative_same_day() -> None:
    """Платежи в один день вычитаются последовательно."""
    payments = [
        (DAY, 30000, "Кредит", 1, "Ильгам"),
        (DAY, 30000, "Ипотека", 1, "Ильгам"),
    ]
    groups = build_payment_verdicts(payments, {1: 50000})
    first, second = groups[0]
    assert (first.free, first.shortfall) == (50000, 0)
    assert (second.free, second.shortfall) == (20000, 10000)


def test_verdict_not_cumulative_between_days() -> None:
    """Между днями остаток сбрасывается."""
    payments = [
        (DAY, 40000, "Кредит", 1, "Ильгам"),
        (NEXT_DAY, 40000, "Ипотека", 1, "Ильгам"),
    ]
    groups = build_payment_verdicts(payments, {1: 50000})
    assert len(groups) == 2
    assert groups[0][0].free == 50000
    assert groups[0][0].shortfall == 0
    assert groups[1][0].free == 50000
    assert groups[1][0].shortfall == 0


def test_verdict_negative_balance() -> None:
    groups = build_payment_verdicts(
        [(DAY, 46000, "Кредит", 1, "Ильгам")], {1: -5000}
    )
    verdict = groups[0][0]
    assert verdict.free == -5000
    assert verdict.shortfall == 51000


def test_verdict_owners_are_independent() -> None:
    """У каждого владельца свой остаток внутри дня."""
    payments = [
        (DAY, 40000, "Кредит", 1, "Ильгам"),
        (DAY, 40000, "Ипотека", 2, "Жена"),
    ]
    groups = build_payment_verdicts(payments, {1: 50000, 2: 30000})
    first, second = groups[0]
    assert (first.free, first.shortfall) == (50000, 0)
    assert (second.free, second.shortfall) == (30000, 10000)


def test_verdict_empty() -> None:
    assert build_payment_verdicts([], {}) == []
