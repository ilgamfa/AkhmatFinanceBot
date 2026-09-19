"""Тесты долгов и /stats Фазы 3."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from services import debts_repo, users_repo

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]


async def _onboard(send_message: Send, send_callback: Press) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("12000")
    await send_callback("onboarding:income_fixed")
    await send_callback("onboarding:times_1")
    await send_message("10, 50000")


async def _add_debt(
    send_message: Send,
    send_callback: Press,
    name: str = "Кредит",
    amount: str = "46000",
    day: str = "25",
    debt_type: str = "loan",
) -> None:
    await send_message("/debts add")
    await send_message(name)
    await send_callback(f"debt_type:{debt_type}")
    await send_message(amount)
    await send_message(day)


# --- 3.1 репозиторий ---------------------------------------------------------


async def test_add_debt(session: AsyncSession) -> None:
    debt = await debts_repo.add_debt(session, 1, "Кредит", "loan", 46000, 25)
    assert debt.id is not None
    assert debt.telegram_id == 1
    assert debt.type == "loan"
    assert debt.amount == 46000
    assert debt.payment_day == 25
    assert debt.created_at


async def test_get_debts(session: AsyncSession) -> None:
    await debts_repo.add_debt(session, 1, "Кредит", "loan", 46000, 25)
    await debts_repo.add_debt(session, 1, "Ипотека", "mortgage", 61000, 30)
    await debts_repo.add_debt(session, 2, "Чужой", "loan", 1, 1)

    debts = await debts_repo.get_debts(session, 1)
    assert [debt.name for debt in debts] == ["Кредит", "Ипотека"]


async def test_delete_debt(session: AsyncSession) -> None:
    debt = await debts_repo.add_debt(session, 1, "Кредит", "loan", 46000, 25)
    assert await debts_repo.delete_debt(session, 1, debt.id) is True
    assert await debts_repo.get_debts(session, 1) == []
    assert await debts_repo.delete_debt(session, 1, debt.id) is False


async def test_get_upcoming_payments(session: AsyncSession) -> None:
    await debts_repo.add_debt(session, 1, "Кредит", "loan", 46000, 25)
    await debts_repo.add_debt(session, 1, "Кредитка", "credit_card", 8000, 5)

    payments = await debts_repo.get_upcoming_payments(
        session, 1, 30, today=date(2026, 9, 20)
    )
    assert [(day, debt.name) for day, debt in payments] == [
        (date(2026, 9, 25), "Кредит"),
        (date(2026, 10, 5), "Кредитка"),
    ]


async def test_get_upcoming_payments_short_window(session: AsyncSession) -> None:
    await debts_repo.add_debt(session, 1, "Кредит", "loan", 46000, 25)
    payments = await debts_repo.get_upcoming_payments(
        session, 1, 3, today=date(2026, 9, 20)
    )
    assert payments == []


# --- 3.2 /debts --------------------------------------------------------------


async def test_debts_empty(send_message: Send, send_callback: Press) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/debts")
    assert "нет долгов" in replies[0]


async def test_debts_shows_list_and_total(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    await _add_debt(send_message, send_callback, "Кредит", "46000", "25")
    await _add_debt(
        send_message, send_callback, "Ипотека", "61000", "30", "mortgage"
    )

    text = (await send_message("/debts"))[0]
    assert "1. Кредит — 46 000 ₽, 25 числа" in text
    assert "2. Ипотека — 61 000 ₽, 30 числа" in text
    assert "Итого в месяц: 107 000 ₽" in text


# --- 3.3 add / del -----------------------------------------------------------


async def test_debts_add_flow(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/debts add")
    await send_message("Кредитка")
    await send_callback("debt_type:credit_card")
    await send_message("8000")
    replies = await send_message("5")
    assert "Долг добавлен: Кредитка — 8 000 ₽, 5 числа" in replies[0]

    debts = await debts_repo.get_debts(session, 1)
    assert len(debts) == 1
    assert debts[0].type == "credit_card"
    assert debts[0].payment_day == 5


async def test_debts_del(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await _add_debt(send_message, send_callback)
    debt = (await debts_repo.get_debts(session, 1))[0]

    replies = await send_message(f"/debts del {debt.id}")
    assert "Долг удалён" in replies[0]
    assert await debts_repo.get_debts(session, 1) == []


async def test_debts_del_not_found(send_message: Send, send_callback: Press) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/debts del 999")
    assert "не найден" in replies[0]


async def test_debts_add_invalid_day(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/debts add")
    await send_message("Кредит")
    await send_callback("debt_type:loan")
    await send_message("1000")
    replies = await send_message("99")
    assert "от 1 до 31" in replies[0]
    assert await debts_repo.get_debts(session, 1) == []


# --- 3.4 /stats --------------------------------------------------------------


async def test_stats_shows_upcoming_payments(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    await _add_debt(send_message, send_callback, "Кредит", "46000", "25")

    text = (await send_message("/stats"))[0]
    assert "Ближайшие платежи:" in text
    assert "— Кредит: 46 000 ₽" in text


async def test_stats_no_debts_hides_payments(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    text = (await send_message("/stats"))[0]
    assert "Ближайшие платежи:" not in text
    assert "Свободно до ЗП:" not in text
    assert "Свободно до конца месяца:" not in text


async def test_stats_free_until_month_end(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    await _add_debt(send_message, send_callback, "Кредит", "46000", "25")

    text = (await send_message("/stats"))[0]
    assert "Свободно до ЗП:" in text
    assert "Свободно до конца месяца:" in text


async def test_stats_full_format(
    send_message: Send, send_callback: Press
) -> None:
    """Полный формат /stats: доход, платежи, свободно до, операции, сальдо."""
    await _onboard(send_message, send_callback)
    await _add_debt(send_message, send_callback, "Кредит", "46000", "25")
    await send_message("/plus 100000")
    await send_message("/minus 4200")

    text = (await send_message("/stats"))[0]
    blocks = text.split("\n\n")
    assert "Свободно: 107 800 ₽" in text
    assert "Доход:\n10 числа — 50 000 ₽" in text
    assert "Ближайшие платежи:\n" in text
    assert "— Кредит: 46 000 ₽" in text
    assert "Свободно до ЗП:" in text
    assert "Свободно до конца месяца:" in text
    assert "Последние операции:" in text
    assert "−4 200 ₽ (сегодня)" in text
    assert "+100 000 ₽ (сегодня)" in text
    assert "За сегодня: +95 800 ₽" in text
    assert blocks[-1].startswith("За сегодня:")


async def test_stats_irregular_hides_until_salary(
    send_message: Send, send_callback: Press
) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("5000")
    await send_callback("onboarding:income_irregular")
    await send_message("90000")
    await _add_debt(send_message, send_callback, "Кредит", "46000", "25")

    text = (await send_message("/stats"))[0]
    assert "Свободно до ЗП:" not in text
    assert "Свободно до конца месяца:" in text
    assert "Доход: нерегулярный" in text
    assert "Среднее в месяц: 90 000 ₽" in text


# --- 3.5 /refresh ------------------------------------------------------------


async def test_refresh_asks_confirmation(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    replies = await send_message("/refresh")
    assert "Точно сбросить" in replies[0]


async def test_refresh_no_cancels(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/refresh")
    replies = await send_callback("refresh:no")
    assert "Отменено" in replies[0]
    assert await users_repo.get_by_telegram_id(session, 1) is not None


async def test_refresh_yes_resets_and_restarts(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await _add_debt(send_message, send_callback)
    await send_message("/minus 1000")

    await send_message("/refresh")
    replies = await send_callback("refresh:yes")
    assert "карманный финсоветник" in replies[0]

    assert await users_repo.get_by_telegram_id(session, 1) is None
    assert await debts_repo.get_debts(session, 1) == []
