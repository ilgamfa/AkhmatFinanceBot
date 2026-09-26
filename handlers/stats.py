"""Команда /stats — сводка Фаз 2–5."""

from __future__ import annotations

from dataclasses import dataclass
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
from models.base import DebtType, IncomeType, TransactionType
from services import (
    accounts_repo,
    categories_repo,
    debts_repo,
    family_repo,
    goals_repo,
    stats_service,
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
DEFAULT_MEMBER_NAME = "Участник"

OVERALL_BUTTON = "📊 Общая"
CALLBACK_FAMILY = "stats_family"
CALLBACK_USER_PREFIX = "stats_user_"

PAID_SUFFIX = " ✅"
# Верхняя граница выборки будущих платежей (разовые долги показываются всегда).
FAR_FUTURE = date(9999, 12, 31)

_MD_SPECIAL = str.maketrans({char: f"\\{char}" for char in "_*`["})


@dataclass
class StatsScreen:
    """Текст сводки."""

    text: str


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


def format_balance(amount: int) -> str:
    """Баланс со знаком: отрицательный — «−5 000 ₽» (U+2212)."""
    if amount < 0:
        return f"−{format_amount(abs(amount))}"
    return format_amount(amount)


def month_start_iso(today: date) -> str:
    """Начало календарного месяца в ISO-формате (UTC)."""
    return datetime(today.year, today.month, 1, tzinfo=UTC).isoformat()


def format_top_categories_lines(top: list[tuple[str, int]]) -> list[str]:
    """Строки блока «Топ категорий за месяц». Пустой список — блок скрыт."""
    if not top:
        return []
    lines = ["", "*Топ категорий за месяц:*"]
    for index, (name, amount) in enumerate(top, start=1):
        lines.append(f"{index}. {escape_markdown(name)}: {format_amount(amount)}")
    return lines


_VOWELS = set("аеёиоуыэюя")


def genitive_name(name: str) -> str:
    """Имя в родительном падеже для «Свободно у …» (упрощённое правило)."""
    if not name:
        return name
    lower = name[-1].lower()
    if lower == "а":
        return name[:-1] + ("Ы" if name[-1].isupper() else "ы")
    if lower == "я":
        return name[:-1] + ("И" if name[-1].isupper() else "и")
    if lower in ("й", "ь"):
        return name[:-1] + ("Я" if name[-1].isupper() else "я")
    if lower in _VOWELS:
        return name
    return name + "а"


def format_month_payment_line(
    payment_date: date,
    debt_name: str,
    amount: int,
    owner_name: str | None = None,
) -> str:
    """Строка платежа: «25.09 — Кредит (Ильгам): 46 000 ₽»."""
    owner = f" ({escape_markdown(owner_name)})" if owner_name else ""
    return (
        f"{payment_date.strftime('%d.%m')} — "
        f"{escape_markdown(debt_name)}{owner}: {format_amount(amount)}"
    )


def format_payment_list_item(
    payment_date: date,
    debt_name: str,
    amount: int,
    owner_name: str | None = None,
    suffix: str = "",
) -> str:
    """Строка платежа с пометкой: оплачено ✅ или просрочено ⏳."""
    owner = f" ({escape_markdown(owner_name)})" if owner_name else ""
    return (
        f"{payment_date.strftime('%d.%m')} — "
        f"{escape_markdown(debt_name)}{owner}: {format_amount(amount)}{suffix}"
    )


def render_payment_list(
    header: str,
    rows: list[tuple[date, int, str, str | None]],
    suffix: str = "",
) -> list[str]:
    """Строки простого блока платежей: заголовок и по строке на платёж."""
    lines = ["", header]
    for payment_date, amount, debt_name, owner_name in rows:
        lines.append(
            format_payment_list_item(
                payment_date, debt_name, amount, owner_name, suffix
            )
        )
    return lines


def format_verdict_line(
    free: int, shortfall: int, owner_name: str | None = None
) -> str:
    """Строка вердикта: «Свободно у Ильгама: 50 000 ₽ — хватает ✅»."""
    who = f" у {escape_markdown(genitive_name(owner_name))}" if owner_name else ""
    if shortfall <= 0:
        return f"  Свободно{who}: {format_balance(free)} — хватает ✅"
    return (
        f"  Свободно{who}: {format_balance(free)} — "
        f"не хватает ❌ (нужно ещё {format_amount(shortfall)})"
    )


def render_month_payments(
    groups: list[list[stats_service.PaymentVerdict]],
    header: str,
    *,
    show_owner: bool,
) -> list[str]:
    """Строки блока платежей: заголовок и группы дней через пустую строку."""
    lines = [header]
    for group in groups:
        lines.append("")
        for verdict in group:
            owner = verdict.owner_name if show_owner else None
            lines.append(
                format_month_payment_line(
                    verdict.payment_date, verdict.debt_name, verdict.amount, owner
                )
            )
            lines.append(
                format_verdict_line(verdict.free, verdict.shortfall, owner)
            )
    return lines


async def _month_payment_groups(
    session: AsyncSession,
    owners: list[tuple[int, str]],
    today: date,
) -> list[list[stats_service.PaymentVerdict]]:
    """Вердикты по предстоящим платежам владельцев.

    Регулярные и краткосрочные — до конца месяца; разовые — на любую
    будущую дату.
    """
    month_end = end_of_month(today)
    balances: dict[int, int] = {}
    payments: list[tuple[date, int, str, int, str]] = []
    for owner_id, owner_name in owners:
        balances[owner_id] = await accounts_repo.get_balance(
            session, owner_id, "card"
        )
        pairs = await debts_repo.get_pending_payments(
            session, owner_id, today, FAR_FUTURE
        )
        for payment, debt in pairs:
            payment_date = date.fromisoformat(payment.due_date)
            if debt.type != DebtType.ONE.value and payment_date > month_end:
                continue
            payments.append(
                (
                    payment_date,
                    payment.amount,
                    debt.name,
                    owner_id,
                    owner_name,
                )
            )
    payments.sort(key=lambda item: item[0])
    return stats_service.build_payment_verdicts(payments, balances)


async def _paid_rows(
    session: AsyncSession,
    owners: list[tuple[int, str]],
    *,
    show_owner: bool,
    today: date,
) -> list[tuple[date, int, str, str | None]]:
    """Строки выплаченного: прошедшие платежи месяца + разовые в прошлом.

    Прошедший по дате платёж считается выплаченным независимо от статуса.
    """
    rows: list[tuple[date, int, str, str | None]] = []
    for owner_id, owner_name in owners:
        for payment, debt in await debts_repo.get_paid_payments(
            session, owner_id, today, today
        ):
            if debt.type == DebtType.ONE.value:
                continue
            rows.append(
                (
                    date.fromisoformat(payment.due_date),
                    payment.amount,
                    debt.name,
                    owner_name if show_owner else None,
                )
            )
        for debt in await debts_repo.get_debts(session, owner_id):
            if debt.type != DebtType.ONE.value:
                continue
            for payment in await debts_repo.get_payments(session, debt.id):
                payment_date = date.fromisoformat(payment.due_date)
                if payment_date < today:
                    rows.append(
                        (
                            payment_date,
                            payment.amount,
                            debt.name,
                            owner_name if show_owner else None,
                        )
                    )
    rows.sort(key=lambda item: item[0])
    return rows


async def _pending_until(
    session: AsyncSession, telegram_id: int, today: date, until_date: date
) -> int:
    """Сумма неоплаченных платежей от сегодня до ``until_date`` включительно."""
    pairs = await debts_repo.get_pending_payments(
        session, telegram_id, today, until_date
    )
    return sum(payment.amount for payment, _ in pairs)


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


async def _solo_screen(
    session: AsyncSession, user: User, today: date | None = None
) -> StatsScreen:
    """Собирает сводку для пользователя без семьи."""
    today = today or datetime.now(UTC).date()
    free_money = await accounts_repo.get_balance(session, user.telegram_id, "card")
    lines = [f"*Свободно:* {format_amount(free_money)}"]

    income_lines = format_income_lines(user)
    if income_lines:
        lines.append("")
        lines.extend(income_lines)

    owners = [(user.telegram_id, "")]
    groups = await _month_payment_groups(session, owners, today)
    if groups:
        lines.append("")
        lines.extend(
            render_month_payments(groups, "*Предстоящие:*", show_owner=False)
        )

    paid = await _paid_rows(session, owners, show_owner=False, today=today)
    if paid:
        lines.extend(render_payment_list("*Выплачено:*", paid, PAID_SUFFIX))

    debts = await debts_repo.get_debts(session, user.telegram_id)
    if debts:
        salary_date = next_salary_date(user, today)
        month_end = end_of_month(today)

        lines.append("")
        if salary_date is not None:
            until_salary = await _pending_until(
                session, user.telegram_id, today, salary_date
            )
            lines.append(
                f"*Свободно до ЗП:* "
                f"{format_amount(free_money - until_salary)}"
            )
        until_month_end = await _pending_until(
            session, user.telegram_id, today, month_end
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

    top = await categories_repo.get_top_expense_categories(
        session, user.telegram_id, month_start_iso(today)
    )
    lines.extend(format_top_categories_lines(top))

    return StatsScreen(text="\n".join(lines))


# --- семейные сводки (Фаза 5.1) ----------------------------------------------


async def _family_screen(
    session: AsyncSession,
    user: User,
    family: Family,
    today: date | None = None,
    members: list[FamilyMember] | None = None,
) -> StatsScreen:
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

    owners = [(member.telegram_id, member_name(member)) for member in members]
    groups = await _month_payment_groups(session, owners, today)
    if groups:
        lines.append("")
        lines.extend(
            render_month_payments(groups, "*Предстоящие:*", show_owner=True)
        )

    paid = await _paid_rows(session, owners, show_owner=True, today=today)
    if paid:
        lines.extend(render_payment_list("*Выплачено:*", paid, PAID_SUFFIX))

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

    top = await categories_repo.get_top_expense_categories(
        session, user.telegram_id, month_start_iso(today)
    )
    lines.extend(format_top_categories_lines(top))

    return StatsScreen(text="\n".join(lines))


async def _member_screen(
    session: AsyncSession,
    member_id: int,
    name: str,
    today: date | None = None,
) -> StatsScreen:
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

    owners = [(member_id, name)]
    groups = await _month_payment_groups(session, owners, today)
    if groups:
        lines.append("")
        lines.extend(
            render_month_payments(groups, "*Мои платежи:*", show_owner=False)
        )

    paid = await _paid_rows(session, owners, show_owner=False, today=today)
    if paid:
        lines.extend(render_payment_list("*Выплачено:*", paid, PAID_SUFFIX))

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

    top = await categories_repo.get_top_expense_categories(
        session, member_id, month_start_iso(today)
    )
    lines.extend(format_top_categories_lines(top))

    return StatsScreen(text="\n".join(lines))


def _compose_keyboard(
    screen: StatsScreen,
    view: str,
    actor_id: int,
    members: list[FamilyMember] | None = None,
) -> InlineKeyboardMarkup | None:
    """Собирает клавиатуру: только переключатель видов семьи (Фаза 5.1)."""
    rows: list[list[InlineKeyboardButton]] = []
    if members is not None and len(members) >= 2:
        member_row = [
            InlineKeyboardButton(
                text=OVERALL_BUTTON, callback_data=CALLBACK_FAMILY
            )
        ]
        member_row.extend(
            InlineKeyboardButton(
                text=f"👤 {member_name(member)}",
                callback_data=f"{CALLBACK_USER_PREFIX}{member.telegram_id}",
            )
            for member in members
        )
        rows.append(member_row)
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def build_view(
    session: AsyncSession,
    actor: User,
    view: str,
    today: date | None = None,
) -> tuple[str, InlineKeyboardMarkup | None] | None:
    """Пересобирает экран /stats в указанном виде (solo/fam/u<id>)."""
    today = today or datetime.now(UTC).date()
    if view == "solo":
        screen = await _solo_screen(session, actor, today)
        return screen.text, _compose_keyboard(screen, "solo", actor.telegram_id)

    loaded = await _load_family(session, actor.telegram_id)
    if loaded is None:
        return None
    family, members = loaded
    if view == "fam":
        screen = await _family_screen(session, actor, family, today, members)
        return screen.text, _compose_keyboard(
            screen, "fam", actor.telegram_id, members
        )

    if not view.startswith("u") or not view[1:].isdigit():
        return None
    target_id = int(view[1:])
    target = next(
        (member for member in members if member.telegram_id == target_id), None
    )
    if target is None:
        return None
    screen = await _member_screen(session, target_id, member_name(target), today)
    return screen.text, _compose_keyboard(
        screen, view, actor.telegram_id, members
    )


async def build_stats_screen(
    session: AsyncSession, user: User, today: date | None = None
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Экран /stats по умолчанию: «Общая» с кнопками или соло без кнопок."""
    today = today or datetime.now(UTC).date()
    family = await family_repo.get_family(session, user.telegram_id)
    view = "fam" if family is not None else "solo"
    rendered = await build_view(session, user, view, today)
    if rendered is None:
        return "", None
    return rendered


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


async def _rerender(
    callback: CallbackQuery, session: AsyncSession, view: str
) -> None:
    """Перерисовывает сообщение /stats в указанном виде."""
    if callback.from_user is None or not isinstance(callback.message, Message):
        return
    user = await users_repo.get_by_telegram_id(session, callback.from_user.id)
    if user is None:
        return
    rendered = await build_view(session, user, view)
    if rendered is None:
        return
    text, keyboard = rendered
    await _safe_edit(callback.message, text, keyboard)


async def on_stats_family(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[📊 Общая]: показывает общую семейную статистику."""
    await callback.answer()
    await _rerender(callback, session, "fam")


async def on_stats_user(callback: CallbackQuery, session: AsyncSession) -> None:
    """[👤 Имя]: показывает статистику участника семьи."""
    await callback.answer()
    if callback.data is None:
        return
    target_raw = callback.data[len(CALLBACK_USER_PREFIX) :]
    if not target_raw.isdigit():
        return
    await _rerender(callback, session, f"u{int(target_raw)}")


def build_router() -> Router:
    """Создаёт роутер сводки."""
    router = Router(name="stats")
    router.message.register(cmd_stats, Command("stats"))
    router.callback_query.register(on_stats_family, F.data == CALLBACK_FAMILY)
    router.callback_query.register(
        on_stats_user, F.data.startswith(CALLBACK_USER_PREFIX)
    )
    return router
