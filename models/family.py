"""Модели семьи (Фаза 5)."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Family(Base):
    """Семья: два участника с общим прозрачным бюджетом."""

    __tablename__ = "families"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    # Код приглашения второго участника, например A7K9M2.
    invite_code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    # ISO-дата (UTC), например 2026-09-20T12:30:00+00:00
    created_at: Mapped[str] = mapped_column(String(40))


class FamilyMember(Base):
    """Участник семьи. У пользователя не может быть больше одной семьи."""

    __tablename__ = "family_members"
    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_family_members_telegram_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # "owner" — создатель семьи, "member" — присоединившийся.
    role: Mapped[str] = mapped_column(String(16))
    # Имя из Telegram для подписей «Карта жены» / «(жена, сегодня)».
    first_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
