"""Модель обязательного платежа (Фаза 3)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, DebtType


class Debt(Base):
    """Кредит, ипотека, кредитка или рассрочка — ежемесячный платёж."""

    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(16), default=DebtType.LOAN.value)
    # Сумма ежемесячного платежа, целые рубли.
    amount: Mapped[int] = mapped_column(Integer)
    # День месяца платежа (1–31).
    payment_day: Mapped[int] = mapped_column(Integer)
    # ISO-дата (UTC), например 2026-09-20T12:30:00+00:00
    created_at: Mapped[str] = mapped_column(String(40))
