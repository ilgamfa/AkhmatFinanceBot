"""Тесты парсинга и форматирования денег."""

from __future__ import annotations

import pytest

from utils.money import (
    format_amount,
    parse_amount,
    parse_amount_unsigned,
    parse_day_and_amount,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("5000", 5000),
        ("50 000", 50000),
        ("50 000 ₽", 50000),
        ("1 500 000", 1500000),
        ("12,5к", 12500),
        ("12.5к", 12500),
        ("12000руб", 12000),
        ("0", 0),
        ("  1000  ", 1000),
        ("100\u00a0000", 100000),
    ],
)
def test_parse_amount_ok(text: str, expected: int) -> None:
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", "   ", None, "abc", "-100", "5..5"])
def test_parse_amount_errors(text: str | None) -> None:
    with pytest.raises(ValueError):
        parse_amount(text)


def test_format_amount() -> None:
    assert format_amount(12000) == "12 000 ₽"
    assert format_amount(0) == "0 ₽"
    assert format_amount(-2000) == "-2 000 ₽"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("5000", 5000),
        ("−1000", 1000),
        ("-1000", 1000),
        ("—25 000", 25000),
        ("50 000 ₽", 50000),
    ],
)
def test_parse_amount_unsigned(text: str, expected: int) -> None:
    assert parse_amount_unsigned(text) == expected


@pytest.mark.parametrize("text", ["", "abc", None, "-", "−"])
def test_parse_amount_unsigned_errors(text: str | None) -> None:
    with pytest.raises(ValueError):
        parse_amount_unsigned(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10, 50000", (10, 50000)),
        ("10, 50 000", (10, 50000)),
        ("25, 20000", (25, 20000)),
        ("1, 1000", (1, 1000)),
        ("31, 0", (31, 0)),
        ("10,12к", (10, 12000)),
    ],
)
def test_parse_day_and_amount_ok(text: str, expected: tuple[int, int]) -> None:
    assert parse_day_and_amount(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "10", "10,", ",50000", "0, 5000", "32, 5000", "abc, 5000", "10, abc", None],
)
def test_parse_day_and_amount_errors(text: str | None) -> None:
    with pytest.raises(ValueError):
        parse_day_and_amount(text)
