"""ORM-модели проекта.

Импорт пакета ``models`` регистрирует все таблицы в ``Base.metadata``.
"""

from __future__ import annotations

from models.base import (
    AdviceStyle,
    Base,
    DebtKind,
    DebtType,
    IncomeType,
    TransactionType,
)
from models.debt import Debt
from models.goal import Goal
from models.transaction import Transaction
from models.user import User

__all__ = [
    "AdviceStyle",
    "Base",
    "Debt",
    "DebtKind",
    "DebtType",
    "Goal",
    "IncomeType",
    "Transaction",
    "TransactionType",
    "User",
]
