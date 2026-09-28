"""Планировщик напоминаний (Фаза 8).

Каждую минуту проверяет, у кого наступило время напоминания, и отправляет
его. Часовой пояс — Europe/Moscow. Повторная отправка в тот же день
исключается полями ``reminder_*_last_sent``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from models.database import Database
from services import accounts_repo, reminder_service, reminders_repo

logger = logging.getLogger(__name__)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

EVENING_JOB_ID = "reminder_evening"
PAYMENT_JOB_ID = "reminder_payment"
# Раз в минуту; допускаем небольшое опоздание, чтобы не терять тик.
TICK_MISFIRE_GRACE_SECONDS = 30


def build_scheduler(database: Database, bot: Bot) -> AsyncIOScheduler:
    """Создаёт планировщик с вечерней и платёжной задачами (раз в минуту)."""
    scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)
    for job, job_id in (
        (evening_job, EVENING_JOB_ID),
        (payment_job, PAYMENT_JOB_ID),
    ):
        scheduler.add_job(
            job,
            "cron",
            minute="*",
            args=[database, bot],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=TICK_MISFIRE_GRACE_SECONDS,
            coalesce=True,
        )
    return scheduler


async def _send(bot: Bot, telegram_id: int, text: str) -> None:
    """Отправляет сообщение, не роняя задачу из-за одного получателя."""
    try:
        await bot.send_message(telegram_id, text)
    except Exception:
        logger.exception("Не удалось отправить напоминание для %s", telegram_id)


async def evening_job(
    database: Database, bot: Bot, now: datetime | None = None
) -> None:
    """Вечернее напоминание тем, у кого время совпало с текущей минутой MSK."""
    moment = reminder_service.now_moscow(now)
    today = moment.date()
    current = moment.strftime("%H:%M")

    async with database.session_factory() as session:
        users = await reminders_repo.get_users_for_evening_reminder(session)
        for user in users:
            if user.reminder_evening_time != current:
                continue
            if not await reminder_service.check_evening_reminder(
                session, user, today
            ):
                continue
            await _send(
                bot, user.telegram_id, reminder_service.compose_evening_text()
            )
            await reminders_repo.mark_evening_sent(session, user, today)


async def payment_job(
    database: Database, bot: Bot, now: datetime | None = None
) -> None:
    """Напоминание о платежах, срок которых наступит через N дней."""
    moment = reminder_service.now_moscow(now)
    today = moment.date()
    current = moment.strftime("%H:%M")

    async with database.session_factory() as session:
        users = await reminders_repo.get_users_for_payment_reminder(session)
        for user in users:
            if user.reminder_payment_time != current:
                continue
            if user.reminder_payment_last_sent == today:
                continue
            pairs = await reminder_service.get_upcoming_payments(
                session,
                user.telegram_id,
                user.reminder_payment_days_before,
                today,
            )
            if not pairs:
                continue
            free = await accounts_repo.get_balance(
                session, user.telegram_id, "card"
            )
            text = reminder_service.compose_payment_text(
                user.reminder_payment_days_before, free, pairs
            )
            await _send(bot, user.telegram_id, text)
            await reminders_repo.mark_payment_sent(session, user, today)
