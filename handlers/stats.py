"""Команда /stats — сводка Фаз 2–4."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from models import Transaction, User
from models.base import IncomeType, TransactionType
from services import (
    accounts_repo,
    debts_repo,
    family_repo,
    goals_repo,
    transactions_repo,
    users_repo,
)
from services.calculations import (
    end_of_month,
    goal_emoji,
    goal_progress_percent,
    parse_income_dates,
)
from utils.money import format_amount, format_rubles

router = Router(name="stats")

LAST_LIMIT = 5
UPCOMING_DAYS = 30

_MD_SPECIAL = str.maketrans({char: f"\\{char}" for char in "_*`["})


def escape_markdown(text: str) -> str:
    """Экранирует спецсимволы legacy-Markdown в имени пользователя."""
    return text.translate(_MD_SPECIAL)


def format_income_lines(user: User) -> list[str]:
    """Строки блока «Доход». Пустой список — блок скрывается.

    Без скобок и запятых, чтобы Telegram не принимал текст за ссылку.
    """
    if user.income_type == IncomeType.IRREGULAR.value:
        if user.income:
            return [
                "*Доход:* нерегулярный",
                f"Среднее в месяц: {format_amount(user.income)}",
            ]
        return []
    entries = parse_income_dates(user.income_dates)
    if not entries:
        return []
    lines = ["*Доход:*"]
    for day, amount in sorted(entries, key=lambda item: item[0]):
        lines.append(f"{day} числа — {format_amount(amount)}")
    return lines


def format_date_label(created_at_iso: str, today: date) -> str:
    """Метка даты: «сегодня», «вчера» или «дд.мм»."""
    try:
        moment = datetime.fromisoformat(created_at_iso)
    except ValueError:
        return created_at_iso
    day = moment.date()
    if day == today:
        return "сегодня"
    if day == today - timedelta(days=1):
        return "вчера"
    return day.strftime("%d.%m")


def format_transaction_line(transaction: Transaction, today: date) -> str:
    """Строка последней операции со знаком и меткой даты."""
    if transaction.type == TransactionType.EXPENSE.value:
        signed = f"−{format_amount(transaction.amount)}"
    elif transaction.type == TransactionType.INCOME.value:
        signed = f"+{format_amount(transaction.amount)}"
    elif transaction.type == TransactionType.SAVINGS_ADD.value:
        signed = f"→ Копилка: {format_amount(transaction.amount)}"
    else:
        sign = "+" if transaction.amount >= 0 else "−"
        signed = f"{sign}{format_amount(abs(transaction.amount))}"
    return f"{signed} ({format_date_label(transaction.created_at, today)})"


def _period_line(title: str, amount: int) -> str:
    """Строка «За период» со знаком сальдо: «*За сегодня:* +25 800 ₽»."""
    if amount > 0:
        return f"*{title}:* +{format_amount(amount)}"
    if amount < 0:
        return f"*{title}:* −{format_amount(abs(amount))}"
    return f"*{title}:* {format_amount(0)}"


def format_payment_line(payment_date: date, debt: object) -> str:
    """Строка ближайшего платежа: «25.09 — Кредит: 46 000 ₽»."""
    return (
        f"{payment_date.strftime('%d.%m')} — "
        f"{escape_markdown(debt.name)}: "  # type: ignore[attr-defined]
        f"{format_amount(debt.amount)}"  # type: ignore[attr-defined]
    )


def next_salary_date(user: User, today: date) -> date | None:
    """Дата следующей зарплаты (для фиксированного дохода) или None."""
    if user.income_type != IncomeType.FIXED.value:
        return None
    entries = parse_income_dates(user.income_dates)
    if not entries:
        return None
    salary_day = min(day for day, _ in entries)
    return debts_repo.next_payment_date(salary_day, today)


async def build_stats_text(
    session: AsyncSession, user: User, today: date | None = None
) -> str:
    """Собирает текст сводки /stats (семейный или одиночный)."""
    today = today or datetime.now(UTC).date()
    family = await family_repo.get_family(session, user.telegram_id)
    if family is not None:
        return await build_family_stats_text(session, user, family, today)
    return await build_solo_stats_text(session, user, today)


async def build_solo_stats_text(
    session: AsyncSession, user: User, today: date | None = None
) -> str:
    """Собирает текст сводки для пользователя без семьи."""
    today = today or datetime.now(UTC).date()
    free_money = await accounts_repo.get_balance(session, user.telegram_id, "card")
    lines = [f"*Свободно:* {format_amount(free_money)}"]

    income_lines = format_income_lines(user)
    if income_lines:
        lines.append("")
        lines.extend(income_lines)

    upcoming = await debts_repo.get_upcoming_payments(
        session, user.telegram_id, UPCOMING_DAYS, today
    )
    if upcoming:
        lines.append("")
        lines.append("*Ближайшие платежи:*")
        lines.extend(
            format_payment_line(payment_date, debt)
            for payment_date, debt in upcoming
        )

    debts = await debts_repo.get_debts(session, user.telegram_id)
    if debts:
        salary_date = next_salary_date(user, today)
        month_end = end_of_month(today)
        until_salary = 0
        until_month_end = 0
        for debt in debts:
            dates = debts_repo.payments_within(
                debt.payment_day, today, UPCOMING_DAYS
            )
            if salary_date is not None:
                until_salary += sum(
                    debt.amount
                    for payment_date in dates
                    if payment_date <= salary_date
                )
            until_month_end += sum(
                debt.amount for payment_date in dates if payment_date <= month_end
            )

        lines.append("")
        if salary_date is not None:
            lines.append(
                f"*Свободно до ЗП:* "
                f"{format_amount(free_money - until_salary)}"
            )
        lines.append(
            f"*Свободно до конца месяца:* "
            f"{format_amount(free_money - until_month_end)}"
        )

    savings_balance = await accounts_repo.get_balance(
        session, user.telegram_id, "savings"
    )
    goals = await goals_repo.get_goals(session, user.telegram_id)
    progress = await goals_repo.get_progress_by_goals(
        session, [goal.id for goal in goals]
    )

    if savings_balance > 0:
        lines.append("")
        lines.append(f"*Копилка:* {format_amount(savings_balance)}")
    if goals:
        lines.append("")
        lines.append("*Цели:*")
        for goal in goals:
            percent = goal_progress_percent(progress.get(goal.id, 0), goal.target)
            lines.append(
                f"{goal_emoji(goal.name)} {escape_markdown(goal.name)}: "
                f"{format_rubles(progress.get(goal.id, 0))} / "
                f"{format_rubles(goal.target)} ₽ "
                f"({percent}%)"
            )

    last = await transactions_repo.get_last_transactions(
        session, user.telegram_id, LAST_LIMIT
    )
    if last:
        lines.append("")
        lines.append("*Последние операции:*")
        lines.extend(format_transaction_line(item, today) for item in last)

        lines.append("")
        lines.append(
            _period_line(
                "За сегодня",
                await transactions_repo.get_balance_by_period(
                    session, user.telegram_id, "today"
                ),
            )
        )
        lines.append(
            _period_line(
                "За неделю",
                await transactions_repo.get_balance_by_period(
                    session, user.telegram_id, "week"
                ),
            )
        )
        lines.append(
            _period_line(
                "За месяц",
                await transactions_repo.get_balance_by_period(
                    session, user.telegram_id, "month"
                ),
            )
        )

    return "\n".join(lines)


def member_label(member_id: int | None, own_id: int, name: str | None) -> str:
    """Подпись участника: «я» для себя, имя партнёра иначе (нижний регистр)."""
    if member_id == own_id:
        return "я"
    return name.lower() if name else "участник"


def account_owner_label(
    member_id: int | None, own_id: int, name: str | None
) -> str:
    """Подпись владельца счёта: «моя»/«жена»."""
    if member_id == own_id:
        return "моя"
    return name.lower() if name else "участника"


async def build_family_stats_text(
    session: AsyncSession,
    user: User,
    family: object,
    today: date | None = None,
) -> str:
    """Собирает семейную сводку: счета обоих, общие цели, операции."""
    today = today or datetime.now(UTC).date()
    family_id = family.id  # type: ignore[attr-defined]
    members = await family_repo.get_family_members(session, family_id)
    own_id = user.telegram_id
    names = {member.telegram_id: member.first_name for member in members}
    others = [member for member in members if member.telegram_id != own_id]
    partner_id = others[0].telegram_id if others else None
    partner_name = names.get(partner_id) if partner_id is not None else None

    lines = [f"*Семья:* {escape_markdown(family.name)}"]  # type: ignore[attr-defined]

    own_card = await accounts_repo.get_balance(session, own_id, "card")
    own_savings = await accounts_repo.get_balance(session, own_id, "savings")
    partner_card = (
        await accounts_repo.get_balance(session, partner_id, "card")
        if partner_id is not None
        else 0
    )
    partner_savings = (
        await accounts_repo.get_balance(session, partner_id, "savings")
        if partner_id is not None
        else 0
    )

    lines.append("")
    lines.append("*Счета:*")
    lines.append("")
    lines.append(f"Моя карта: {format_amount(own_card)}")
    if partner_id is not None:
        owner_label = escape_markdown(
            account_owner_label(partner_id, own_id, partner_name)
        )
        lines.append(
            f"Карта {owner_label}: {format_amount(partner_card)}"
        )
    lines.append("")
    lines.append(f"Моя копилка: {format_amount(own_savings)}")
    if partner_id is not None:
        lines.append(
            f"Копилка {owner_label}: {format_amount(partner_savings)}"
        )
    lines.append("")
    lines.append(f"Свободно (карты): {format_amount(own_card + partner_card)}")
    lines.append(f"В копилках: {format_amount(own_savings + partner_savings)}")

    goals = await goals_repo.get_goals(session, own_id)
    progress = await goals_repo.get_progress_by_goals(
        session, [goal.id for goal in goals]
    )
    if goals:
        lines.append("")
        lines.append("*Цели:*")
        for goal in goals:
            percent = goal_progress_percent(progress.get(goal.id, 0), goal.target)
            lines.append(
                f"{goal_emoji(goal.name)} {escape_markdown(goal.name)}: "
                f"{format_rubles(progress.get(goal.id, 0))} / "
                f"{format_rubles(goal.target)} ₽ ({percent}%)"
            )

    payments: list[tuple[date, object]] = []
    for member in members:
        payments.extend(
            await debts_repo.get_upcoming_payments(
                session, member.telegram_id, UPCOMING_DAYS, today
            )
        )
    if payments:
        payments.sort(key=lambda item: item[0])
        lines.append("")
        lines.append("*Ближайшие платежи:*")
        lines.extend(
            format_payment_line(payment_date, debt)
            for payment_date, debt in payments
        )

    last = await transactions_repo.get_last_family_transactions(
        session, [member.telegram_id for member in members], LAST_LIMIT
    )
    if last:
        lines.append("")
        lines.append("*Последние операции:*")
        lines.extend(
            format_family_transaction_line(
                item, today, own_id, names.get(item.telegram_id)
            )
            for item in last
        )

        ids = [member.telegram_id for member in members]
        lines.append("")
        lines.append(
            _period_line(
                "За сегодня",
                await transactions_repo.get_family_balance_by_period(
                    session, ids, "today"
                ),
            )
        )
        lines.append(
            _period_line(
                "За неделю",
                await transactions_repo.get_family_balance_by_period(
                    session, ids, "week"
                ),
            )
        )
        lines.append(
            _period_line(
                "За месяц",
                await transactions_repo.get_family_balance_by_period(
                    session, ids, "month"
                ),
            )
        )

    return "\n".join(lines)


def format_family_transaction_line(
    transaction: Transaction,
    today: date,
    own_id: int,
    name: str | None,
) -> str:
    """Строка операции семьи с автором: «−3 000 ₽ (жена, сегодня)»."""
    if transaction.type == TransactionType.EXPENSE.value:
        signed = f"−{format_amount(transaction.amount)}"
    elif transaction.type == TransactionType.INCOME.value:
        signed = f"+{format_amount(transaction.amount)}"
    elif transaction.type == TransactionType.SAVINGS_ADD.value:
        signed = f"→ Копилка: {format_amount(transaction.amount)}"
    else:
        sign = "+" if transaction.amount >= 0 else "−"
        signed = f"{sign}{format_amount(abs(transaction.amount))}"
    author = escape_markdown(member_label(transaction.telegram_id, own_id, name))
    return (
        f"{signed} ({author}, {format_date_label(transaction.created_at, today)})"
    )


async def cmd_stats(message: Message, session: AsyncSession) -> None:
    """Показывает сводку: баланс, доход, операции и суммы за период."""
    if message.from_user is None:
        return

    user = await users_repo.get_by_telegram_id(session, message.from_user.id)
    if user is None or not user.onboarding_completed:
        await message.answer("Сначала пройди онбординг: /start")
        return

    await message.answer(
        await build_stats_text(session, user), parse_mode="Markdown"
    )


def build_router() -> Router:
    """Создаёт роутер сводки."""
    router = Router(name="stats")
    router.message.register(cmd_stats, Command("stats"))
    return router
