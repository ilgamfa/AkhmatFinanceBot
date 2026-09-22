"""ORM-модели проекта.

Импорт пакета ``models`` регистрирует все таблицы в ``Base.metadata``.
"""

from __future__ import annotations

from models.account import ACCOUNT_TYPES, CARD, SAVINGS, Account
from models.allocations import Allocation
from models.base import (
    AdviceStyle,
    Base,
    CategoryType,
    DebtType,
    IncomeType,
    TransactionType,
)
from models.category import Category
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
    "Category",
    "CategoryType",
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