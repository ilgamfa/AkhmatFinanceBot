"""Тесты кнопок категорий, /categories и топа в /stats (Фаза 6)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from models import Transaction
from models.base import CategoryType
from services import categories_repo, transactions_repo

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]


def _button_labels(bot: object) -> list[str]:
    """Тексты кнопок последней клавиатуры бота."""
    markup = bot.session.last_reply_markup  # type: ignore[attr-defined]
    if not isinstance(markup, InlineKeyboardMarkup):
        return []
    return [button.text for row in markup.inline_keyboard for button in row]


async def _onboard(
    send_message: Send, send_callback: Press, *, amount: str = "50000"
) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message(amount)
    await send_message("Т-Банк")
    await send_callback("onboarding:income_fixed")
    await send_callback("onboarding:times_1")
    await send_message("10, 50000")


async def _last_transaction(session: AsyncSession) -> Transaction:
    """Последняя операция пользователя 1."""
    return (await transactions_repo.get_last_transactions(session, 1, 1))[0]


# --- 3, 4. кнопки при /minus и /plus ------------------------------------------


async def test_minus_without_category_shows_buttons(
    send_message: Send, send_callback: Press, bot: object
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/minus 5000")

    labels = _button_labels(bot)
    assert "Продукты" in labels
    assert "➕ Своя" in labels
    assert "❌ Без категории" in labels


async def test_minus_with_category_hides_buttons(
    send_message: Send, send_callback: Press, bot: object, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/minus 5000 Продукты")

    assert _button_labels(bot) == []
    assert "Категория: Продукты" in replies[0]
    transaction = await _last_transaction(session)
    assert transaction.category_id is not None


async def test_plus_with_category_saves_income_category(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/plus 50000 Зарплата")

    assert "Категория: Зарплата" in replies[0]
    transaction = await _last_transaction(session)
    assert transaction.category_id is not None


async def test_unknown_category_warns_without_category(
    send_message: Send, send_callback: Press, bot: object, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/minus 5000 Неизвестная")

    assert any("не найдена" in text for text in replies)
    transaction = await _last_transaction(session)
    assert transaction.category_id is None
    assert "Продукты" in _button_labels(bot)


# --- 5, 6, 7. выбор категории -------------------------------------------------


async def test_pick_base_category_saves_id(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/minus 5000")
    transaction = await _last_transaction(session)
    transaction_id = transaction.id
    category = await categories_repo.find_by_name(
        session, 1, "Продукты", CategoryType.EXPENSE.value
    )
    assert category is not None
    category_id = category.id

    await send_callback(f"cat_pick:{transaction_id}:{category_id}")

    session.expire_all()
    updated = await session.get(Transaction, transaction_id)
    assert updated is not None
    assert updated.category_id == category_id


async def test_own_category_creates_and_saves(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/minus 5000")
    transaction = await _last_transaction(session)
    transaction_id = transaction.id

    prompt = await send_callback(f"cat_own:{transaction_id}")
    assert "Название категории" in prompt[0]

    await send_message("Кофе")

    session.expire_all()
    categories = await categories_repo.get_categories(
        session, 1, CategoryType.EXPENSE.value
    )
    coffee = next((item for item in categories if item.name == "Кофе"), None)
    assert coffee is not None and coffee.is_custom is True
    updated = await session.get(Transaction, transaction_id)
    assert updated is not None
    assert updated.category_id == coffee.id


async def test_no_category_keeps_null(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/minus 5000")
    transaction = await _last_transaction(session)
    transaction_id = transaction.id

    await send_callback(f"cat_none:{transaction_id}")

    session.expire_all()
    updated = await session.get(Transaction, transaction_id)
    assert updated is not None
    assert updated.category_id is None


# --- 8. /categories -----------------------------------------------------------


async def test_categories_command_shows_list(
    send_message: Send, send_callback: Press, bot: object
) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/categories")

    text = replies[0]
    assert "*Траты:*" in text
    assert "Продукты" in text
    assert "Зарплата" in text
    labels = _button_labels(bot)
    assert "➕ Добавить" in labels
    assert "🗑 Удалить" in labels


async def test_categories_add_custom(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/categories")
    await send_callback("categories:add")
    await send_message("Кофе")

    categories = await categories_repo.get_categories(
        session, 1, CategoryType.EXPENSE.value
    )
    assert any(
        category.name == "Кофе" and category.is_custom
        for category in categories
    )


async def test_categories_delete_custom(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/categories")
    await send_callback("categories:add")
    await send_message("Кофе")
    category = await categories_repo.find_by_name(
        session, 1, "Кофе", CategoryType.EXPENSE.value
    )
    assert category is not None
    category_id = category.id

    await send_message("/categories")
    await send_callback("categories:delete")
    await send_callback(f"categories_del:{category_id}")

    session.expire_all()
    assert await categories_repo.get_category(session, 1, category_id) is None


# --- 9, 10. топ-3 в /stats ----------------------------------------------------


async def test_stats_shows_top_categories(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/minus 1000 Продукты")
    await send_message("/minus 2000 Транспорт")
    await send_message("/minus 300 Продукты")
    await send_message("/minus 400 Жильё")

    text = (await send_message("/stats"))[0]
    assert "*Топ категорий за месяц:*" in text
    assert "1. Транспорт: 2 000 ₽" in text
    assert "2. Продукты: 1 300 ₽" in text
    assert "3. Жильё: 400 ₽" in text


async def test_stats_hides_top_without_categories(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    text = (await send_message("/stats"))[0]
    assert "Топ категорий" not in text


async def test_stats_hides_top_for_uncategorized_expense(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/minus 5000")
    text = (await send_message("/stats"))[0]
    assert "Топ категорий" not in text
