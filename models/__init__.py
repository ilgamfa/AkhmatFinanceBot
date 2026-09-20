"""ORM-модели проекта.

Импорт пакета ``models`` регистрирует все таблицы в ``Base.metadata``.
"""

from __future__ import annotations

from models.allocations import Allocation
from models.base import (
    AdviceStyle,
    Base,
    DebtType,
    IncomeType,
    TransactionType,
)
from models.debt import Debt
from models.goal import Goal
from models.savings import Savings
from models.transaction import Transaction
from models.user import User

__all__ = [
    "AdviceStyle",
    "Allocation",
    "Base",
    "Debt",
    "DebtType",
    "Goal",
    "IncomeType",
    "Savings",
    "Transaction",
    "TransactionType",
    "User",
]