"""Модель долга. Логика — Фаза 3, таблица создаётся заранее."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, DebtKind, DebtType


class Debt(Base):
    """Кредит, ипотека, кредитка или рассрочка."""

    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), default=DebtKind.CONSTANT.value)
    debt_type: Mapped[str] = mapped_column(String(16), default=DebtType.CREDIT.value)
    amount: Mapped[int] = mapped_column(BigInteger)
    due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grace_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
