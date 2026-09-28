"""Модель пользователя."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import AdviceStyle, Base


class User(Base):
    """Пользователь бота и его финансовый профиль."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    advice_style: Mapped[str] = mapped_column(
        String(16), default=AdviceStyle.SOFT.value
    )
    onboarding_completed: Mapped[bool] = mapped_column(default=False)

    # Профиль Фазы 1 (заполняется в онбординге).
    income_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # JSON-строка со списком {"day": int, "amount": int} для fixed-дохода.
    income_dates: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Средний доход в месяц для irregular-дохода.
    income: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Настройки напоминаний (Фаза 8).
    reminder_evening_enabled: Mapped[bool] = mapped_column(default=True)
    reminder_evening_time: Mapped[str] = mapped_column(String(5), default="21:00")
    reminder_payment_enabled: Mapped[bool] = mapped_column(default=True)
    reminder_payment_time: Mapped[str] = mapped_column(String(5), default="10:00")
    reminder_payment_days_before: Mapped[int] = mapped_column(Integer, default=1)
    # Дата (Europe/Moscow) последней отправки — защита от дублей (Фаза 8).
    reminder_evening_last_sent: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    reminder_payment_last_sent: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
