"""Тесты команд /minus, /plus, /correct и /stats (Фаза 2)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from services import accounts_repo

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]


async def _onboard(send_message: Send, send_callback: Press) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("12000")
    await send_callback("onboarding:income_fixed")
    await send_callback("onboarding:times_1")
    await send_message("10, 50000")


async def test_minus_updates_balance(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/minus 5000")
    assert "Записал: −5 000 ₽" in replies[0]
    assert "Свободно: 7 000 ₽" in replies[0]

    assert await accounts_repo.get_balance(session, 1, "card") == 7000


async def test_minus_records_expense(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/minus 5000")

    from services import transactions_repo

    last = await transactions_repo.get_last_transactions(session, 1, 1)
    assert len(last) == 1
    assert last[0].type == "expense"
    assert last[0].amount == 5000


async def test_plus_updates_balance(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/plus 100000")
    assert "Записал: +100 000 ₽" in replies[0]
    assert "Свободно: 112 000 ₽" in replies[0]

    assert await accounts_repo.get_balance(session, 1, "card") == 112000


async def test_plus_records_income(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/plus 100000")

    from services import transactions_repo

    last = await transactions_repo.get_last_transactions(session, 1, 1)
    assert last[0].type == "income"
    assert last[0].amount == 100000


async def test_minus_without_argument_sends_force_reply(
    send_message: Send, send_callback: Press, bot: object
) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/minus")
    assert "Напиши сумму траты" in replies[0]

    from aiogram.types import ForceReply

    assert isinstance(bot.session.last_reply_markup, ForceReply)  # type: ignore[attr-defined]


async def test_plus_without_argument_sends_force_reply(
    send_message: Send, send_callback: Press, bot: object
) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/plus")
    assert "Напиши сумму дохода" in replies[0]

    from aiogram.types import ForceReply

    assert isinstance(bot.session.last_reply_markup, ForceReply)  # type: ignore[attr-defined]


async def test_minus_force_reply_flow(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/minus")
    replies = await send_message("3000")
    assert "Записал: −3 000 ₽" in replies[0]

    assert await accounts_repo.get_balance(session, 1, "card") == 9000


async def test_plus_force_reply_flow(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/plus")
    replies = await send_message("50000")
    assert "Записал: +50 000 ₽" in replies[0]

    assert await accounts_repo.get_balance(session, 1, "card") == 62000


async def test_minus_invalid_amount(send_message: Send, send_callback: Press) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/minus abc")
    assert "Не понял сумму" in replies[0]


async def test_minus_unicode_minus(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/minus −1000")
    assert await accounts_repo.get_balance(session, 1, "card") == 11000


async def test_minus_negative_balance_warns(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/minus 999999")
    assert any("баланс ушёл в минус" in text for text in replies)


async def test_correct_updates_balance(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/correct 12000")
    assert "Баланс обновлён: 12 000 ₽" in replies[0]

    assert await accounts_repo.get_balance(session, 1, "card") == 12000


async def test_correct_records_difference(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/correct 20000")

    from services import transactions_repo

    last = await transactions_repo.get_last_transactions(session, 1, 1)
    assert last[0].type == "correction"
    assert last[0].amount == 8000  # 20000 − 12000


async def test_correct_without_argument_sends_force_reply(
    send_message: Send, send_callback: Press, bot: object
) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/correct")
    assert "новую сумму" in replies[0]

    from aiogram.types import ForceReply

    assert isinstance(bot.session.last_reply_markup, ForceReply)  # type: ignore[attr-defined]


async def test_stats_shows_balance_income_and_operations(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/minus 5000")
    await send_message("/plus 100000")

    replies = await send_message("/stats")
    text = replies[0]
    assert "*Свободно:* 107 000 ₽" in text
    assert "Доход:" in text
    assert "10 числа — 50 000 ₽" in text
    assert "*Последние операции:*" in text
    assert "−5 000 ₽ (сегодня)" in text
    assert "+100 000 ₽ (сегодня)" in text


async def test_stats_shows_period_balance(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/minus 5000")
    await send_message("/plus 30800")

    text = (await send_message("/stats"))[0]
    assert "*За сегодня:* +25 800 ₽" in text
    assert "*За неделю:* +25 800 ₽" in text
    assert "*За месяц:* +25 800 ₽" in text


async def test_stats_shows_period_sums(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/minus 5000")
    await send_message("/minus 1500")

    text = (await send_message("/stats"))[0]
    assert "*За сегодня:* −6 500 ₽" in text
    assert "*За неделю:* −6 500 ₽" in text
    assert "*За месяц:* −6 500 ₽" in text


async def test_stats_hides_operations_when_empty(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    text = (await send_message("/stats"))[0]
    assert "*Свободно:* 12 000 ₽" in text
    assert "*Последние операции:*" not in text
    assert "За сегодня:" not in text


async def test_stats_irregular_income_line(
    send_message: Send, send_callback: Press
) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("3000")
    await send_callback("onboarding:income_irregular")
    await send_message("90000")

    text = (await send_message("/stats"))[0]
    assert "*Доход:* нерегулярный" in text
    assert "Среднее в месяц: 90 000 ₽" in text


async def test_stats_fixed_income_sums_dates(
    send_message: Send, send_callback: Press
) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("10000")
    await send_callback("onboarding:income_fixed")
    await send_callback("onboarding:times_2")
    await send_message("10, 30000")
    await send_message("25, 20000")

    text = (await send_message("/stats"))[0]
    assert "Доход:" in text
    assert "10 числа — 30 000 ₽" in text
    assert "25 числа — 20 000 ₽" in text


async def test_stats_without_onboarding(send_message: Send) -> None:
    replies = await send_message("/stats")
    assert "Сначала пройди онбординг" in replies[0]
