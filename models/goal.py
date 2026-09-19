"""Модель цели. Логика — Фаза 4, таблица создаётся заранее."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Goal(Base):
    """Финансовая цель пользователя."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    target_amount: Mapped[int] = mapped_column(BigInteger)
    saved_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
