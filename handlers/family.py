"""Команда /family: семья, создание и присоединение (Фаза 5)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from config import BOT_USERNAME
from services import family_repo
from services.family_repo import DEFAULT_FAMILY_NAME

NO_FAMILY_TEXT = "Ты пока не в семье. Хочешь создать или присоединиться?"

CREATE_BUTTON_TEXT = "🆕 Создать семью"
JOIN_BUTTON_TEXT = "🔗 Присоединиться"
SHOW_CODE_BUTTON_TEXT = "🔑 Показать код"
RENAME_BUTTON_TEXT = "✏️ Переименовать"

CALLBACK_CREATE = "family:create"
CALLBACK_JOIN = "family:join"
CALLBACK_SHOW_CODE = "family:show_code"
CALLBACK_RENAME = "family:rename"

NAME_PROMPT = "Название семьи? Например: Ивановы"
CODE_PROMPT = "Код приглашения? Например: A7K9M2"
RENAME_PROMPT = "Новое название семьи? Например: Ивановы"
EMPTY_NAME_TEXT = "Напиши название. Например: Ивановы"

CREATED_TEXT = "Семья создана: {name}"
LINK_TAIL = "Отправь эту ссылку второму участнику:"
CODE_TAIL = "Или пусть введёт код вручную: {code}"
JOINED_TEXT = "Ты присоединилась к семье: {name}.\nТеперь вы видите счета друг друга."
ALREADY_IN_FAMILY = "Ты уже в семье: {name}"
WRONG_CODE = "Неверный код. Проверь код приглашения и попробуй ещё раз."
JOIN_FORMAT = "Формат: /family join A7K9M2"
UNKNOWN_SUBCOMMAND = "Формат: /family create, /family join <код> или /family"
RENAMED_TEXT = "Семья переименована: {name}"


class FamilyFlow(StatesGroup):
    """Шаги создания, присоединения и переименования семьи."""

    name = State()
    code = State()
    rename = State()


def _force_reply(prompt: str) -> ForceReply:
    return ForceReply(input_field_placeholder=prompt, selective=True)


def _no_family_keyboard() -> InlineKeyboardMarkup:
    """Кнопки, когда пользователь ещё не в семье."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=CREATE_BUTTON_TEXT, callback_data=CALLBACK_CREATE
                ),
                InlineKeyboardButton(
                    text=JOIN_BUTTON_TEXT, callback_data=CALLBACK_JOIN
                ),
            ]
        ]
    )


def _family_keyboard() -> InlineKeyboardMarkup:
    """Кнопки управления семьёй."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=SHOW_CODE_BUTTON_TEXT, callback_data=CALLBACK_SHOW_CODE
                ),
                InlineKeyboardButton(
                    text=RENAME_BUTTON_TEXT, callback_data=CALLBACK_RENAME
                ),
            ]
        ]
    )


def invite_link(invite_code: str) -> str:
    """Диплинк-приглашение в семью."""
    return f"https://t.me/{BOT_USERNAME}?start=family_{invite_code}"


def _member_names(members: list[object], own_id: int) -> str:
    """«Я, Жена» — себя показываем как «Я»."""
    labels = []
    for member in members:
        if member.telegram_id == own_id:  # type: ignore[attr-defined]
            labels.append("Я")
        else:
            labels.append(member.first_name or "Участник")  # type: ignore[attr-defined]
    return ", ".join(labels)


async def send_family_invite(message: Message, family: object) -> None:
    """Три сообщения: создано, ссылка, код. Без parse_mode (в коде есть «_»)."""
    await message.answer(
        f"{CREATED_TEXT.format(name=family.name)}\n{LINK_TAIL}"  # type: ignore[attr-defined]
    )
    await message.answer(invite_link(family.invite_code))  # type: ignore[attr-defined]
    await message.answer(
        CODE_TAIL.format(code=family.invite_code)  # type: ignore[attr-defined]
    )


async def send_family_code(message: Message, family: object) -> None:
    """Ссылка и код отдельными сообщениями."""
    await message.answer(invite_link(family.invite_code))  # type: ignore[attr-defined]
    await message.answer(
        CODE_TAIL.format(code=family.invite_code)  # type: ignore[attr-defined]
    )


async def cmd_family(
    message: Message, command: CommandObject, session: AsyncSession
) -> None:
    """Семья: кнопки, создание, присоединение и показ участников."""
    if message.from_user is None:
        return

    args = (command.args or "").strip()
    if not args:
        await _show_family(message, session)
        return

    parts = args.split(maxsplit=1)
    subcommand = parts[0].lower()
    if subcommand == "create":
        await _create_family(message, session, DEFAULT_FAMILY_NAME)
        return
    if subcommand == "join":
        if len(parts) != 2:
            await message.answer(JOIN_FORMAT)
            return
        await _join_family(message, session, parts[1])
        return
    await message.answer(UNKNOWN_SUBCOMMAND)


async def _create_family(
    message: Message, session: AsyncSession, name: str
) -> None:
    """Создаёт семью и отправляет приглашение."""
    if message.from_user is None:
        return
    try:
        family = await family_repo.create_family(
            session,
            message.from_user.id,
            name,
            message.from_user.first_name,
        )
    except ValueError:
        existing = await family_repo.get_family(session, message.from_user.id)
        fallback = existing.name if existing is not None else name
        await message.answer(ALREADY_IN_FAMILY.format(name=fallback))
        return

    await send_family_invite(message, family)


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
    except ValueError as exc:
        existing = await family_repo.get_family(session, message.from_user.id)
        if existing is not None:
            await message.answer(ALREADY_IN_FAMILY.format(name=existing.name))
            return
        await message.answer(str(exc))
        return

    await message.answer(JOINED_TEXT.format(name=family.name))


async def _show_family(message: Message, session: AsyncSession) -> None:
    """Показывает сводку семьи или кнопки создания/присоединения."""
    if message.from_user is None:
        return
    telegram_id = message.from_user.id
    family = await family_repo.get_family(session, telegram_id)
    if family is None:
        await message.answer(NO_FAMILY_TEXT, reply_markup=_no_family_keyboard())
        return

    members = await family_repo.get_family_members(session, family.id)
    await message.answer(
        f"Семья: {family.name}\n"
        f"Участники: {_member_names(members, telegram_id)}\n"
        f"Код приглашения: {family.invite_code}",
        reply_markup=_family_keyboard(),
    )


async def on_create_pressed(callback, state: FSMContext) -> None:
    """[🆕 Создать семью]: запрашивает название."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await state.set_state(FamilyFlow.name)
    await callback.message.answer(NAME_PROMPT, reply_markup=_force_reply(NAME_PROMPT))


