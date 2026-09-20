"""Модель финансовой операции (Фаза 2)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TransactionType


class Transaction(Base):
    """Трата, доход или корректировка баланса. Суммы — в целых рублях."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # Счёт операции (карта или копилка); NULL, если счёт неизвестен.
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    type: Mapped[str] = mapped_column(
        String(16), default=TransactionType.EXPENSE.value
    )
    # Для expense/income — положительная сумма, для correction — разница со знаком.
    amount: Mapped[int] = mapped_column(Integer)
    # ISO-дата (UTC), например 2026-09-20T12:30:00+00:00
    created_at: Mapped[str] = mapped_column(String(40))
