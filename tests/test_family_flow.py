"""Тесты флоу семьи: кнопки и диплинк-приглашение (Фаза 5.1, пункт 1)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from services import accounts_repo, family_repo

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]


def _button_labels(bot: object) -> list[str]:
    """Тексты кнопок последней клавиатуры бота."""
    markup = bot.session.last_reply_markup  # type: ignore[attr-defined]
    if not isinstance(markup, InlineKeyboardMarkup):
        return []
    return [button.text for row in markup.inline_keyboard for button in row]


async def _onboard(
    send_message: Send, send_callback: Press, *, user_id: int = 1
) -> None:
    await send_message("/start", user_id=user_id)
    await send_callback("onboarding:start", user_id=user_id)
    await send_message("12000", user_id=user_id)
    await send_callback("onboarding:income_fixed", user_id=user_id)
    await send_callback("onboarding:times_1", user_id=user_id)
    await send_message("10, 50000", user_id=user_id)


# --- кнопки в /family ---------------------------------------------------------


async def test_family_without_family_shows_buttons(
    send_message: Send, bot: object
) -> None:
    await send_message("/family")
    labels = _button_labels(bot)
    assert "🆕 Создать семью" in labels
    assert "🔗 Присоединиться" in labels


async def test_create_family_via_button(
    send_message: Send, send_callback: Press
) -> None:
    replies = await send_callback("family:create")
    assert "Название семьи" in replies[0]

    replies = await send_message("Ивановы")
    assert "Семья создана: Ивановы" in replies[0]
    assert replies[1].startswith("https://t.me/")
    assert "?start=family_" in replies[1]
    assert replies[2].startswith("Или пусть введёт код вручную: ")


async def test_join_family_via_button(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    family = await family_repo.create_family(session, 1, "Ивановы", "Илья")

    replies = await send_callback("family:join", user_id=2, first_name="Жена")
    assert "Код приглашения" in replies[0]

    replies = await send_message(
        family.invite_code, user_id=2, first_name="Жена"
    )
    assert "Ты присоединилась к семье: Ивановы" in replies[0]


async def test_family_in_family_shows_summary_and_buttons(
    send_message: Send, send_callback: Press, session: AsyncSession, bot: object
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/family create", user_id=1, first_name="Илья")

    replies = await send_message("/family", user_id=1, first_name="Илья")
    assert "Код приглашения:" in replies[0]
    labels = _button_labels(bot)
    assert "🔑 Показать код" in labels
    assert "✏️ Переименовать" in labels


async def test_show_code_button(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    family = await family_repo.create_family(session, 1, "Ивановы", "Илья")

    replies = await send_callback("family:show_code")
    assert replies[0] == f"https://t.me/akhmatfinancebot?start=family_{family.invite_code}"
    assert replies[1] == f"Или пусть введёт код вручную: {family.invite_code}"


async def test_rename_family_via_button(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await family_repo.create_family(session, 1, "Ивановы", "Илья")

    replies = await send_callback("family:rename")
    assert "Новое название" in replies[0]

    replies = await send_message("Петровы")
    assert "Семья переименована: Петровы" in replies[0]
    family = await family_repo.get_family(session, 1)
    assert family is not None and family.name == "Петровы"


# --- диплинк-приглашение ------------------------------------------------------


async def test_deeplink_offers_to_join(
    send_message: Send, session: AsyncSession, bot: object
) -> None:
    family = await family_repo.create_family(session, 1, "Ивановы", "Илья")

    replies = await send_message(
        f"/start family_{family.invite_code}", user_id=2, first_name="Жена"
    )
    assert "Тебя пригласили в семью: Ивановы" in replies[0]
    assert "✅ Да" in _button_labels(bot)
    assert "❌ Нет" in _button_labels(bot)


async def test_deeplink_unknown_code(send_message: Send) -> None:
    replies = await send_message("/start family_ZZZZZZ", user_id=2)
    assert "Код не найден" in replies[0]


async def test_deeplink_already_in_family(
    send_message: Send, session: AsyncSession
) -> None:
    family = await family_repo.create_family(session, 1, "Ивановы", "Илья")

    replies = await send_message(
        f"/start family_{family.invite_code}", user_id=1, first_name="Илья"
    )
    assert "Ты уже в семье: Ивановы" in replies[0]


async def test_deeplink_family_full(
    send_message: Send, session: AsyncSession
) -> None:
    family = await family_repo.create_family(session, 1, "Ивановы", "Илья")
    await family_repo.join_family(session, 2, family.invite_code, "Жена")

    replies = await send_message(
        f"/start family_{family.invite_code}", user_id=3, first_name="Третий"
    )
    assert "уже два участника" in replies[0]


async def test_deeplink_yes_joins_and_starts_onboarding(
    send_message: Send,
    send_callback: Press,
    session: AsyncSession,
) -> None:
    family = await family_repo.create_family(session, 1, "Ивановы", "Илья")
    await send_message(
        f"/start family_{family.invite_code}", user_id=2, first_name="Жена"
    )

    replies = await send_callback(
        f"family_link:yes:{family.invite_code}", user_id=2, first_name="Жена"
    )
    assert any("Ты присоединилась к семье" in text for text in replies)
    assert any("3 вопроса" in text for text in replies)

    members = await family_repo.get_family_members(session, family.id)
    assert [member.telegram_id for member in members] == [1, 2]
    # счета ещё не созданы: их создаст онбординг, чтобы не потерять баланс
    assert await accounts_repo.get_account(session, 2, "card") is None

    await send_callback("onboarding:start", user_id=2, first_name="Жена")
    await send_message("30000", user_id=2, first_name="Жена")
    await send_callback("onboarding:income_fixed", user_id=2, first_name="Жена")
    await send_callback("onboarding:times_1", user_id=2, first_name="Жена")
    await send_message("10, 50000", user_id=2, first_name="Жена")

    card = await accounts_repo.get_account(session, 2, "card")
    assert card is not None
    assert card.balance == 30000
    assert card.family_id == family.id


async def test_deeplink_onboarding_balance_visible_in_stats(
    send_message: Send,
    send_callback: Press,
    session: AsyncSession,
) -> None:
    """Сумма, введённая при онбординге после вступления, видна в /stats."""
    family = await family_repo.create_family(session, 1, "Ивановы", "Илья")
    await send_message(
        f"/start family_{family.invite_code}", user_id=2, first_name="Жена"
    )
    await send_callback(
        f"family_link:yes:{family.invite_code}", user_id=2, first_name="Жена"
    )
    await send_callback("onboarding:start", user_id=2, first_name="Жена")
    await send_message("30000", user_id=2, first_name="Жена")
    await send_callback("onboarding:income_fixed", user_id=2, first_name="Жена")
    await send_callback("onboarding:times_1", user_id=2, first_name="Жена")
    await send_message("10, 50000", user_id=2, first_name="Жена")

    text = (await send_message("/stats", user_id=2, first_name="Жена"))[0]
    assert "Моя карта: 30 000 ₽" in text


async def test_deeplink_no_cancels(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    family = await family_repo.create_family(session, 1, "Ивановы", "Илья")
    await send_message(
        f"/start family_{family.invite_code}", user_id=2, first_name="Жена"
    )

    replies = await send_callback(
        "family_link:no", user_id=2, first_name="Жена"
    )
    assert "Отменено" in replies[0]
    assert await family_repo.get_family(session, 2) is None
