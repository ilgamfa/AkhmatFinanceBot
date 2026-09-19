"""Тесты расчётов Фазы 1."""

from __future__ import annotations

from datetime import date

import pytest

from services.calculations import (
    build_advice,
    days_until_day_of_month,
    days_until_next_income,
    dump_income_dates,
    parse_income_dates,
)


def test_income_dates_round_trip() -> None:
    entries = [(10, 50000), (25, 20000)]
    raw = dump_income_dates(entries)
    assert parse_income_dates(raw) == entries


def test_parse_income_dates_invalid() -> None:
    assert parse_income_dates(None) == []
    assert parse_income_dates("") == []
    assert parse_income_dates("not json") == []
    assert parse_income_dates('{"day": 1}') == []
    assert parse_income_dates('[{"day": "x", "amount": 1}]') == []


@pytest.mark.parametrize(
    ("today", "day", "expected"),
    [
        (date(2026, 9, 1), 5, 4),
        (date(2026, 9, 5), 5, 0),
        (date(2026, 9, 6), 5, 29),
        (date(2026, 1, 31), 31, 0),
        (date(2026, 2, 28), 31, 0),
        (date(2026, 2, 27), 31, 1),
        (date(2026, 12, 31), 1, 1),
    ],
)
def test_days_until_day_of_month(today: date, day: int, expected: int) -> None:
    assert days_until_day_of_month(today, day) == expected


@pytest.mark.parametrize("day", [0, 32, -1])
def test_days_until_invalid_day(day: int) -> None:
    with pytest.raises(ValueError):
        days_until_day_of_month(date(2026, 9, 1), day)


def test_days_until_next_income() -> None:
    today = date(2026, 9, 8)
    assert days_until_next_income([(10, 1), (25, 1)], today) == 2
    assert days_until_next_income([(1, 1), (25, 1)], today) == 17
    assert days_until_next_income([], today) is None


def test_build_advice_without_profile() -> None:
    assert "/start" in build_advice(0, None, None)


def test_build_advice_fixed() -> None:
    assert "До ближайшего поступления 5 дн." in build_advice(1000, 5, "fixed")
    assert "день поступления" in build_advice(1000, 0, "fixed")


def test_build_advice_irregular() -> None:
    advice = build_advice(5000, None, "irregular")
    assert "нерегулярный" in advice


def test_build_advice_negative() -> None:
    assert "отложить" in build_advice(-1000, 5, "fixed")
