"""Модель копилки (Фаза 4)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Savings(Base):
    """Одна копилка на пользователя. Баланс — в целых рублях."""

    __tablename__ = "savings"

    # telegram_id — первичный ключ: у пользователя ровно одна копилка.
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)