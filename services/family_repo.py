"""Операции с семьёй (Фаза 5)."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models import Family, FamilyMember

OWNER_ROLE = "owner"
MEMBER_ROLE = "member"
DEFAULT_FAMILY_NAME = "Наша семья"

# Без похожих символов (I, O, 0, 1), чтобы код было легко продиктовать.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
MAX_CODE_ATTEMPTS = 20
# Семья — два человека; третий присоединиться не может.
MAX_FAMILY_MEMBERS = 2


def _now_iso() -> str:
    """Текущее время в ISO-формате (UTC)."""
    return datetime.now(UTC).isoformat()


def generate_invite_code() -> str:
    """Случайный 6-символьный код приглашения."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


async def create_family(
    session: AsyncSession,
    telegram_id: int,
    name: str | None = None,
    first_name: str | None = None,
) -> Family:
    """Создаёт семью и делает ``telegram_id`` её владельцем.

    Бросает ValueError, если пользователь уже в семье.
    """
    if await get_family(session, telegram_id) is not None:
        raise ValueError("Ты уже в семье.")

    family = await _insert_family(session, name or DEFAULT_FAMILY_NAME)
    session.add(
        FamilyMember(
            family_id=family.id,
            telegram_id=telegram_id,
            role=OWNER_ROLE,
            first_name=first_name,
        )
    )
    await session.commit()
    await _join_accounts(session, telegram_id, family.id)
    await session.refresh(family)
    return family


async def _insert_family(session: AsyncSession, name: str) -> Family:
    """Вставляет семью с уникальным кодом, повторяя при коллизии."""
    for _ in range(MAX_CODE_ATTEMPTS):
        family = Family(
            name=name, invite_code=generate_invite_code(), created_at=_now_iso()
        )
        session.add(family)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            continue
        return family
    raise RuntimeError("Не удалось сгенерировать уникальный код приглашения.")


async def join_family(
    session: AsyncSession,
    telegram_id: int,
    invite_code: str,
    first_name: str | None = None,
) -> Family:
    """Добавляет пользователя в семью по коду как участника.

    Бросает ValueError, если код неверный, пользователь уже в семье
    или в семье уже два участника.
    """
    if await get_family(session, telegram_id) is not None:
        raise ValueError("Ты уже в семье.")
    family = await get_family_by_code(session, invite_code)
    if family is None:
        raise ValueError("Семья с таким кодом не найдена.")
    if len(await get_family_members(session, family.id)) >= MAX_FAMILY_MEMBERS:
        raise ValueError("В этой семье уже два участника.")
    session.add(
        FamilyMember(
            family_id=family.id,
            telegram_id=telegram_id,
            role=MEMBER_ROLE,
            first_name=first_name,
        )
    )
    await session.commit()
    await _join_accounts(session, telegram_id, family.id)
    return family


async def _join_accounts(
    session: AsyncSession, telegram_id: int, family_id: int
) -> None:
    """Проставляет family_id на счетах участника."""
    from services import accounts_repo

    await accounts_repo.set_family_id(session, telegram_id, family_id)


async def get_family_by_code(
    session: AsyncSession, invite_code: str
) -> Family | None:
    """Возвращает семью по коду приглашения или None (регистр не важен)."""
    result = await session.execute(
        select(Family).where(Family.invite_code == invite_code.strip().upper())
    )
    return result.scalar_one_or_none()


async def rename_family(
    session: AsyncSession, family_id: int, name: str
) -> Family | None:
    """Меняет название семьи. None, если семьи нет."""
    family = await session.get(Family, family_id)
    if family is None:
        return None
    family.name = name
    await session.commit()
    await session.refresh(family)
    return family


async def get_family(session: AsyncSession, telegram_id: int) -> Family | None:
    """Возвращает семью пользователя или None."""
    result = await session.execute(
        select(Family)
        .join(FamilyMember, FamilyMember.family_id == Family.id)
        .where(FamilyMember.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def get_family_members(
    session: AsyncSession, family_id: int
) -> list[FamilyMember]:
    """Участники семьи по порядку присоединения (сначала владелец)."""
    result = await session.execute(
        select(FamilyMember)
        .where(FamilyMember.family_id == family_id)
        .order_by(FamilyMember.id)
    )
    return list(result.scalars().all())


async def get_partner_id(session: AsyncSession, telegram_id: int) -> int | None:
    """Telegram ID второго участника семьи или None."""
    family = await get_family(session, telegram_id)
    if family is None:
        return None
    members = await get_family_members(session, family.id)
    for member in members:
        if member.telegram_id != telegram_id:
            return member.telegram_id
    return None
