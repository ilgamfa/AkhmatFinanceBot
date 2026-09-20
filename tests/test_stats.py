"""Тесты блоков «Копилка» и «Цели» в /stats (Фаза 4)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from services import allocations_repo, goals_repo, savings_repo

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]


async def _onboard(send_message: Send, send_callback: Press) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("12000")
    await send_callback("onboarding:income_fixed")
    await send_callback("onboarding:times_1")
    await send_message("10, 50000")


async def test_stats_shows_savings_and_goals(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await savings_repo.add_to_savings(session, 1, 550000)
    goal = await goals_repo.add_goal(session, 1, "Машина", 1500000, "2027-12-01", 1)
    await allocations_repo.allocate(session, goal.id, 400000)
    goal2 = await goals_repo.add_goal(session, 1, "Подушка", 300000, "2027-06-01", 2)
    await allocations_repo.allocate(session, goal2.id, 150000)

    text = (await send_message("/stats"))[0]
    assert "Копилка: 550 000 ₽" in text
    assert "Цели:" in text
    assert "🚗 Машина: 400 000 / 1 500 000 ₽ (27%)" in text
    assert "🛟 Подушка: 150 000 / 300 000 ₽ (50%)" in text


async def test_stats_hides_savings_and_goals_when_empty(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    text = (await send_message("/stats"))[0]
    assert "Копилка:" not in text
    assert "Цели:" not in text


async def test_stats_goals_without_savings(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    """Цели есть, копилки нет — блок копилки скрыт, цели показаны."""
    await _onboard(send_message, send_callback)
    await goals_repo.add_goal(session, 1, "Машина", 1500000, None, 1)

    text = (await send_message("/stats"))[0]
    assert "Копилка:" not in text
    assert "Цели:" in text
    assert "🚗 Машина: 0 / 1 500 000 ₽ (0%)" in text


async def test_stats_shows_savings_add_transaction(
    send_message: Send, send_callback: Press
) -> None:
    """Пополнение копилки пишется как «→ Копилка» и минус в сальдо."""
    await _onboard(send_message, send_callback)
    await send_message("/savings add 5000")

    text = (await send_message("/stats"))[0]
    assert "→ Копилка: 5 000 ₽ (сегодня)" in text
    assert "За сегодня: −5 000 ₽" in text