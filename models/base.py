"""Базовый класс моделей и перечисления домена."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей."""


class AdviceStyle(StrEnum):
    """Стиль советов (Фаза 5)."""

    SOFT = "soft"
    HARD = "hard"


class TransactionType(StrEnum):
    """Тип финансовой операции."""

    INCOME = "income"
    EXPENSE = "expense"
    CORRECTION = "correction"


class IncomeType(StrEnum):
    """Формат дохода: фиксированный или нерегулярный."""

    FIXED = "fixed"
    IRREGULAR = "irregular"


class DebtKind(StrEnum):
    """Характер долга: постоянный платёж или разовый (Фаза 3)."""

    CONSTANT = "constant"
    ONCE = "once"


class DebtType(StrEnum):
    """Тип долга (Фаза 3)."""

    CREDIT = "credit"
    MORTGAGE = "mortgage"
    CARD = "card"
    INSTALLMENT = "installment"
