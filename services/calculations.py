"""Расчёты Фазы 1: свободные деньги, ближайшее поступление, совет."""

from __future__ import annotations

import calendar
import json
from collections.abc import Iterable
from datetime import date
from typing import Any

from utils.money import format_amount


def parse_income_dates(raw: str | None) -> list[tuple[int, int]]:
    """Разбирает JSON ``income_dates`` в список пар (день, сумма)."""
    if not raw:
        return []
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    result: list[tuple[int, int]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        day, amount = item.get("day"), item.get("amount")
        if isinstance(day, int) and isinstance(amount, int):
            result.append((day, amount))
    return result


def dump_income_dates(entries: Iterable[tuple[int, int]]) -> str:
    """Сериализует пары (день, сумма) в JSON-строку."""
    return json.dumps([{"day": day, "amount": amount} for day, amount in entries])


def _clamp_day(year: int, month: int, day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def days_until_day_of_month(today: date, day: int) -> int:
    """Число дней от ``today`` до ближайшего числа ``day`` числа месяца.

    Возвращает 0, если сегодня уже этот день. Для 29–31 берётся
    последний день месяца, если в месяце меньше дней.
    """
    if not 1 <= day <= 31:
        raise ValueError("День месяца должен быть от 1 до 31.")

    candidate = _clamp_day(today.year, today.month, day)
    if candidate < today:
        if today.month == 12:
            year, month = today.year + 1, 1
        else:
            year, month = today.year, today.month + 1
        candidate = _clamp_day(year, month, day)
    return (candidate - today).days


def days_until_next_income(
    entries: Iterable[tuple[int, int]], today: date
) -> int | None:
    """Минимальное число дней до ближайшего поступления или None."""
    days = [days_until_day_of_month(today, day) for day, _ in entries]
    return min(days) if days else None


def build_advice(
    free_money: int, days_to_income: int | None, income_type: str | None
) -> str:
    """Строит короткий совет для главного экрана."""
    if free_money == 0 and income_type is None:
        return (
            "Пока не знаю твой доход. Пройди онбординг: /start."
        )
    if free_money < 0:
        return "Расходы превышают деньги на счетах. Крупные покупки лучше отложить."
    if income_type == "irregular":
        return (
            f"Свободно {format_amount(free_money)}. Доход нерегулярный — "
            "держи запас на месяц."
        )
    if days_to_income == 0:
        return "Сегодня день поступления — можно сверить план на месяц."
    if days_to_income is not None:
        return (
            f"До ближайшего поступления {days_to_income} дн. "
            f"Свободно {format_amount(free_money)} — планируй траты с запасом."
        )
    return f"Свободно {format_amount(free_money)}. Траты под контролем."
