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
    PaymentStatus,
    TransactionType,
)
from models.category import Category
from models.debt import Debt, DebtPayment
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
    "DebtPayment",
    "DebtType",
    "Family",
    "FamilyMember",
    "Goal",
    "IncomeType",
    "PaymentStatus",
    "Transaction",
    "TransactionType",
    "User",
]
