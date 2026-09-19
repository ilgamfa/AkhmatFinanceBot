"""Расчёты Фазы 1: свободные деньги, ближайшее поступление, совет."""

from __future__ import annotations

import calendar
import json
import math
from collections.abc import Iterable
from datetime import date, datetime
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


def end_of_month(today: date) -> date:
    """Последний день текущего календарного месяца."""
    last_day = calendar.monthrange(today.year, today.month)[1]
    return date(today.year, today.month, last_day)


# --- Цели (Фаза 4) -----------------------------------------------------------


GOAL_EMOJI: dict[str, str] = {
    "машина": "🚗",
    "авто": "🚗",
    "подушка": "🛟",
    "квартира": "🏠",
    "отпуск": "✈️",
    "путешествие": "✈️",
    "телефон": "📱",
    "ремонт": "🔧",
}
DEFAULT_GOAL_EMOJI = "🎯"


def goal_emoji(name: str) -> str:
    """Эмодзи цели по названию (fallback — 🎯)."""
    return GOAL_EMOJI.get(name.strip().lower(), DEFAULT_GOAL_EMOJI)


def goal_progress_percent(saved: int, target: int) -> int:
    """Процент накопления цели (целое число)."""
    if target <= 0:
        return 0
    return round(saved * 100 / target)


def months_until_deadline(deadline_iso: str | None, today: date) -> int | None:
    """Календарные месяцы до срока (минимум 1) или None, если срока нет.

    Если срок прошёл — возвращается 1 (цель нужно закрыть как можно скорее).
    """
    if not deadline_iso:
        return None
    try:
        deadline_date = date.fromisoformat(deadline_iso)
    except ValueError:
        return None
    months = (
        (deadline_date.year - today.year) * 12 + (deadline_date.month - today.month)
    )
    # Если в текущем месяце срок уже прошёл по числу — месяц ещё не наступил.
    if deadline_date.day < today.day:
        months -= 1
    return max(1, months)


def monthly_goal_amount(
    saved: int,
    target: int,
    deadline_iso: str | None,
    today: date,
) -> int | None:
    """Сколько откладывать в месяц: ceil((target − saved) / месяцев). None без срока."""
    months = months_until_deadline(deadline_iso, today)
    if months is None:
        return None
    remaining = target - saved
    if remaining <= 0:
        return 0
    return math.ceil(remaining / months)


def parse_goal_deadline(text: str | None) -> str | None:
    """Разбирает ввод срока: «01.12.2027» → «2027-12-01», «skip»/«нет» → None.

    Raises:
        ValueError: если формат не распознан.
    """
    cleaned = (text or "").strip().lower()
    if cleaned in ("skip", "нет", "-"):
        return None
    try:
        parsed = datetime.strptime(cleaned, "%d.%m.%Y").date()
    except ValueError as exc:
        raise ValueError(
            "Не понял срок. Напиши дату в формате 01.12.2027 или skip."
        ) from exc
    return parsed.isoformat()


def format_goal_deadline(deadline_iso: str | None) -> str | None:
    """«2027-12-01» → «01.12.2027», пустой срок → None."""
    if not deadline_iso:
        return None
    try:
        parsed = date.fromisoformat(deadline_iso)
    except ValueError:
        return None
    return parsed.strftime("%d.%m.%Y")


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
