"""Команда /stats — сводка Фаз 2–5."""

from __future__ import annotations

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

from models import Family, FamilyMember, Transaction, User
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
DEFAULT_MEMBER_NAME = "Участник"

OVERALL_BUTTON = "📊 Общая"
CALLBACK_FAMILY = "stats_family"
CALLBACK_USER_PREFIX = "stats_user_"

_MD_SPECIAL = str.maketrans({char: f"\\{char}" for char in "_*`["})


def escape_markdown(text: str) -> str:
    """Экранирует спецсимволы legacy-Markdown в имени пользователя."""
    return text.translate(_MD_SPECIAL)


def member_name(member: FamilyMember) -> str:
    """Имя участника из Telegram-аккаунта (``first_name``)."""
    return member.first_name or DEFAULT_MEMBER_NAME


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


def _signed_amount(transaction: Transaction) -> str:
    """Сумма операции со знаком и типом (трата/доход/копилка/коррекция)."""
    if transaction.type == TransactionType.EXPENSE.value:
        return f"−{format_amount(transaction.amount)}"
    if transaction.type == TransactionType.INCOME.value:
        return f"+{format_amount(transaction.amount)}"
    if transaction.type == TransactionType.SAVINGS_ADD.value:
        return f"→ Копилка: {format_amount(transaction.amount)}"
    sign = "+" if transaction.amount >= 0 else "−"
    return f"{sign}{format_amount(abs(transaction.amount))}"


def format_transaction_line(transaction: Transaction, today: date) -> str:
    """Строка последней операции со знаком и меткой даты."""
    return (
        f"{_signed_amount(transaction)} "
        f"({format_date_label(transaction.created_at, today)})"
    )


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


