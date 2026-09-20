"""Модель счёта (Фаза 5)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base

CARD = "card"
SAVINGS = "savings"
ACCOUNT_TYPES = (CARD, SAVINGS)


class Account(Base):
    """Счёт пользователя: одна карта и одна копилка.

    Баланс — в целых рублях. ``family_id`` заполняется, когда пользователь
    вступает в семью (или создаёт её).
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    family_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # "card" — свободные деньги, "savings" — копилка.
    type: Mapped[str] = mapped_column(String(16))
    balance: Mapped[int] = mapped_column(Integer, default=0)
    # ISO-дата (UTC)
    created_at: Mapped[str] = mapped_column(String(40))
