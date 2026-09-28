"""Модели долгов и их платежей (Фаза 7)."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, DebtType, PaymentStatus


class Debt(Base):
    """Долг пользователя."""

    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(64))
    # Тип заполнения: regular / short / one (см. DebtType).
    type: Mapped[str] = mapped_column(
        String(16), default=DebtType.REGULAR.value
    )
    # ISO-дата (UTC), например 2026-09-20T12:30:00+00:00
    created_at: Mapped[str] = mapped_column(String(40))


class DebtPayment(Base):
    """Платёж по долгу с датой, статусом и отметкой оплаты."""

    __tablename__ = "debt_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    debt_id: Mapped[int] = mapped_column(
        ForeignKey("debts.id", ondelete="CASCADE"), index=True
    )
    amount: Mapped[int] = mapped_column(Integer)
    # ISO-дата платежа (YYYY-MM-DD).
    due_date: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(
        String(16), default=PaymentStatus.PENDING.value
    )
    # ISO-дата (UTC) фактической оплаты, пока не оплачен — NULL.
    paid_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
