"""Тесты целей, /goals и расчётов Фазы 4."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from services import allocations_repo, goals_repo, savings_repo
from services.calculations import (
    format_goal_deadline,
    goal_progress_percent,
    monthly_goal_amount,
    months_until_deadline,
    parse_goal_deadline,
)

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]


def _button_labels(bot: object) -> list[str]:
    """Тексты кнопок последней клавиатуры бота."""
    markup = bot.session.last_reply_markup  # type: ignore[attr-defined]
    if not isinstance(markup, InlineKeyboardMarkup):
        return []
    return [button.text for row in markup.inline_keyboard for button in row]


# --- 4.1 расчёты целей --------------------------------------------------------


def test_goal_helpers() -> None:
    today = date(2026, 9, 20)
    assert months_until_deadline(None, today) is None
    assert months_until_deadline("2027-12-01", today) == 14
    assert months_until_deadline("2027-12-25", today) == 15
    assert months_until_deadline("2020-01-01", today) == 1
    assert monthly_goal_amount(0, 1500000, None, today) is None
    assert monthly_goal_amount(0, 1500000, "2027-12-01", today) == 107143
    assert monthly_goal_amount(50000, 1500000, "2027-12-01", today) == 103572
    assert monthly_goal_amount(1500000, 1500000, "2027-12-01", today) == 0
    assert goal_progress_percent(50000, 1500000) == 3
    assert goal_progress_percent(0, 0) == 0
    assert parse_goal_deadline("skip") is None
    assert parse_goal_deadline("01.12.2027") == "2027-12-01"
    assert format_goal_deadline("2027-12-01") == "01.12.2027"
    assert format_goal_deadline(None) is None


# --- 4.1 репозиторий ----------------------------------------------------------


async def test_add_goal(session: AsyncSession) -> None:
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, "2027-12-01", 1)
    assert goal.id is not None
    assert goal.telegram_id == 1
    assert goal.name == "Машина"
    assert goal.target == 1500000
    assert goal.deadline == "2027-12-01"
    assert goal.priority == 1
    assert goal.created_at


async def test_get_goals(session: AsyncSession) -> None:
    await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)
    await goals_repo.add_goal(session, 1, "Подушка", 300000, "2027-06-01", 2)
    await goals_repo.add_goal(session, 2, "Чужой", 100, None, 3)

    goals = await goals_repo.get_goals(session, 1)
    assert [goal.name for goal in goals] == ["Машина", "Подушка"]
    assert goals[0].deadline is None


async def test_update_goal(session: AsyncSession) -> None:
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)

    updated = await goals_repo.update_goal(
        session, 1, goal.id, name="Авто", priority=2
    )
    assert updated is not None
    assert updated.name == "Авто"
    assert updated.priority == 2

    assert await goals_repo.update_goal(session, 1, 999, name="X") is None


async def test_get_goal_progress_from_allocations(session: AsyncSession) -> None:
    await savings_repo.add_to_savings(session, 1, 500000)
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)

    assert await goals_repo.get_goal_progress(session, goal.id) == 0
    await allocations_repo.allocate(session, goal.id, 400000)
    await allocations_repo.allocate(session, goal.id, 70000)
    assert await goals_repo.get_goal_progress(session, goal.id) == 470000


async def test_delete_goal_removes_allocations(session: AsyncSession) -> None:
    await savings_repo.add_to_savings(session, 1, 500000)
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)
    await allocations_repo.allocate(session, goal.id, 400000)

    assert await goals_repo.delete_goal(session, 1, goal.id) is True
    # связи удалены — деньги вернулись в свободные копилки
    assert await allocations_repo.get_allocations_by_goal(session, goal.id) == []
    assert await goals_repo.get_goals(session, 1) == []
    assert await savings_repo.get_free_in_savings(session, 1) == 500000

    assert await goals_repo.delete_goal(session, 1, goal.id) is False


# --- 4.2 /goals: список и кнопки ---------------------------------------------


async def test_goals_empty_shows_add_button_only(
    send_message: Send, bot: object
) -> None:
    text = (await send_message("/goals"))[0]
    assert "нет целей" in text
    labels = _button_labels(bot)
    assert "➕ Добавить цель" in labels
    assert "💰 Распределить" not in labels
    assert "✏️ Редактировать" not in labels
    assert "🗑 Удалить" not in labels


async def test_goals_shows_list_and_buttons(
    send_message: Send, session: AsyncSession, bot: object
) -> None:
    await savings_repo.add_to_savings(session, 1, 550000)
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, "2027-12-01", 1)
    await allocations_repo.allocate(session, goal.id, 400000)
    await goals_repo.add_goal(session, 1, "Подушка", 300000, "2027-06-01", 2)

    text = (await send_message("/goals"))[0]
    assert "Твои цели:" in text
    assert "1. 🚗 Машина: 400 000 / 1 500 000 ₽ (27%)" in text
    assert "   Срок: 01.12.2027" in text
    assert "   Нужно в месяц:" in text
    assert "2. 🛟 Подушка: 0 / 300 000 ₽ (0%)" in text
    assert "Итого закреплено: 400 000 ₽" in text

    labels = _button_labels(bot)
    assert "➕ Добавить цель" in labels
    assert "💰 Распределить" in labels
    assert "✏️ Редактировать" in labels
    assert "🗑 Удалить" in labels


# --- 4.3 добавление цели -----------------------------------------------------


async def test_goals_add_flow(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await send_message("/goals")
    replies = await send_callback("goals:add")
    assert "Название цели?" in replies[0]
    await send_message("Машина")
    await send_message("1500000")
    await send_message("01.12.2027")
    replies = await send_callback("goal_priority:1")
    assert "Цель добавлена: Машина — 1 500 000 ₽ до 01.12.2027" in replies[0]

    goals = await goals_repo.get_goals(session, 1)
    assert len(goals) == 1
    assert goals[0].name == "Машина"
    assert goals[0].target == 1500000
    assert goals[0].deadline == "2027-12-01"
    assert goals[0].priority == 1


async def test_goals_add_skip_deadline(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await send_message("/goals")
    await send_callback("goals:add")
    await send_message("Подушка")
    await send_message("300000")
    await send_message("skip")
    replies = await send_callback("goal_priority:3")
    assert "Цель добавлена: Подушка — 300 000 ₽" in replies[0]
    assert " до " not in replies[0]

    goals = await goals_repo.get_goals(session, 1)
    assert goals[0].deadline is None


async def test_goals_add_invalid_deadline(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await send_message("/goals")
    await send_callback("goals:add")
    await send_message("Машина")
    await send_message("1500000")
    replies = await send_message("завтра")
    assert "Не понял срок" in replies[0]
    assert await goals_repo.get_goals(session, 1) == []


# --- 4.4 редактирование цели --------------------------------------------------


async def test_goals_edit_shows_list_and_fields(
    send_message: Send, send_callback: Press, session: AsyncSession, bot: object
) -> None:
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, "2027-12-01", 1)

    replies = await send_callback("goals:edit")
    assert "Выбери цель для редактирования:" in replies[0]
    labels = _button_labels(bot)
    assert "1. Машина" in labels
    assert "❌ Отмена" in labels

    replies = await send_callback(f"goal_edit:{goal.id}")
    assert "Что изменить?" in replies[0]
    labels = _button_labels(bot)
    assert "Название" in labels
    assert "Сумма" in labels
    assert "Срок" in labels
    assert "Приоритет" in labels
    assert "❌ Отмена" in labels


async def test_goals_edit_name(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, "2027-12-01", 1)

    await send_callback("goals:edit")
    await send_callback(f"goal_edit:{goal.id}")
    replies = await send_callback("goal_field:name")
    assert "Новое название?" in replies[0]
    replies = await send_message("Авто")
    assert "Цель обновлена: Авто — 1 500 000 ₽ до 01.12.2027" in replies[0]

    session.expire_all()
    stored = (await goals_repo.get_goals(session, 1))[0]
    assert stored.name == "Авто"


async def test_goals_edit_target_and_deadline(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, "2027-12-01", 1)

    await send_callback("goals:edit")
    await send_callback(f"goal_edit:{goal.id}")
    await send_callback("goal_field:target")
    await send_message("2000000")
    session.expire_all()
    stored = (await goals_repo.get_goals(session, 1))[0]
    assert stored.target == 2000000

    await send_callback("goals:edit")
    await send_callback(f"goal_edit:{goal.id}")
    await send_callback("goal_field:deadline")
    replies = await send_message("skip")
    assert "Цель обновлена: Машина — 2 000 000 ₽" in replies[0]
    assert " до " not in replies[0]

    session.expire_all()
    stored = (await goals_repo.get_goals(session, 1))[0]
    assert stored.deadline is None


async def test_goals_edit_priority(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)

    await send_callback("goals:edit")
    await send_callback(f"goal_edit:{goal.id}")
    replies = await send_callback("goal_field:priority")
    assert "Приоритет цели?" in replies[0]
    replies = await send_callback("goal_priority:2")
    assert "Цель обновлена: Машина — 1 500 000 ₽" in replies[0]

    session.expire_all()
    stored = (await goals_repo.get_goals(session, 1))[0]
    assert stored.priority == 2


async def test_goals_edit_cancel(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)
    replies = await send_callback("goals_edit:cancel")
    assert "Отменено" in replies[0]
    stored = (await goals_repo.get_goals(session, 1))[0]
    assert stored.name == "Машина"


# --- 4.5 удаление цели --------------------------------------------------------


async def test_goals_delete_flow(
    send_message: Send, send_callback: Press, session: AsyncSession, bot: object
) -> None:
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)

    replies = await send_callback("goals:del")
    assert "Выбери цель для удаления:" in replies[0]
    labels = _button_labels(bot)
    assert "1. Машина" in labels
    assert "❌ Отмена" in labels

    replies = await send_callback(f"goal_del:{goal.id}")
    assert "Цель удалена: Машина" in replies[0]
    assert "Связи сняты, деньги вернулись в свободные копилки." in replies[0]
    assert await goals_repo.get_goals(session, 1) == []


async def test_goals_delete_returns_money_to_free(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await savings_repo.add_to_savings(session, 1, 500000)
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)
    await allocations_repo.allocate(session, goal.id, 400000)
    goal_id = goal.id
    session.expire_all()

    await send_callback(f"goal_del:{goal_id}")

    session.expire_all()
    assert await goals_repo.get_goals(session, 1) == []
    assert await savings_repo.get_free_in_savings(session, 1) == 500000


async def test_goals_delete_cancel(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)
    replies = await send_callback("goals_del:cancel")
    assert "Отменено" in replies[0]
    assert len(await goals_repo.get_goals(session, 1)) == 1


async def test_goals_delete_not_found(
    send_message: Send, send_callback: Press
) -> None:
    replies = await send_callback("goal_del:999")
    assert "Цель не найдена" in replies[0]


async def test_goals_edit_delete_when_empty(
    send_message: Send, send_callback: Press
) -> None:
    assert "нет целей" in (await send_callback("goals:edit"))[0]
    assert "нет целей" in (await send_callback("goals:del"))[0]