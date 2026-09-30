"""Команда /forecast — прогноз на 1/3/6/12 месяцев (Фаза 9)."""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from handlers.stats import escape_markdown
from models import User
from models.base import IncomeType
from services import (
    accounts_repo,
    categories_repo,
    debts_repo,
    goals_repo,
    users_repo,
)
from services.calculations import (
    goal_emoji,
    goal_progress_percent,
    monthly_goal_amount,
    parse_income_dates,
)
from utils.money import format_amount, format_rubles

HORIZONS: tuple[tuple[int, str], ...] = (
    (1, "1"),
    (3, "3"),
    (6, "6"),
    (12, "12"),
)
HORIZON_MONTHS = frozenset(months for months, _ in HORIZONS)
CALLBACK_PREFIX = "forecast:"

PROMPT = "На какой срок посчитать прогноз? Выбери число месяцев."
NEED_ONBOARDING = "Сначала пройди онбординг: /start"

# Средние траты считаем по окну 90 дней и делим на 3 месяца.
AVG_WINDOW_DAYS = 90
AVG_MONTHS = 3
TOP_CATEGORIES = 3

_MONTH_WORDS = {1: "месяц", 3: "месяца", 6: "месяцев", 12: "месяцев"}


def _month_word(months: int) -> str:
    """Падеж слова «месяц» для заголовка и вердикта."""
    return _MONTH_WORDS.get(months, "месяцев")


def _signed(amount: int) -> str:
    """Сумма со знаком: минус — «−133 000 ₽» (U+2212)."""
    if amount < 0:
        return f"−{format_amount(abs(amount))}"
    return format_amount(amount)


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    """Сдвигает (год, месяц) на ``offset`` месяцев."""
    index = month - 1 + offset
    return year + index // 12, index % 12 + 1


def _clamp_date(year: int, month: int, day: int) -> date:
    """Дата с днём ``day``; если в месяце меньше дней — последний день."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def horizon_end(today: date, months: int) -> date:
    """Конец горизонта: ``today`` + ``months`` месяцев (день сохраняется)."""
    year, month = _shift_month(today.year, today.month, months)
    return _clamp_date(year, month, today.day)


def income_for_period(user: User, months: int, today: date) -> int:
    """Доход за период — только будущие поступления ``(today, end]``.

    Фиксированный: суммы ``income_dates``, чьи вхождения попадают в период.
    Нерегулярный: ``income`` × число месяцев.
    """
    if user.income_type == IncomeType.IRREGULAR.value:
        return (user.income or 0) * months

    end = horizon_end(today, months)
    total = 0
    for day, amount in parse_income_dates(user.income_dates):
        for offset in range(months + 1):
            year, month = _shift_month(today.year, today.month, offset)
            candidate = _clamp_date(year, month, day)
            if today < candidate <= end:
                total += amount
    return total


def _avg_window_start_iso(today: date) -> str:
    """Начало окна средних трат (90 дней назад) в ISO-UTC."""
    start = datetime(today.year, today.month, today.day, tzinfo=UTC) - timedelta(
        days=AVG_WINDOW_DAYS
    )
    return start.isoformat()


async def _average_monthly_expenses(
    session: AsyncSession, telegram_id: int, today: date
) -> tuple[list[tuple[str, int]], int]:
    """Траты по категориям за 3 месяца и среднее в месяц.

    Возвращает ``(top_rows, avg_monthly)``, где ``top_rows`` — строки топ-3.
    Пустой список — данных для расчёта нет.
    """
    rows = await categories_repo.get_expense_categories_since(
        session, telegram_id, _avg_window_start_iso(today)
    )
    if not rows:
        return [], 0
    avg_monthly = sum(amount for _, amount in rows) // AVG_MONTHS
    return rows[:TOP_CATEGORIES], avg_monthly


async def build_forecast_text(
    session: AsyncSession,
    user: User,
    months: int,
    today: date | None = None,
) -> str:
    """Собирает прогноз на ``months`` месяцев: карта, копилка, цели, траты."""
    today = today or datetime.now(UTC).date()
    end = horizon_end(today, months)

    card = await accounts_repo.get_balance(session, user.telegram_id, "card")
    savings = await accounts_repo.get_balance(session, user.telegram_id, "savings")
    income = income_for_period(user, months, today)

    pending = await debts_repo.get_pending_payments(
        session, user.telegram_id, today, end
    )
    debts_total = sum(payment.amount for payment, _ in pending)

    top_categories, avg_monthly = await _average_monthly_expenses(
        session, user.telegram_id, today
    )
    has_expenses = bool(top_categories)
    expenses_total = avg_monthly * months

    goals = await goals_repo.get_goals(session, user.telegram_id)
    progress = await goals_repo.get_progress_by_goals(
        session, [goal.id for goal in goals]
    )
    goals_total = 0
    goal_lines: list[str] = []
    for goal in goals:
        saved = progress.get(goal.id, 0)
        monthly = monthly_goal_amount(saved, goal.target, goal.deadline, today) or 0
        projected = min(saved + monthly * months, goal.target)
        goals_total += max(0, projected - saved)
        percent = goal_progress_percent(projected, goal.target)
        goal_lines.append(
            f"{goal_emoji(goal.name)} {escape_markdown(goal.name)}: "
            f"{format_rubles(projected)} / {format_rubles(goal.target)} ₽ "
            f"({percent}%)"
        )

    savings_end = savings + goals_total
    card_end = card + income - debts_total
    if has_expenses:
        card_end -= expenses_total

    word = _month_word(months)
    title = f"Прогноз на {months} {word}"
    if not has_expenses:
        title += " (только доходы и долги)"

    lines = [
        f"*{title}:*",
        "",
        "*Карта:*",
        f"Сейчас: {format_amount(card)}",
        f"Доход: {format_amount(income)}",
        f"Долги: {format_amount(debts_total)}",
    ]
    if has_expenses:
        lines.append(f"Траты: {format_amount(expenses_total)}")
    lines.append("────────────────")
    card_line = f"Через {months} {word}: {_signed(card_end)}"
    if card_end < 0:
        card_line += " ⚠️"
    lines.append(card_line)

    lines += [
        "",
        "*Копилка:*",
        f"Сейчас: {format_amount(savings)}",
        f"Отложено: {format_amount(goals_total)}",
        "────────────────",
        f"Через {months} {word}: {format_amount(savings_end)}",
    ]

    if goal_lines:
        lines += ["", "*Цели:*", *goal_lines]

    if has_expenses:
        lines += ["", "*Средние траты в месяц:*"]
        for name, amount in top_categories:
            lines.append(
                f"{escape_markdown(name)}: {format_amount(amount // AVG_MONTHS)}"
            )
    else:
        lines += ["", "*Средние траты:* пока нет данных для расчёта."]

    if user.income_type == IncomeType.IRREGULAR.value and not user.income:
        lines += [
            "",
            "*Доход нерегулярный, среднее не указано. "
            "Прогноз без учёта дохода.*",
        ]

    if card_end < 0:
        lines += [
            "",
            f"⚠️ Если ничего не менять, через {months} {word} уйдёшь в минус.",
        ]
    else:
        lines += [
            "",
            f"🎉 Если ничего не менять, через {months} {word} всё под контролем.",
        ]

    return "\n".join(lines)


def _horizon_keyboard() -> InlineKeyboardMarkup:
    """Кнопки выбора горизонта прогноза."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label, callback_data=f"{CALLBACK_PREFIX}{months}"
                )
                for months, label in HORIZONS
            ]
        ]
    )


