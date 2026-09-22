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
    SAVINGS_ADD = "savings_add"


class CategoryType(StrEnum):
    """Тип категории (Фаза 6)."""

    EXPENSE = "expense"
    INCOME = "income"


class IncomeType(StrEnum):
    """Формат дохода: фиксированный или нерегулярный."""

    FIXED = "fixed"
    IRREGULAR = "irregular"


class DebtType(StrEnum):
    """Тип обязательного платежа (Фаза 3)."""

    LOAN = "loan"
    MORTGAGE = "mortgage"
    CREDIT_CARD = "credit_card"
    INSTALLMENT = "installment"
