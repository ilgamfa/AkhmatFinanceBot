"""Доход пользователя для сквозного прогноза платежей (Фаза 9.1).

Возвращает будущие поступления фиксированного дохода в окне дат. Если доход
нерегулярный или не задан — поступлений нет, прогноз считается только по
балансу карты.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from models import User
from models.base import IncomeType
from services import transactions_repo
from services.calculations import income_occurrences, parse_income_dates


async def get_income_events(
    session: AsyncSession,
    user: User,
    today: date,
    until: date,
) -> list[tuple[date, int]]:
    """Будущие поступления ``(дата, сумма)`` в окне ``today..until`` (вкл.).

    Учитывается только фиксированный доход (``income_type = fixed``).
    Сегодняшнее поступление пропускается, если за сегодня уже есть операция
    дохода (``/plus``): иначе оно было бы посчитано дважды — в балансе и в
    прогнозе.
    """
    if user.income_type != IncomeType.FIXED.value:
        return []
    entries = parse_income_dates(user.income_dates)
    if not entries:
        return []
    events = income_occurrences(entries, today, until)
    if await transactions_repo.has_income_today(session, user.telegram_id, today):
        events = [event for event in events if event[0] != today]
    return events