def format_family_transaction_line(
    transaction: Transaction, today: date, name: str | None
) -> str:
    """Строка операции семьи с автором: «−3 000 ₽ (Жена, сегодня)»."""
    author = escape_markdown(name or DEFAULT_MEMBER_NAME)
    return (
        f"{_signed_amount(transaction)} "
        f"({author}, {format_date_label(transaction.created_at, today)})"
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


def member_label(member_id: int | None, own_id: int, name: str | None) -> str:
    """Подпись участника: «я» для себя, имя партнёра иначе (нижний регистр)."""
    if member_id == own_id:
        return "я"
    return name.lower() if name else "участник"


# --- одиночная сводка ---------------------------------------------------------


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


# --- семейные сводки (Фаза 5.1) ----------------------------------------------


async def build_family_stats_text(
    session: AsyncSession,
    user: User,
    family: Family,
    today: date | None = None,
    members: list[FamilyMember] | None = None,
) -> str:
    """Собирает «Общую» семейную сводку: счета обоих, свободно, цели, операции."""
    today = today or datetime.now(UTC).date()
    if members is None:
        members = await family_repo.get_family_members(session, family.id)
    member_ids = [member.telegram_id for member in members]
    names = {member.telegram_id: member_name(member) for member in members}

    lines = [f"*Семья: {escape_markdown(family.name)}*"]

    lines.append("")
    lines.append("*Счета:*")
    for member in members:
        owner = escape_markdown(names[member.telegram_id])
        accounts = await accounts_repo.get_accounts(session, member.telegram_id)
        for account in accounts:
            lines.append(
                f"{escape_markdown(account.name)} ({owner}): "
                f"{format_amount(account.balance or 0)}"
            )

    lines.append("")
    lines.append("*Свободно:*")
    total_free = 0
    for member in members:
        card = await accounts_repo.get_balance(
            session, member.telegram_id, "card"
        )
        total_free += card
        lines.append(
            f"{escape_markdown(names[member.telegram_id])}: "
            f"{format_amount(card)}"
        )
    lines.append(f"Итого: {format_amount(total_free)}")

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

    goals = await goals_repo.get_goals(session, user.telegram_id)
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

    last = await transactions_repo.get_last_family_transactions(
        session, member_ids, LAST_LIMIT
    )
    if last:
        lines.append("")
        lines.append("*Последние операции:*")
        lines.extend(
            format_family_transaction_line(
                item, today, names.get(item.telegram_id)
            )
            for item in last
        )

        lines.append("")
        lines.append(
            _period_line(
                "За месяц",
                await transactions_repo.get_family_balance_by_period(
                    session, member_ids, "month"
                ),
            )
        )

    return "\n".join(lines)


async def build_member_stats_text(
    session: AsyncSession,
    member_id: int,
    name: str,
    today: date | None = None,
) -> str:
    """Собирает «Мою» сводку участника: только его счета, платежи, операции."""
    today = today or datetime.now(UTC).date()
    card = await accounts_repo.get_balance(session, member_id, "card")
    savings = await accounts_repo.get_balance(session, member_id, "savings")

    lines = [
        f"*Статистика: {escape_markdown(name)}*",
        "",
        f"*Моя карта:* {format_amount(card)}",
        f"*Моя копилка:* {format_amount(savings)}",
        "",
        f"*Свободно:* {format_amount(card)}",
    ]

    payments = await debts_repo.get_upcoming_payments(
        session, member_id, UPCOMING_DAYS, today
    )
    if payments:
        lines.append("")
        lines.append("*Мои платежи:*")
        lines.extend(
            format_payment_line(payment_date, debt)
            for payment_date, debt in payments
        )

    goals = await goals_repo.get_goals(session, member_id)
    progress = await goals_repo.get_progress_by_goals(
        session, [goal.id for goal in goals]
    )
    if goals:
        lines.append("")
        lines.append("*Мои цели:*")
        for goal in goals:
            percent = goal_progress_percent(progress.get(goal.id, 0), goal.target)
            lines.append(
                f"{goal_emoji(goal.name)} {escape_markdown(goal.name)}: "
                f"{format_rubles(progress.get(goal.id, 0))} / "
                f"{format_rubles(goal.target)} ₽ ({percent}%)"
            )

    last = await transactions_repo.get_last_transactions(
        session, member_id, LAST_LIMIT
    )
    if last:
        lines.append("")
        lines.append("*Мои последние операции:*")
        lines.extend(format_transaction_line(item, today) for item in last)

    return "\n".join(lines)


def build_stats_keyboard(
    members: list[FamilyMember],
) -> InlineKeyboardMarkup | None:
    """Кнопки [📊 Общая] и [👤 Имя] для семьи. None, если участник один."""
    if len(members) < 2:
        return None
    buttons = [
        InlineKeyboardButton(text=OVERALL_BUTTON, callback_data=CALLBACK_FAMILY)
    ]
    buttons.extend(
        InlineKeyboardButton(
            text=f"👤 {member_name(member)}",
            callback_data=f"{CALLBACK_USER_PREFIX}{member.telegram_id}",
        )
        for member in members
    )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


async def build_stats_screen(
    session: AsyncSession, user: User, today: date | None = None
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Экран /stats по умолчанию: «Общая» с кнопками или соло без кнопок."""
    today = today or datetime.now(UTC).date()
    family = await family_repo.get_family(session, user.telegram_id)
    if family is None:
        return await build_solo_stats_text(session, user, today), None
    members = await family_repo.get_family_members(session, family.id)
    text = await build_family_stats_text(session, user, family, today, members)
    return text, build_stats_keyboard(members)


async def _safe_edit(
    message: Message,
    text: str,
    keyboard: InlineKeyboardMarkup | None,
) -> None:
    """Редактирует сообщение, игнорируя «не изменилось» и устаревшие сообщения."""
    try:
        await message.edit_text(
            text, parse_mode="Markdown", reply_markup=keyboard
        )
    except TelegramBadRequest:
        pass


async def _load_family(
    session: AsyncSession, telegram_id: int
) -> tuple[Family, list[FamilyMember]] | None:
    """Семья пользователя и её участники или None."""
    family = await family_repo.get_family(session, telegram_id)
    if family is None:
        return None
    members = await family_repo.get_family_members(session, family.id)
    return family, members


async def cmd_stats(message: Message, session: AsyncSession) -> None:
    """Показывает сводку: баланс, доход, операции и суммы за период."""
    if message.from_user is None:
        return

    user = await users_repo.get_by_telegram_id(session, message.from_user.id)
    if user is None or not user.onboarding_completed:
        await message.answer("Сначала пройди онбординг: /start")
        return

    text, keyboard = await build_stats_screen(session, user)
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)


async def on_stats_family(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[📊 Общая]: показывает общую семейную статистику."""
    await callback.answer()
    if callback.from_user is None or not isinstance(callback.message, Message):
        return

    user = await users_repo.get_by_telegram_id(session, callback.from_user.id)
    if user is None:
        return
    loaded = await _load_family(session, user.telegram_id)
    if loaded is None:
        return
    family, members = loaded
    text = await build_family_stats_text(session, user, family, members=members)
    await _safe_edit(callback.message, text, build_stats_keyboard(members))


async def on_stats_user(callback: CallbackQuery, session: AsyncSession) -> None:
    """[👤 Имя]: показывает статистику участника семьи."""
    await callback.answer()
    if (
        callback.from_user is None
        or callback.data is None
        or not isinstance(callback.message, Message)
    ):
        return

    target_raw = callback.data[len(CALLBACK_USER_PREFIX) :]
    if not target_raw.isdigit():
        return
    target_id = int(target_raw)

    user = await users_repo.get_by_telegram_id(session, callback.from_user.id)
    if user is None:
        return
    loaded = await _load_family(session, user.telegram_id)
    if loaded is None:
        return
    _, members = loaded
    target = next(
        (member for member in members if member.telegram_id == target_id), None
    )
    if target is None:
        return

    text = await build_member_stats_text(
        session, target_id, member_name(target)
    )
    await _safe_edit(callback.message, text, build_stats_keyboard(members))


def build_router() -> Router:
    """Создаёт роутер сводки."""
    router = Router(name="stats")
    router.message.register(cmd_stats, Command("stats"))
    router.callback_query.register(on_stats_family, F.data == CALLBACK_FAMILY)
    router.callback_query.register(
        on_stats_user, F.data.startswith(CALLBACK_USER_PREFIX)
    )
    return router
