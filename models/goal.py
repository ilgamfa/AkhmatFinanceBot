"""Модель финансовой цели (Фаза 4)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Goal(Base):
    """Цель пользователя: название, сумма, накоплено, срок, приоритет."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(64))
    # Целевая сумма, целые рубли.
    target: Mapped[int] = mapped_column(Integer)
    # Отложено, целые рубли.
    saved: Mapped[int] = mapped_column(Integer, default=0)
    # ISO-дата (например 2027-12-01) или NULL.
    deadline: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Приоритет: 1 — высокий, 2 — средний, 3 — низкий.
    priority: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))