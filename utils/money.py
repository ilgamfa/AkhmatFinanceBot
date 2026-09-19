"""Парсинг и форматирование денежных сумм (целые рубли)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_SPACE_CHARS = (" ", "\u00a0", "\u202f", "\t")
_RUBLE_SUFFIXES = ("руб.", "руб", "₽", "р.", "р")
_THOUSAND_SUFFIXES = ("к", "k")
_DASH_CHARS = ("−", "–", "—")


def parse_amount(text: str | None) -> int:
    """Преобразует ввод пользователя в целое число рублей.

    Понимает «12 000», «12000 ₽», «12,5к» (тысячи). Округляет до рубля.

    Raises:
        ValueError: если строку не удалось распознать или сумма отрицательная.
    """
    if text is None:
        raise ValueError("Пустая сумма.")
    cleaned = text.strip().lower()
    for char in _SPACE_CHARS:
        cleaned = cleaned.replace(char, "")
    for char in _DASH_CHARS:
        cleaned = cleaned.replace(char, "-")
    for suffix in _RUBLE_SUFFIXES:
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    cleaned = cleaned.replace(",", ".")
    if not cleaned:
        raise ValueError("Пустая сумма.")

    multiplier = Decimal(1)
    if cleaned.endswith(_THOUSAND_SUFFIXES):
        multiplier = Decimal(1000)
        cleaned = cleaned[:-1]

    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(
            f"Не понял сумму «{text.strip()}». Введи число, например 50 000."
        ) from exc
    if not value.is_finite():
        raise ValueError("Сумма должна быть обычным числом.")
    if value < 0:
        raise ValueError("Сумма не может быть отрицательной.")

    rubles = (value * multiplier).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(rubles)


def parse_amount_unsigned(text: str | None) -> int:
    """Как parse_amount, но допускает ведущий минус и возвращает модуль.

    Нужно для команд, где знак зашит в саму команду (/minus).
    """
    if text is None:
        raise ValueError("Пустая сумма.")
    cleaned = text.strip()
    for char in _DASH_CHARS:
        cleaned = cleaned.replace(char, "-")
    if cleaned.startswith("-"):
        cleaned = cleaned[1:]
    return parse_amount(cleaned)


def format_amount(rubles: int) -> str:
    """Форматирует сумму в вид «12 000 ₽»."""
    return f"{rubles:,}".replace(",", " ") + " ₽"


def format_rubles(rubles: int) -> str:
    """Форматирует сумму в вид «12 000» без обозначения валюты."""
    return f"{rubles:,}".replace(",", " ")


def parse_day_and_amount(text: str | None) -> tuple[int, int]:
    """Разбирает строку вида «10, 50000» в пару (день месяца, сумма).

    Raises:
        ValueError: если формат неверный, день вне 1–31 или сумма не распознана.
    """
    if text is None or not text.strip():
        raise ValueError("Пустой ввод.")
    parts = text.split(",")
    if len(parts) != 2:
        raise ValueError(
            f"Не понял «{text.strip()}». Напиши дату и сумму через запятую, "
            "например: 10, 50000."
        )

    day_part, amount_part = parts[0].strip(), parts[1].strip()
    if not day_part.isdigit():
        raise ValueError("Дата должна быть числом от 1 до 31. Например: 10, 50000.")
    day = int(day_part)
    if not 1 <= day <= 31:
        raise ValueError("Дата должна быть числом от 1 до 31. Например: 10, 50000.")

    try:
        amount = parse_amount(amount_part)
    except ValueError as exc:
        raise ValueError(
            f"Не понял сумму «{amount_part}». Напиши дату и сумму через запятую, "
            "например: 10, 50000."
        ) from exc
    return day, amount

