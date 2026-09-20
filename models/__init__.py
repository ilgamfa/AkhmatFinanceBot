"""ORM-модели проекта.

Импорт пакета ``models`` регистрирует все таблицы в ``Base.metadata``.
"""

from __future__ import annotations

from models.allocations import Allocation
from models.account import CARD, SAVINGS, ACCOUNT_TYPES, Account
from models.base import (
    AdviceStyle,
    Base,
    DebtType,
    IncomeType,
    TransactionType,
)
from models.debt import Debt
from models.family import Family, FamilyMember
from models.goal import Goal
from models.transaction import Transaction
from models.user import User

__all__ = [
    "ACCOUNT_TYPES",
    "CARD",
    "SAVINGS",
    "Account",
    "AdviceStyle",
    "Allocation",
    "Base",
    "Debt",
    "DebtType",
    "Family",
    "FamilyMember",
    "Goal",
    "IncomeType",
    "Transaction",
    "TransactionType",
    "User",
]