def _parse_horizon(data: str) -> int | None:
    """Разбирает callback ``forecast:<N>`` в число месяцев или None."""
    if not data.startswith(CALLBACK_PREFIX):
        return None
    raw = data[len(CALLBACK_PREFIX) :]
    if not raw.isdigit():
        return None
    months = int(raw)
    return months if months in HORIZON_MONTHS else None


async def cmd_forecast(message: Message, session: AsyncSession) -> None:
    """Показывает кнопки выбора горизонта прогноза."""
    if message.from_user is None:
        return
    user = await users_repo.get_by_telegram_id(session, message.from_user.id)
    if user is None or not user.onboarding_completed:
        await message.answer(NEED_ONBOARDING)
        return
    await message.answer(PROMPT, reply_markup=_horizon_keyboard())


async def on_horizon(callback: CallbackQuery, session: AsyncSession) -> None:
    """Кнопка горизонта: считает прогноз и перерисовывает сообщение."""
    await callback.answer()
    if callback.from_user is None or callback.data is None:
        return
    months = _parse_horizon(callback.data)
    if months is None:
        return
    user = await users_repo.get_by_telegram_id(session, callback.from_user.id)
    if user is None or not user.onboarding_completed:
        return
    if not isinstance(callback.message, Message):
        return

    text = await build_forecast_text(session, user, months)
    try:
        await callback.message.edit_text(
            text, parse_mode="Markdown", reply_markup=_horizon_keyboard()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            text, parse_mode="Markdown", reply_markup=_horizon_keyboard()
        )


def build_router() -> Router:
    """Создаёт роутер команды /forecast."""
    router = Router(name="forecast")
    router.message.register(cmd_forecast, Command("forecast"))
    router.callback_query.register(
        on_horizon, F.data.startswith(CALLBACK_PREFIX)
    )
    return router
