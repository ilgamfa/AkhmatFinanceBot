"""Команда /family: семья, создание и присоединение (Фаза 5)."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from services import family_repo
from services.family_repo import DEFAULT_FAMILY_NAME

SINGLE_TEXT = (
    "Ты ведёшь бюджет один. Создай семью через /family create "
    "или присоединись через /family join <код>"
)
CREATED_HEADER = "Семья создана: {name}"
INVITE_HEADER = "Код приглашения: {code}"
CREATED_TAIL = "Передай этот код второму участнику."
JOINED_TEXT = "Ты присоединилась к семье: {name}.\nТеперь вы видите счета друг друга."
ALREADY_IN_FAMILY = "Ты уже в семье: {name}"
WRONG_CODE = "Неверный код. Проверь код приглашения и попробуй ещё раз."
JOIN_FORMAT = "Формат: /family join A7K9M2"
UNKNOWN_SUBCOMMAND = (
    "Формат: /family create, /family join <код> или /family"
)


def _member_names(members: list[object], own_id: int) -> str:
    """«Я, Жена» — себя показываем как «Я»."""
    labels = []
    for member in members:
        if member.telegram_id == own_id:  # type: ignore[attr-defined]
            labels.append("Я")
        else:
            labels.append(member.first_name or "Участник")  # type: ignore[attr-defined]
    return ", ".join(labels)


async def cmd_family(
    message: Message, command: CommandObject, session: AsyncSession
) -> None:
    """Семья: создание, присоединение и показ участников."""
    if message.from_user is None:
        return

    args = (command.args or "").strip()
    if not args:
        await _show_family(message, session)
        return

    parts = args.split(maxsplit=1)
    subcommand = parts[0].lower()
    if subcommand == "create":
        await _create_family(message, session)
        return
    if subcommand == "join":
        if len(parts) != 2:
            await message.answer(JOIN_FORMAT)
            return
        await _join_family(message, session, parts[1])
        return
    await message.answer(UNKNOWN_SUBCOMMAND)


async def _create_family(message: Message, session: AsyncSession) -> None:
    """Создаёт семью с пользователем-владельцем."""
    if message.from_user is None:
        return
    try:
        family = await family_repo.create_family(
            session,
            message.from_user.id,
            DEFAULT_FAMILY_NAME,
            message.from_user.first_name,
        )
    except ValueError:
        existing = await family_repo.get_family(session, message.from_user.id)
        name = existing.name if existing is not None else DEFAULT_FAMILY_NAME
        await message.answer(ALREADY_IN_FAMILY.format(name=name))
        return

    await message.answer(
        f"{CREATED_HEADER.format(name=family.name)}\n"
        f"{INVITE_HEADER.format(code=family.invite_code)}\n"
        f"{CREATED_TAIL}"
    )


async def _join_family(
    message: Message, session: AsyncSession, invite_code: str
) -> None:
    """Присоединяет пользователя к семье по коду."""
    if message.from_user is None:
        return
    try:
        family = await family_repo.join_family(
            session,
            message.from_user.id,
            invite_code,
            message.from_user.first_name,
        )
    except ValueError:
        existing = await family_repo.get_family(session, message.from_user.id)
        if existing is not None:
            await message.answer(ALREADY_IN_FAMILY.format(name=existing.name))
            return
        await message.answer(WRONG_CODE)
        return

    await message.answer(JOINED_TEXT.format(name=family.name))


async def _show_family(message: Message, session: AsyncSession) -> None:
    """Показывает семью, участников и код приглашения."""
    if message.from_user is None:
        return
    telegram_id = message.from_user.id
    family = await family_repo.get_family(session, telegram_id)
    if family is None:
        await message.answer(SINGLE_TEXT)
        return

    members = await family_repo.get_family_members(session, family.id)
    await message.answer(
        f"Семья: {family.name}\n"
        f"Участники: {_member_names(members, telegram_id)}\n"
        f"Код приглашения: {family.invite_code}"
    )


def build_router() -> Router:
    """Создаёт роутер команды /family."""
    router = Router(name="family")
    router.message.register(cmd_family, Command("family"))
    return router
