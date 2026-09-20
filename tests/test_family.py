"""Тесты семьи и /family (Фаза 5, задача 5.1)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from services import family_repo
from services.family_repo import CODE_ALPHABET, CODE_LENGTH

Send = Callable[..., Awaitable[list[str]]]


# --- 5.1 generate_invite_code -------------------------------------------------


def test_generate_invite_code_is_six_chars() -> None:
    code = family_repo.generate_invite_code()
    assert len(code) == CODE_LENGTH
    assert all(char in CODE_ALPHABET for char in code)


# --- 5.1 create_family --------------------------------------------------------


async def test_create_family_makes_owner_and_code(session: AsyncSession) -> None:
    family = await family_repo.create_family(session, 1, "Наша семья", "Илья")

    assert family.id is not None
    assert family.name == "Наша семья"
    assert len(family.invite_code) == CODE_LENGTH
    assert family.created_at

    members = await family_repo.get_family_members(session, family.id)
    assert len(members) == 1
    assert members[0].telegram_id == 1
    assert members[0].role == "owner"
    assert members[0].first_name == "Илья"


async def test_create_family_twice_raises(session: AsyncSession) -> None:
    await family_repo.create_family(session, 1)
    with pytest.raises(ValueError):
        await family_repo.create_family(session, 1)


async def test_create_family_uses_default_name(session: AsyncSession) -> None:
    family = await family_repo.create_family(session, 1)
    assert family.name == "Наша семья"


# --- 5.1 join_family ----------------------------------------------------------


async def test_join_family_adds_member(session: AsyncSession) -> None:
    family = await family_repo.create_family(session, 1, first_name="Илья")

    joined = await family_repo.join_family(session, 2, family.invite_code, "Жена")
    assert joined.id == family.id

    members = await family_repo.get_family_members(session, family.id)
    assert [member.telegram_id for member in members] == [1, 2]
    assert members[1].role == "member"
    assert members[1].first_name == "Жена"


async def test_join_family_wrong_code_raises(session: AsyncSession) -> None:
    await family_repo.create_family(session, 1)
    with pytest.raises(ValueError):
        await family_repo.join_family(session, 2, "QQQQQQ")


async def test_join_family_case_insensitive(session: AsyncSession) -> None:
    family = await family_repo.create_family(session, 1)
    joined = await family_repo.join_family(session, 2, family.invite_code.lower())
    assert joined.id == family.id


async def test_join_family_when_already_member_raises(session: AsyncSession) -> None:
    family = await family_repo.create_family(session, 1)
    await family_repo.join_family(session, 2, family.invite_code)
    with pytest.raises(ValueError):
        await family_repo.join_family(session, 2, family.invite_code)


# --- 5.1 get_family -----------------------------------------------------------


async def test_get_family_returns_family_or_none(session: AsyncSession) -> None:
    assert await family_repo.get_family(session, 1) is None

    family = await family_repo.create_family(session, 1)
    stored = await family_repo.get_family(session, 1)
    assert stored is not None
    assert stored.id == family.id
    assert await family_repo.get_family(session, 2) is None


async def test_get_partner_id(session: AsyncSession) -> None:
    family = await family_repo.create_family(session, 1)
    assert await family_repo.get_partner_id(session, 1) is None
    await family_repo.join_family(session, 2, family.invite_code)
    assert await family_repo.get_partner_id(session, 1) == 2
    assert await family_repo.get_partner_id(session, 2) == 1
