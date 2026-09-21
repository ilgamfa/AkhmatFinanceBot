"""Тесты FSM-онбординга (кнопочный флоу)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from services import accounts_repo, users_repo

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]


async def test_intro_has_buttons(send_message: Send) -> None:
    replies = await send_message("/start")
    assert len(replies) == 1
    assert "3 вопроса" in replies[0]


async def test_later_skips_onboarding(
    send_message: Send, send_callback: Press, session: object
) -> None:
    await send_message("/start")
    replies = await send_callback("onboarding:later")
    assert "вернёшься" in replies[0]


async def test_fixed_single_income(
    send_message: Send, send_callback: Press, session: object
) -> None:
    await send_message("/start")
    started = await send_callback("onboarding:start")
    assert "на картах" in started[0]

    ask_kind = await send_message("50000")
    assert "устроен доход" in ask_kind[0]

    ask_times = await send_callback("onboarding:income_fixed")
    assert "раз в месяц" in ask_times[0]

    ask_date = await send_callback("onboarding:times_1")
    assert "Напиши дату и сумму" in ask_date[0]

    final = await send_message("10, 80000")
    assert "Готово" in final[0]
    assert "/stats" in final[0]


async def test_fixed_double_income(
    send_message: Send, send_callback: Press
) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("10000")
    await send_callback("onboarding:income_fixed")
    asked_first = await send_callback("onboarding:times_2")
    assert "первую дату" in asked_first[0]

    asked_second = await send_message("10, 30000")
    assert "вторую дату" in asked_second[0]

    final = await send_message("25, 20000")
    assert "Готово" in final[0]


async def test_irregular_income(
    send_message: Send, send_callback: Press
) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("5000")
    asked = await send_callback("onboarding:income_irregular")
    assert "в среднем" in asked[0]

    final = await send_message("70000")
    assert "Готово" in final[0]


async def test_invalid_money_rejected(
    send_message: Send, send_callback: Press
) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    replies = await send_message("abc")
    assert "Не понял сумму" in replies[0]


async def test_invalid_date_amount_rejected(
    send_message: Send, send_callback: Press
) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("1000")
    await send_callback("onboarding:income_fixed")
    await send_callback("onboarding:times_1")
    replies = await send_message("99, 1000")
    assert "от 1 до 31" in replies[0]


async def test_cancel_stops_onboarding(
    send_message: Send, send_callback: Press
) -> None:
    await send_message("/start")
    replies = await send_message("/cancel")
    assert "Отменил" in replies[0]


async def test_full_profile_saved(
    send_message: Send, send_callback: Press, session: object
) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("50000")
    await send_callback("onboarding:income_fixed")
    await send_callback("onboarding:times_2")
    await send_message("10, 30000")
    await send_message("25, 20000")

    user = await users_repo.get_by_telegram_id(session, 1)  # type: ignore[arg-type]
    assert user is not None
    assert user.onboarding_completed is True
    assert await accounts_repo.get_balance(session, 1, "card") == 50000  # type: ignore[arg-type]
    assert user.income_type == "fixed"
    assert user.income_dates is not None
    assert "30000" in user.income_dates and "20000" in user.income_dates


async def test_irregular_profile_saved(
    send_message: Send, send_callback: Press, session: object
) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("5000")
    await send_callback("onboarding:income_irregular")
    await send_message("70000")

    user = await users_repo.get_by_telegram_id(session, 1)  # type: ignore[arg-type]
    assert user is not None
    assert user.income_type == "irregular"
    assert user.income == 70000
    assert user.income_dates is None
