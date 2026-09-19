"""Тесты блока «Цели» в /stats (Фаза 4)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from services import goals_repo

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]


async def _onboard(send_message: Send, send_callback: Press) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("12000")
    await send_callback("onboarding:income_fixed")
    await send_callback("onboarding:times_1")
    await send_message("10, 50000")


async def test_stats_shows_goals_block(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    goal = await goals_repo.add_goal(
        session, 1, "Машина", 1500000, "2027-12-01", 1
    )
    await goals_repo.update_goal_saved(session, 1, goal.id, 50000)

    text = (await send_message("/stats"))[0]
    assert "Цели:" in text
    assert "🚗 Машина: 50 000 / 1 500 000 ₽ (3%)" in text


async def test_stats_hides_goals_block_when_empty(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    text = (await send_message("/stats"))[0]
    assert "Цели:" not in text