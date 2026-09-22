"""Тесты команды /accounts (Фаза 5.1, пункт 1)."""

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
    send_message: Send,
    send_callback: Press,
    *,
    user_id: int = 1,
    first_name: str = "Test",
    card_name: str = "Т-Банк",
    amount: str = "50000",
) -> None:
    await send_message("/start", user_id=user_id, first_name=first_name)
    await send_callback("onboarding:start", user_id=user_id, first_name=first_name)
    await send_message(amount, user_id=user_id, first_name=first_name)
    await send_message(card_name, user_id=user_id, first_name=first_name)
    await send_callback(
        "onboarding:income_fixed", user_id=user_id, first_name=first_name
    )
    await send_callback(
        "onboarding:times_1", user_id=user_id, first_name=first_name
    )
    await send_message("10, 50000", user_id=user_id, first_name=first_name)


async def test_accounts_shows_accounts(
    send_message: Send, send_callback: Press, bot: object
) -> None:
    await _onboard(send_message, send_callback)

    replies = await send_message("/accounts")
    text = replies[0]
    assert "*Твои счета:*" in text
    assert "Т-Банк (карта): 50 000 ₽" in text
    assert "Копилка: 0 ₽" in text
    assert "✏️ Переименовать карту" in _button_labels(bot)


async def test_accounts_requires_onboarding(send_message: Send) -> None:
    replies = await send_message("/accounts")
    assert "онбординг" in replies[0]


async def test_accounts_rename_card(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/accounts")

    prompt = await send_callback("accounts:rename")
    assert "Новое название" in prompt[0]

    replies = await send_message("Сбер")
    assert "Карта переименована: Сбер" in replies[0]

    card = await accounts_repo.get_account(session, 1, "card")
    assert card is not None and card.name == "Сбер"


async def test_accounts_savings_not_renamed(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    """Копилка всегда остаётся «Копилка»."""
    await _onboard(send_message, send_callback)
    await send_message("/accounts")
    await send_callback("accounts:rename")
    await send_message("Сбер")

    savings = await accounts_repo.get_account(session, 1, "savings")
    assert savings is not None and savings.name == "Копилка"


async def test_accounts_family_shows_both(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(
        send_message, send_callback, user_id=1, first_name="Илья", card_name="Т-Банк"
    )
    await _onboard(
        send_message,
        send_callback,
        user_id=2,
        first_name="Жена",
        card_name="Сбер",
        amount="30000",
    )
    family = await family_repo.create_family(session, 1, "Ивановы", "Илья")
    await family_repo.join_family(session, 2, family.invite_code, "Жена")

    text = (await send_message("/accounts", user_id=1, first_name="Илья"))[0]
    assert "*Счета семьи:*" in text
    assert "Т-Банк" in text
    assert "Сбер" in text
    assert "Копилка" in text