async def process_family_name(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Принимает название и создаёт семью."""
    name = (message.text or "").strip()
    if not name:
        await message.answer(EMPTY_NAME_TEXT)
        return
    await state.clear()
    await _create_family(message, session, name)


async def on_join_pressed(callback, state: FSMContext) -> None:
    """[🔗 Присоединиться]: запрашивает код."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await state.set_state(FamilyFlow.code)
    await callback.message.answer(CODE_PROMPT, reply_markup=_force_reply(CODE_PROMPT))


async def process_family_code(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Принимает код и присоединяет к семье."""
    invite_code = (message.text or "").strip()
    if not invite_code:
        await message.answer(CODE_PROMPT)
        return
    await state.clear()
    await _join_family(message, session, invite_code)


async def on_show_code_pressed(callback, session: AsyncSession) -> None:
    """[🔑 Показать код]: отправляет ссылку и код."""
    await callback.answer()
    if callback.from_user is None or not isinstance(callback.message, Message):
        return
    family = await family_repo.get_family(session, callback.from_user.id)
    if family is None:
        await callback.message.answer(
            NO_FAMILY_TEXT, reply_markup=_no_family_keyboard()
        )
        return
    await send_family_code(callback.message, family)


async def on_rename_pressed(callback, state: FSMContext) -> None:
    """[✏️ Переименовать]: запрашивает новое название."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await state.set_state(FamilyFlow.rename)
    await callback.message.answer(
        RENAME_PROMPT, reply_markup=_force_reply(RENAME_PROMPT)
    )


async def process_family_rename(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Принимает новое название семьи и сохраняет его."""
    if message.from_user is None:
        await state.clear()
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer(EMPTY_NAME_TEXT)
        return
    await state.clear()

    family = await family_repo.get_family(session, message.from_user.id)
    if family is None:
        await message.answer(NO_FAMILY_TEXT, reply_markup=_no_family_keyboard())
        return
    updated = await family_repo.rename_family(session, family.id, name)
    if updated is None:
        await message.answer(NO_FAMILY_TEXT, reply_markup=_no_family_keyboard())
        return
    await message.answer(RENAMED_TEXT.format(name=updated.name))


def build_router() -> Router:
    """Создаёт роутер команды /family."""
    router = Router(name="family")

    router.message.register(cmd_family, Command("family"))
    router.message.register(process_family_name, FamilyFlow.name, ~F.text.startswith("/"))
    router.message.register(process_family_code, FamilyFlow.code, ~F.text.startswith("/"))
    router.message.register(
        process_family_rename, FamilyFlow.rename, ~F.text.startswith("/")
    )

    router.callback_query.register(on_create_pressed, F.data == CALLBACK_CREATE)
    router.callback_query.register(on_join_pressed, F.data == CALLBACK_JOIN)
    router.callback_query.register(
        on_show_code_pressed, F.data == CALLBACK_SHOW_CODE
    )
    router.callback_query.register(on_rename_pressed, F.data == CALLBACK_RENAME)
    return router
