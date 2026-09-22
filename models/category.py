"""Модель категории операций (Фаза 6)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, CategoryType

# Длина поля categories.name (String(64)).
CATEGORY_NAME_MAX = 64


class Category(Base):
    """Категория траты или дохода: базовая или пользовательская.

    Базовые категории создаются лениво (``is_custom=False``), пользовательские
    добавляет сам пользователь (``is_custom=True``).
    """

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(64))
    # "expense" — трата, "income" — доход.
    type: Mapped[str] = mapped_column(
        String(16), default=CategoryType.EXPENSE.value
    )
    # False — базовая категория, True — добавленная пользователем.
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    # ISO-дата (UTC)
    created_at: Mapped[str] = mapped_column(String(40))
