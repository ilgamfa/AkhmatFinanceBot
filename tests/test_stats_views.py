"""Тесты кнопок и переключения видов в /stats (Фаза 5.1)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from services import family_repo

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]


def _button_labels(bot: object) -> list[str]:
    """Тексты кнопок последней клавиатуры бота."""
    markup = bot.session.last_reply_markup  # type: ignore[attr-defined]
    if not isinstance(markup, InlineKeyboardMarkup):
        return []
    return [button.text for row in markup.inline_keyboard for button in row]


async def _onboard(
    send_message: Send, send_callback: Press, *, user_id: int, first_name: str
) -> None:
    await send_message("/start", user_id=user_id, first_name=first_name)
    await send_callback("onboarding:start", user_id=user_id, first_name=first_name)
    await send_message("12000", user_id=user_id, first_name=first_name)
    await send_callback(
        "onboarding:income_fixed", user_id=user_id, first_name=first_name
    )
    await send_callback(
        "onboarding:times_1", user_id=user_id, first_name=first_name
    )
    await send_message("10, 50000", user_id=user_id, first_name=first_name)


async def _make_family(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    """Создаёт семью из двух пользователей через команды."""
    await _onboard(send_message, send_callback, user_id=1, first_name="Илья")
    await _onboard(send_message, send_callback, user_id=2, first_name="Жена")
    await send_message("/family create", user_id=1, first_name="Илья")
    family = await family_repo.get_family(session, 1)
    assert family is not None
    await send_message(
        f"/family join {family.invite_code}", user_id=2, first_name="Жена"
    )


async def test_family_stats_shows_buttons(
    send_message: Send, send_callback: Press, session: AsyncSession, bot: object
) -> None:
    await _make_family(send_message, send_callback, session)
    await send_message("/stats", user_id=1, first_name="Илья")

    labels = _button_labels(bot)
    assert "📊 Общая" in labels
    assert "👤 Илья" in labels
    assert "👤 Жена" in labels


async def test_solo_stats_has_no_buttons(
    send_message: Send, send_callback: Press, bot: object
) -> None:
    await _onboard(send_message, send_callback, user_id=1, first_name="Илья")
    await send_message("/stats", user_id=1, first_name="Илья")

    assert _button_labels(bot) == []


async def test_user_button_shows_member_stats(
    send_message: Send, send_callback: Press, session: AsyncSession, bot: object
) -> None:
    await _make_family(send_message, send_callback, session)
    await send_message("/stats", user_id=1, first_name="Илья")
    sent_before = len(bot.session.sent)  # type: ignore[attr-defined]

    await send_callback("stats_user_2", user_id=1, first_name="Илья")

    edited = bot.session.edited[-1].text  # type: ignore[attr-defined]
    assert "*Статистика: Жена*" in edited
    assert "*Моя карта:*" in edited
    # редактирование, а не новое сообщение
    assert len(bot.session.sent) == sent_before  # type: ignore[attr-defined]
    assert "📊 Общая" in _button_labels(bot)


async def test_overall_button_returns_family_stats(
    send_message: Send, send_callback: Press, session: AsyncSession, bot: object
) -> None:
    await _make_family(send_message, send_callback, session)
    await send_message("/stats", user_id=1, first_name="Илья")
    await send_callback("stats_user_2", user_id=1, first_name="Илья")

    await send_callback("stats_family", user_id=1, first_name="Илья")

    edited = bot.session.edited[-1].text  # type: ignore[attr-defined]
    assert "*Семья: Наша семья*" in edited
    assert "*Счета:*" in edited


async def test_user_button_ignores_foreign_id(
    send_message: Send, send_callback: Press, session: AsyncSession, bot: object
) -> None:
    """Кнопка с чужим telegram_id ничего не меняет."""
    await _make_family(send_message, send_callback, session)
    await send_message("/stats", user_id=1, first_name="Илья")
    edited_before = len(bot.session.edited)  # type: ignore[attr-defined]

    await send_callback("stats_user_999", user_id=1, first_name="Илья")

    assert len(bot.session.edited) == edited_before  # type: ignore[attr-defined]
