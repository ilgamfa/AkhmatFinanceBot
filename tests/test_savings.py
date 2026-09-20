"""Тесты копилки, /savings и распределения (Фаза 4)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from services import (
    allocations_repo,
    goals_repo,
    savings_repo,
    transactions_repo,
    users_repo,
)

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]


def _button_labels(bot: object) -> list[str]:
    """Тексты кнопок последней клавиатуры бота."""
    markup = bot.session.last_reply_markup  # type: ignore[attr-defined]
    if not isinstance(markup, InlineKeyboardMarkup):
        return []
    return [button.text for row in markup.inline_keyboard for button in row]


# --- 4.1 репозиторий копилки и связей -----------------------------------------


async def test_add_to_savings_creates_and_accumulates(session: AsyncSession) -> None:
    balance = await savings_repo.add_to_savings(session, 1, 200000)
    assert balance == 200000
    balance = await savings_repo.add_to_savings(session, 1, 10000)
    assert balance == 210000

    assert await savings_repo.get_savings(session, 1) == 210000
    assert await savings_repo.get_savings(session, 2) == 0


async def test_add_to_savings_rejects_non_positive(session: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await savings_repo.add_to_savings(session, 1, 0)


async def test_get_free_in_savings(session: AsyncSession) -> None:
    await savings_repo.add_to_savings(session, 1, 550000)
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)
    goal2 = await goals_repo.add_goal(session, 1, "Подушка", 300000, None, 2)
    await allocations_repo.allocate(session, goal.id, 400000)
    await allocations_repo.allocate(session, goal2.id, 150000)

    assert await savings_repo.get_allocated_total(session, 1) == 550000
    assert await savings_repo.get_free_in_savings(session, 1) == 0
    assert await savings_repo.get_free_in_savings(session, 2) == 0


async def test_allocate_saves_and_returns_progress(session: AsyncSession) -> None:
    await savings_repo.add_to_savings(session, 1, 550000)
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)

    progress = await allocations_repo.allocate(session, goal.id, 400000)
    assert progress == 400000
    assert await goals_repo.get_goal_progress(session, goal.id) == 400000

    allocations = await allocations_repo.get_allocations_by_goal(session, goal.id)
    assert len(allocations) == 1
    assert allocations[0].amount == 400000


async def test_allocate_denies_exceeding_free(session: AsyncSession) -> None:
    await savings_repo.add_to_savings(session, 1, 50000)
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)

    with pytest.raises(ValueError):
        await allocations_repo.allocate(session, goal.id, 50001)
    with pytest.raises(ValueError):
        await allocations_repo.allocate(session, goal.id, 0)
    assert await goals_repo.get_goal_progress(session, goal.id) == 0

    # всё свободное занято — повторная попытка тоже падает
    await allocations_repo.allocate(session, goal.id, 50000)
    with pytest.raises(ValueError):
        await allocations_repo.allocate(session, goal.id, 1)


async def test_unallocate_withdraws_partially(session: AsyncSession) -> None:
    await savings_repo.add_to_savings(session, 1, 100000)
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)
    await allocations_repo.allocate(session, goal.id, 60000)
    await allocations_repo.allocate(session, goal.id, 30000)

    progress = await allocations_repo.unallocate(session, goal.id, 50000)
    assert progress == 40000

    assert await goals_repo.get_goal_progress(session, goal.id) == 40000
    assert await savings_repo.get_free_in_savings(session, 1) == 60000
    allocations = await allocations_repo.get_allocations_by_goal(session, goal.id)
    assert sum(allocation.amount for allocation in allocations) == 40000


async def test_unallocate_denies_more_than_allocated(session: AsyncSession) -> None:
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)
    with pytest.raises(ValueError):
        await allocations_repo.unallocate(session, goal.id, 100)
    with pytest.raises(ValueError):
        await allocations_repo.unallocate(session, 999, 100)


# --- 4.2 /savings: показ -------------------------------------------------------


async def test_savings_empty_shows_empty_text(
    send_message: Send, bot: object
) -> None:
    text = (await send_message("/savings"))[0]
    assert "Копилка пуста" in text
    labels = _button_labels(bot)
    assert "➕ Пополнить" in labels
    assert "💰 Распределить" in labels


async def test_savings_shows_balance_and_allocations(
    send_message: Send, session: AsyncSession, bot: object
) -> None:
    await savings_repo.add_to_savings(session, 1, 550000)
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)
    await allocations_repo.allocate(session, goal.id, 400000)

    text = (await send_message("/savings"))[0]
    assert "Копилка: 550 000 ₽" in text
    assert "Закреплено за целями:" in text
    assert "🚗 Машина: 400 000 ₽" in text
    assert "Свободно в копилке: 150 000 ₽" in text
    labels = _button_labels(bot)
    assert "➕ Пополнить" in labels
    assert "💰 Распределить" in labels


async def test_savings_hides_allocations_when_none(
    send_message: Send, session: AsyncSession
) -> None:
    await savings_repo.add_to_savings(session, 1, 100000)
    text = (await send_message("/savings"))[0]
    assert "Копилка: 100 000 ₽" in text
    assert "Закреплено за целями:" not in text
    assert "Свободно в копилке: 100 000 ₽" in text


# --- 4.2 /savings: пополнение -------------------------------------------------


async def _with_free_money(session: AsyncSession, amount: int) -> None:
    user = await users_repo.get_or_create(session, 1)
    await users_repo.save_onboarding_profile(
        session, user, free_money=amount, income_type="fixed", income_dates="[]"
    )


async def test_savings_add_via_command(
    send_message: Send, session: AsyncSession
) -> None:
    await _with_free_money(session, 50000)

    text = (await send_message("/savings add 50000"))[0]
    assert "Пополнено: 50 000 ₽" in text
    assert "Копилка: 50 000 ₽" in text
    assert "Свободно: 50 000 ₽" in text

    session.expire_all()
    user = await users_repo.get_by_telegram_id(session, 1)
    assert user is not None
    assert user.free_money == 0
    assert await savings_repo.get_savings(session, 1) == 50000

    transactions = await transactions_repo.get_last_transactions(session, 1, 1)
    assert transactions[0].type == "savings_add"
    assert transactions[0].amount == 50000


async def test_savings_add_via_button(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _with_free_money(session, 50000)
    await send_message("/savings")

    replies = await send_callback("savings:add")
    assert "Сумма пополнения?" in replies[0]

    text = (await send_message("20000"))[0]
    assert "Пополнено: 20 000 ₽" in text
    assert "Копилка: 20 000 ₽" in text

    session.expire_all()
    assert await savings_repo.get_savings(session, 1) == 20000


async def test_savings_add_insufficient_free_money(
    send_message: Send, session: AsyncSession
) -> None:
    await _with_free_money(session, 5000)
    text = (await send_message("/savings add 10000"))[0]
    assert "Недостаточно свободных денег. Свободно: 5 000 ₽" in text
    assert await savings_repo.get_savings(session, 1) == 0


async def test_savings_add_no_profile(send_message: Send) -> None:
    """Без онбординга free_money = 0 — пополнение невозможно."""
    text = (await send_message("/savings add 100"))[0]
    assert "Недостаточно свободных денег" in text


async def test_savings_add_bad_input(send_message: Send) -> None:
    replies = await send_message("/savings hello")
    assert "Формат: /savings add 50000" in replies[0]
    replies = await send_message("/savings add абв")
    assert "Не понял сумму" in replies[0]


# --- 4.5 распределение --------------------------------------------------------


async def test_allocate_flow_success(
    send_message: Send, send_callback: Press, session: AsyncSession, bot: object
) -> None:
    await savings_repo.add_to_savings(session, 1, 550000)
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)
    await allocations_repo.allocate(session, goal.id, 400000)
    goal_id = goal.id
    session.expire_all()

    replies = await send_callback("alloc:start")
    assert "К какой цели закрепить деньги?" in replies[0]
    labels = _button_labels(bot)
    assert "1. Машина (400 000 / 1 500 000)" in labels
    assert "❌ Отмена" in labels

    replies = await send_callback(f"alloc:goal:{goal_id}")
    assert "Сколько закрепить за целью «Машина»?" in replies[0]
    assert "Свободно в копилке: 150 000 ₽" in replies[0]

    text = (await send_message("50000"))[0]
    assert "Закреплено за целью «Машина»: 50 000 ₽" in text
    assert "Прогресс: 450 000 / 1 500 000 ₽ (30%)" in text
    assert "Свободно в копилке: 100 000 ₽" in text


async def test_allocate_flow_insufficient(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)

    await send_callback("alloc:start")
    replies = await send_callback("alloc:goal:1")
    assert "Свободно в копилке: 0 ₽" in replies[0]

    text = (await send_message("100"))[0]
    assert "Недостаточно свободных денег в копилке. Свободно: 0 ₽" in text
    assert await goals_repo.get_goal_progress(session, 1) == 0


async def test_allocate_no_goals(send_callback: Press) -> None:
    replies = await send_callback("alloc:start")
    assert "нет целей" in replies[0]


async def test_allocate_cancel(send_callback: Press) -> None:
    replies = await send_callback("alloc:cancel")
    assert "Отменено" in replies[0]