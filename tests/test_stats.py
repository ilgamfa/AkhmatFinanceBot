"""Тесты блоков «Копилка» и «Цели» в /stats (Фазы 4–5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from services import accounts_repo, allocations_repo, family_repo, goals_repo

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]


async def _onboard(send_message: Send, send_callback: Press) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("12000")
    await send_callback("onboarding:income_fixed")
    await send_callback("onboarding:times_1")
    await send_message("10, 50000")


async def _fund_savings(session: AsyncSession, telegram_id: int, amount: int) -> None:
    """Ставит баланс копилки пользователя."""
    savings = await accounts_repo.ensure_account(session, telegram_id, "savings")
    await accounts_repo.correct_balance(session, savings.id, amount)


async def test_stats_shows_savings_and_goals(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await _fund_savings(session, 1, 550000)
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, "2027-12-01", 1)
    await allocations_repo.allocate(session, goal.id, 400000, 1)
    goal2 = await goals_repo.add_goal(session, 1, "Подушка", 300000, "2027-06-01", 2)
    await allocations_repo.allocate(session, goal2.id, 150000, 1)

    text = (await send_message("/stats"))[0]
    assert "*Копилка:* 550 000 ₽" in text
    assert "*Цели:*" in text
    assert "🚗 Машина: 400 000 / 1 500 000 ₽ (27%)" in text
    assert "🛟 Подушка: 150 000 / 300 000 ₽ (50%)" in text


async def test_stats_hides_savings_and_goals_when_empty(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    text = (await send_message("/stats"))[0]
    assert "*Копилка:*" not in text
    assert "*Цели:*" not in text


async def test_stats_goals_without_savings(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    """Цели есть, копилки нет — блок копилки скрыт, цели показаны."""
    await _onboard(send_message, send_callback)
    await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)

    text = (await send_message("/stats"))[0]
    assert "*Копилка:*" not in text
    assert "*Цели:*" in text
    assert "🚗 Машина: 0 / 1 500 000 ₽ (0%)" in text


async def test_stats_shows_savings_add_transaction(
    send_message: Send, send_callback: Press
) -> None:
    """Пополнение копилки пишется как «→ Копилка» и минус в сальдо."""
    await _onboard(send_message, send_callback)
    await send_message("/savings add 5000")

    text = (await send_message("/stats"))[0]
    assert "→ Копилка: 5 000 ₽ (сегодня)" in text
    assert "*За сегодня:* −5 000 ₽" in text


# --- 5.4 семейная сводка ------------------------------------------------------


async def _onboard_user(
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
    await _onboard_user(send_message, send_callback, user_id=1, first_name="Илья")
    await _onboard_user(send_message, send_callback, user_id=2, first_name="Жена")
    await send_message("/family create", user_id=1, first_name="Илья")
    family = await family_repo.get_family(session, 1)
    assert family is not None
    await send_message(
        f"/family join {family.invite_code}", user_id=2, first_name="Жена"
    )


async def test_stats_family_summary(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _make_family(send_message, send_callback, session)
    await accounts_repo.correct_balance(
        session, (await accounts_repo.ensure_account(session, 1, "card")).id, 50000
    )
    await accounts_repo.correct_balance(
        session, (await accounts_repo.ensure_account(session, 2, "card")).id, 30000
    )
    # копилки обоих
    await accounts_repo.correct_balance(
        session,
        (await accounts_repo.ensure_account(session, 1, "savings")).id,
        300000,
    )
    await accounts_repo.correct_balance(
        session,
        (await accounts_repo.ensure_account(session, 2, "savings")).id,
        100000,
    )
    goal = await goals_repo.add_goal(session, 1, "Отпуск", 500000, None, 1)
    await allocations_repo.allocate(session, goal.id, 300000, 1)
    await allocations_repo.allocate(session, goal.id, 100000, 2)

    text = (await send_message("/stats"))[0]
    assert "*Семья: Наша семья*" in text
    assert "*Счета:*" in text
    assert "Карта (Илья): 50 000 ₽" in text
    assert "Копилка (Илья): 300 000 ₽" in text
    assert "Карта (Жена): 30 000 ₽" in text
    assert "Копилка (Жена): 100 000 ₽" in text
    assert "*Свободно:*" in text
    assert "Илья: 50 000 ₽" in text
    assert "Жена: 30 000 ₽" in text
    assert "Итого: 80 000 ₽" in text
    assert "✈️ Отпуск: 400 000 / 500 000 ₽ (80%)" in text


async def test_stats_family_shows_both_members_operations(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _make_family(send_message, send_callback, session)
    await accounts_repo.correct_balance(
        session, (await accounts_repo.ensure_account(session, 1, "card")).id, 50000
    )
    await accounts_repo.correct_balance(
        session, (await accounts_repo.ensure_account(session, 2, "card")).id, 30000
    )

    await send_message("/minus 3000", user_id=1, first_name="Илья")
    await send_message("/plus 50000", user_id=2, first_name="Жена")

    text = (await send_message("/stats", user_id=1, first_name="Илья"))[0]
    assert "*Последние операции:*" in text
    assert "−3 000 ₽ (Илья, сегодня)" in text
    assert "+50 000 ₽ (Жена, сегодня)" in text
    assert "*За месяц:*" in text

    partner_text = (await send_message("/stats", user_id=2, first_name="Жена"))[0]
    assert "−3 000 ₽ (Илья, сегодня)" in partner_text
    assert "+50 000 ₽ (Жена, сегодня)" in partner_text


# --- форматирование Markdown -------------------------------------------------


async def test_stats_bold_headers_and_parse_mode(
    send_message: Send, send_callback: Press, bot: object
) -> None:
    """Заголовки блоков выделены жирным, сообщение уходит с parse_mode."""
    await _onboard(send_message, send_callback)
    await send_message("/minus 5000")

    text = (await send_message("/stats"))[0]
    assert text.startswith("*Свободно:*")
    assert "*Доход:*" in text
    assert "*Последние операции:*" in text
    assert "*За сегодня:* −5 000 ₽" in text

    assert bot.session.sent[-1].parse_mode == "Markdown"  # type: ignore[attr-defined]


async def test_stats_escapes_markdown_in_goal_name(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    """Спецсимволы Markdown в названии цели экранируются."""
    await _onboard(send_message, send_callback)
    await goals_repo.add_goal(session, 1, "Подушка_2", 300000, None, 1)

    text = (await send_message("/stats"))[0]
    assert "🎯 Подушка\\_2: 0 / 300 000 ₽ (0%)" in text
