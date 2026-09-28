"""Тесты напоминаний Фазы 8: репозиторий, сервис, планировщик и хендлеры."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta

from scheduler import evening_job, payment_job
from services import (
    accounts_repo,
    debts_repo,
    reminder_service,
    reminders_repo,
    transactions_repo,
    users_repo,
)
from services.reminder_service import MOSCOW_TZ

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]


async def _complete_onboarding(
    send_message: Send, send_callback: Press
) -> list[str]:
    """Проходит онбординг до конца и возвращает ответы последнего шага."""
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("50000")
    await send_message("Т-Банк")
    await send_callback("onboarding:income_fixed")
    await send_callback("onboarding:times_1")
    return await send_message("10, 80000")


# --- репозиторий --------------------------------------------------------------


async def test_get_reminder_settings_defaults(session: object) -> None:
    settings = await reminders_repo.get_reminder_settings(session, 999)  # type: ignore[arg-type]
    assert settings.evening_enabled is True
    assert settings.evening_time == "21:00"
    assert settings.payment_enabled is True
    assert settings.payment_time == "10:00"
    assert settings.payment_days_before == 1


async def test_update_reminder_settings(session: object) -> None:
    await reminders_repo.update_reminder_settings(
        session,  # type: ignore[arg-type]
        1,
        reminder_evening_time="9:30",
        reminder_payment_enabled=False,
        reminder_payment_days_before="3",
    )
    settings = await reminders_repo.get_reminder_settings(session, 1)  # type: ignore[arg-type]
    assert settings.evening_time == "09:30"
    assert settings.payment_enabled is False
    assert settings.payment_days_before == 3


async def test_get_users_filters_disabled_and_not_onboarded(
    session: object,
) -> None:
    ready = await users_repo.get_or_create(session, 1)  # type: ignore[arg-type]
    await users_repo.skip_onboarding(session, ready)  # type: ignore[arg-type]
    await users_repo.get_or_create(session, 2)  # type: ignore[arg-type]
    await reminders_repo.update_reminder_settings(
        session, 3, reminder_evening_enabled=False  # type: ignore[arg-type]
    )
    await users_repo.skip_onboarding(
        session, await users_repo.get_or_create(session, 3)  # type: ignore[arg-type]
    )

    users = await reminders_repo.get_users_for_evening_reminder(session)  # type: ignore[arg-type]
    assert [user.telegram_id for user in users] == [1]


# --- сервис -------------------------------------------------------------------


async def test_evening_reminder_skipped_when_transaction_exists(
    session: object,
) -> None:
    user = await users_repo.get_or_create(session, 1)  # type: ignore[arg-type]
    await users_repo.skip_onboarding(session, user)  # type: ignore[arg-type]
    await transactions_repo.add_transaction(  # type: ignore[arg-type]
        session, 1, "expense", 500
    )
    today = reminder_service.moscow_today()
    assert await reminder_service.check_evening_reminder(  # type: ignore[arg-type]
        session, user, today
    ) is False


async def test_evening_reminder_sent_without_transactions(
    session: object,
) -> None:
    user = await users_repo.get_or_create(session, 1)  # type: ignore[arg-type]
    await users_repo.skip_onboarding(session, user)  # type: ignore[arg-type]
    today = reminder_service.moscow_today()
    assert await reminder_service.check_evening_reminder(  # type: ignore[arg-type]
        session, user, today
    ) is True


async def test_upcoming_payments_only_due_and_pending(session: object) -> None:
    today = date(2026, 9, 28)
    debt = await debts_repo.create_debt(session, 1, "Кредит")  # type: ignore[arg-type]
    await debts_repo.add_payment(  # type: ignore[arg-type]
        session, debt.id, 46000, today + timedelta(days=1)
    )
    paid = await debts_repo.add_payment(  # type: ignore[arg-type]
        session, debt.id, 1000, today + timedelta(days=1)
    )
    await debts_repo.mark_paid(session, paid.id)  # type: ignore[arg-type]

    pairs = await reminder_service.get_upcoming_payments(session, 1, 1, today)  # type: ignore[arg-type]
    assert len(pairs) == 1
    assert pairs[0][1].name == "Кредит"
    assert pairs[0][0].amount == 46000


async def test_compose_payment_text_verdict(session: object) -> None:
    today = date(2026, 9, 28)
    debt = await debts_repo.create_debt(session, 1, "Кредит")  # type: ignore[arg-type]
    payment = await debts_repo.add_payment(  # type: ignore[arg-type]
        session, debt.id, 46000, today + timedelta(days=1)
    )
    text = reminder_service.compose_payment_text(1, 50000, [(payment, debt)])
    assert "Завтра" in text
    assert "Кредит" in text
    assert "46 000 ₽" in text
    assert "хватает ✅" in text


# --- планировщик --------------------------------------------------------------


async def test_evening_job_sends_once_per_day(database: object, bot: object) -> None:
    async with database.session_factory() as setup:  # type: ignore[attr-defined]
        user = await users_repo.get_or_create(setup, 1)
        await users_repo.skip_onboarding(setup, user)
        await reminders_repo.update_reminder_settings(
            setup, 1, reminder_evening_time="21:00"
        )

    now = datetime(2026, 9, 28, 21, 0, tzinfo=MOSCOW_TZ)
    await evening_job(database, bot, now)  # type: ignore[arg-type]
    await evening_job(database, bot, now)  # type: ignore[arg-type]
    assert len(bot.session.sent) == 1  # type: ignore[attr-defined]


async def test_evening_job_skips_when_transaction_exists(
    database: object, bot: object
) -> None:
    async with database.session_factory() as setup:  # type: ignore[attr-defined]
        user = await users_repo.get_or_create(setup, 1)
        await users_repo.skip_onboarding(setup, user)
        await reminders_repo.update_reminder_settings(
            setup, 1, reminder_evening_time="21:00"
        )
        await transactions_repo.add_transaction(setup, 1, "expense", 100)

    now = datetime(2026, 9, 28, 21, 0, tzinfo=MOSCOW_TZ)
    await evening_job(database, bot, now)  # type: ignore[arg-type]
    assert bot.session.sent == []  # type: ignore[attr-defined]


async def test_payment_job_sends_verdict(database: object, bot: object) -> None:
    async with database.session_factory() as setup:  # type: ignore[attr-defined]
        user = await users_repo.get_or_create(setup, 1)
        await users_repo.skip_onboarding(setup, user)
        await accounts_repo.create_accounts(setup, 1, card_balance=50000)
        await reminders_repo.update_reminder_settings(
            setup, 1, reminder_payment_time="10:00", reminder_payment_days_before=1
        )
        debt = await debts_repo.create_debt(setup, 1, "Кредит")
        await debts_repo.add_payment(setup, debt.id, 46000, date(2026, 9, 29))

    now = datetime(2026, 9, 28, 10, 0, tzinfo=MOSCOW_TZ)
    await payment_job(database, bot, now)  # type: ignore[arg-type]
    assert len(bot.session.sent) == 1  # type: ignore[attr-defined]
    text = bot.session.sent[0].text  # type: ignore[attr-defined]
    assert "Завтра" in text and "46 000 ₽" in text and "хватает ✅" in text


# --- команда /reminders -------------------------------------------------------


async def test_reminders_shows_settings(
    send_message: Send, send_callback: Press
) -> None:
    await _complete_onboarding(send_message, send_callback)
    replies = await send_message("/reminders")
    assert any("Настройки уведомлений" in reply for reply in replies)
    assert any("21:00" in reply for reply in replies)


async def test_reminders_changes_time(
    send_message: Send, send_callback: Press, session: object
) -> None:
    await _complete_onboarding(send_message, send_callback)
    await send_message("/reminders")
    await send_callback("reminders:edit_evening")
    replies = await send_message("09:30")
    assert any("09:30" in reply for reply in replies)
    settings = await reminders_repo.get_reminder_settings(session, 1)  # type: ignore[arg-type]
    assert settings.evening_time == "09:30"


async def test_reminders_rejects_invalid_time(
    send_message: Send, send_callback: Press
) -> None:
    await _complete_onboarding(send_message, send_callback)
    await send_message("/reminders")
    await send_callback("reminders:edit_evening")
    replies = await send_message("вечером")
    assert "формате 21:00" in replies[0]


async def test_reminders_toggle_disables(
    send_message: Send, send_callback: Press, session: object
) -> None:
    await _complete_onboarding(send_message, send_callback)
    await send_message("/reminders")
    await send_callback("reminders:toggle_evening")
    settings = await reminders_repo.get_reminder_settings(session, 1)  # type: ignore[arg-type]
    assert settings.evening_enabled is False


# --- онбординг ----------------------------------------------------------------


async def test_onboarding_offers_reminders(
    send_message: Send, send_callback: Press
) -> None:
    final = await _complete_onboarding(send_message, send_callback)
    assert any("напоминал" in reply for reply in final)
