"""Модель связи копилки с целью (Фаза 4)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Allocation(Base):
    """Сколько из копилки закреплено за целью. Суммы — в целых рублях."""

    __tablename__ = "allocations"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # Кто закрепил деньги (из своей копилки).
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # Сумма из копилки, закреплённая за целью.
    amount: Mapped[int] = mapped_column(Integer)