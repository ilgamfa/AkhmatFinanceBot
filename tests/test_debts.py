"""Тесты долгов, платежей и /stats Фазы 7."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, timedelta

import pytest
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import DebtType, PaymentStatus
from services import accounts_repo, debts_repo, transactions_repo, users_repo
from services.calculations import dump_income_dates, moscow_today

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]

TODAY = moscow_today()
PAST_THIS_MONTH = TODAY - timedelta(days=1)
FUTURE = TODAY + timedelta(days=40)
PAST = TODAY - timedelta(days=40)
# День дохода, гарантированно не совпадающий с сегодняшним.
INCOME_DAY = (TODAY.day % 28) + 1
ADDED_TEXT = "Долг добавлен. Удалить можно в /debts."
NEEDS_PAST_IN_MONTH = pytest.mark.skipif(
    PAST_THIS_MONTH.month != TODAY.month,
    reason="1-е число месяца: прошлых дней в текущем месяце нет",
)


def _button_labels(bot: object) -> list[str]:
    """Тексты кнопок последней клавиатуры бота."""
    markup = bot.session.last_reply_markup  # type: ignore[attr-defined]
    if not isinstance(markup, InlineKeyboardMarkup):
        return []
    return [button.text for row in markup.inline_keyboard for button in row]


async def _onboard(send_message: Send, send_callback: Press) -> None:
    await send_message("/start")
    await send_callback("onboarding:start")
    await send_message("12000")
    await send_callback("onboarding:income_fixed")
    await send_callback("onboarding:times_1")
    await send_message(f"{INCOME_DAY}, 50000")


async def _add_debt(
    session: AsyncSession,
    telegram_id: int = 1,
    name: str = "Кредит",
    amount: int = 46000,
    due_date: date | None = None,
    debt_type: str = DebtType.REGULAR.value,
) -> tuple[int, int]:
    """Создаёт долг с одним платежом. Возвращает (debt_id, payment_id)."""
    debt = await debts_repo.create_debt(session, telegram_id, name, debt_type)
    payment = await debts_repo.add_payment(
        session, debt.id, amount, due_date or TODAY
    )
    return debt.id, payment.id


# --- 1. репозиторий ----------------------------------------------------------


async def test_create_debt_and_add_payment(session: AsyncSession) -> None:
    debt = await debts_repo.create_debt(session, 1, "Кредит")
    assert debt.id is not None
    assert debt.telegram_id == 1
    assert debt.name == "Кредит"
    assert debt.type == DebtType.REGULAR.value
    assert debt.created_at

    payment = await debts_repo.add_payment(session, debt.id, 46000, TODAY)
    assert payment.id is not None
    assert payment.debt_id == debt.id
    assert payment.amount == 46000
    assert payment.due_date == TODAY.isoformat()
    assert payment.status == PaymentStatus.PENDING.value
    assert payment.paid_at is None


async def test_get_debts_and_payments(session: AsyncSession) -> None:
    first = await debts_repo.create_debt(session, 1, "Кредит")
    await debts_repo.create_debt(session, 1, "Ипотека")
    await debts_repo.create_debt(session, 2, "Чужой")
    await debts_repo.add_payment(session, first.id, 1000, TODAY)
    await debts_repo.add_payment(session, first.id, 2000, TODAY + timedelta(days=30))

    debts = await debts_repo.get_debts(session, 1)
    assert [debt.name for debt in debts] == ["Кредит", "Ипотека"]
    payments = await debts_repo.get_payments(session, first.id)
    assert [payment.amount for payment in payments] == [1000, 2000]


@NEEDS_PAST_IN_MONTH
async def test_get_pending_and_paid_queries(session: AsyncSession) -> None:
    _, pending_id = await _add_debt(session, name="Кредит", due_date=TODAY)
    _, past_id = await _add_debt(session, name="Ипотека", due_date=PAST_THIS_MONTH)

    pending = await debts_repo.get_pending_payments(session, 1, TODAY, FUTURE)
    assert [payment.id for payment, _ in pending] == [pending_id]

    paid = await debts_repo.get_paid_payments(session, 1, TODAY, TODAY)
    assert past_id in [payment.id for payment, _ in paid]


async def test_update_debt_schedule_regenerates(session: AsyncSession) -> None:
    """Правка числа месяца и суммы пересобирает платежи регулярного долга."""
    debt = await debts_repo.create_debt(session, 1, "Кредит", DebtType.REGULAR.value)
    for due_date in debts_repo.monthly_dates(
        debts_repo.next_payment_date(5, TODAY), 3
    ):
        await debts_repo.add_payment(session, debt.id, 10000, due_date)

    await debts_repo.update_debt_schedule(session, debt.id, 50000, 20)

    payments = await debts_repo.get_payments(session, debt.id)
    assert all(payment.amount == 50000 for payment in payments)
    assert {date.fromisoformat(payment.due_date).day for payment in payments} == {20}


# --- 9. mark_paid ------------------------------------------------------------


async def test_mark_paid_changes_status(session: AsyncSession) -> None:
    _, payment_id = await _add_debt(session)
    payment = await debts_repo.mark_paid(session, payment_id)
    assert payment is not None
    assert payment.status == PaymentStatus.PAID.value
    assert payment.paid_at is not None


# --- 10. delete_debt ---------------------------------------------------------


async def test_delete_debt_removes_payments(session: AsyncSession) -> None:
    debt_id, _ = await _add_debt(session)
    assert await debts_repo.delete_debt(session, debt_id) is True
    assert await debts_repo.get_debts(session, 1) == []
    assert await debts_repo.get_payments(session, debt_id) == []
    assert await debts_repo.delete_debt(session, debt_id) is False


# --- 2–4. способы заполнения -------------------------------------------------


async def test_regular_flow_generates_payments(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/debts")
    descriptions = await send_callback("debts:add")
    assert "Какой тип долга?" in descriptions[0]
    assert "12" not in descriptions[0]
    replies = await send_callback("debt_method:regular")
    assert "Название" in replies[0]
    await send_message("Кредит")
    await send_message("46000")
    replies = await send_message("25")
    assert ADDED_TEXT in replies[0]

    debt = (await debts_repo.get_debts(session, 1))[0]
    assert debt.type == DebtType.REGULAR.value
    payments = await debts_repo.get_payments(session, debt.id)
    assert len(payments) == 12
    assert payments[0].due_date == debts_repo.next_payment_date(25, TODAY).isoformat()
    assert all(payment.amount == 46000 for payment in payments)
    # каждый месяц в один день
    assert {date.fromisoformat(payment.due_date).day for payment in payments} == {25}


async def test_short_flow_generates_n(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/debts")
    await send_callback("debts:add")
    await send_callback("debt_method:short")
    await send_message("Рассрочка")
    replies = await send_message("3")
    assert "Дата платежа 1 из 3" in replies[0]
    await send_message("25.10.2026")
    await send_message("10000")
    await send_message("25.11.2026")
    await send_message("20000")
    await send_message("25.12.2026")
    replies = await send_message("30000")
    assert ADDED_TEXT in replies[0]

    debt = (await debts_repo.get_debts(session, 1))[0]
    assert debt.type == DebtType.SHORT.value
    payments = await debts_repo.get_payments(session, debt.id)
    assert [payment.amount for payment in payments] == [10000, 20000, 30000]


async def test_short_flow_allows_single_payment(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    """Краткосрочный с одним платежом допустим (N >= 1)."""
    await _onboard(send_message, send_callback)
    await send_message("/debts")
    await send_callback("debts:add")
    await send_callback("debt_method:short")
    await send_message("Рассрочка")
    replies = await send_message("1")
    assert "Дата платежа 1 из 1" in replies[0]
    await send_message("25.10.2026")
    replies = await send_message("5000")
    assert ADDED_TEXT in replies[0]

    debt = (await debts_repo.get_debts(session, 1))[0]
    assert debt.type == DebtType.SHORT.value
    payments = await debts_repo.get_payments(session, debt.id)
    assert len(payments) == 1


async def test_one_flow_creates_single_payment(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await send_message("/debts")
    await send_callback("debts:add")
    await send_callback("debt_method:one")
    await send_message("Штраф")
    await send_message("5000")
    replies = await send_message("01.10.2026")
    assert ADDED_TEXT in replies[0]

    debt = (await debts_repo.get_debts(session, 1))[0]
    assert debt.type == DebtType.ONE.value
    payments = await debts_repo.get_payments(session, debt.id)
    assert len(payments) == 1
    assert payments[0].due_date == "2026-10-01"


# --- 5–8. /stats -------------------------------------------------------------


async def test_stats_shows_upcoming(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await _add_debt(session, amount=46000, due_date=TODAY)

    text = (await send_message("/stats"))[0]
    assert "*Предстоящие:*" in text
    assert "— Кредит: 46 000 ₽" in text
    assert "Свободно: 12 000 ₽ — не хватает ❌ (нужно ещё 34 000 ₽)" in text


@NEEDS_PAST_IN_MONTH
async def test_stats_shows_paid(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await _add_debt(session, amount=7000, due_date=PAST_THIS_MONTH)

    text = (await send_message("/stats"))[0]
    assert "*Выплачено:*" in text
    assert "— Кредит: 7 000 ₽ ✅" in text


async def test_stats_one_future_in_upcoming(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await _add_debt(
        session,
        name="Штраф",
        amount=5000,
        due_date=FUTURE,
        debt_type=DebtType.ONE.value,
    )

    text = (await send_message("/stats"))[0]
    assert "*Предстоящие:*" in text
    assert "— Штраф: 5 000 ₽" in text


async def test_stats_one_past_in_paid(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    await _add_debt(
        session,
        name="Штраф",
        amount=5000,
        due_date=PAST,
        debt_type=DebtType.ONE.value,
    )

    text = (await send_message("/stats"))[0]
    assert "*Выплачено:*" in text
    assert "— Штраф: 5 000 ₽ ✅" in text


async def test_stats_hides_blocks_when_empty(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback)
    text = (await send_message("/stats"))[0]
    assert "*Предстоящие:*" not in text
    assert "*Выплачено:*" not in text
    assert "*Просрочено:*" not in text
    assert "*Продлить долги:*" not in text


# --- UI: список, удаление, редактирование ------------------------------------


async def test_debts_list_format(
    send_message: Send, send_callback: Press, session: AsyncSession, bot: object
) -> None:
    await _onboard(send_message, send_callback)
    empty = await send_message("/debts")
    assert "нет долгов" in empty[0]
    labels = _button_labels(bot)
    assert "➕ Добавить" in labels
    assert "🗑 Удалить" not in labels

    # регулярный — «сумма/мес, N числа»
    regular = await debts_repo.create_debt(session, 1, "Кредит", DebtType.REGULAR.value)
    for due_date in debts_repo.monthly_dates(
        debts_repo.next_payment_date(25, TODAY), 12
    ):
        await debts_repo.add_payment(session, regular.id, 46000, due_date)
    # краткосрочный — «N платежа, следующий дата»
    short_first = TODAY + timedelta(days=5)
    short = await debts_repo.create_debt(session, 1, "Кредитка", DebtType.SHORT.value)
    for offset in (0, 30, 60):
        await debts_repo.add_payment(
            session, short.id, 10000, short_first + timedelta(days=offset)
        )
    # разовый — «сумма, дата»
    one_date = TODAY + timedelta(days=7)
    one = await debts_repo.create_debt(session, 1, "Друг", DebtType.ONE.value)
    await debts_repo.add_payment(session, one.id, 44000, one_date)

    text = (await send_message("/debts"))[0]
    assert "Твои долги:" in text
    assert "1. Кредит — 46 000 ₽/мес, 25 числа" in text
    assert (
        f"2. Кредитка — 3 платежа, следующий {short_first.strftime('%d.%m')}"
        in text
    )
    assert f"3. Друг — 44 000 ₽, {one_date.strftime('%d.%m')}" in text
    assert "Неоплаченных платежей" not in text
    labels = _button_labels(bot)
    assert "✏️ Редактировать" in labels
    assert "🗑 Удалить" in labels


async def test_debts_delete_by_button(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    debt_id, _ = await _add_debt(session)

    await send_message("/debts")
    replies = await send_callback("debts:del")
    assert "Выбери долг для удаления:" in replies[0]
    replies = await send_callback(f"debt_del:{debt_id}")
    assert "Долг удалён: Кредит" in replies[0]
    assert await debts_repo.get_debts(session, 1) == []
    assert await debts_repo.get_payments(session, debt_id) == []


async def test_debts_edit_name(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    debt_id, _ = await _add_debt(session, name="Кредит", due_date=TODAY)

    await send_message("/debts")
    await send_callback("debts:edit")
    replies = await send_callback(f"debt_edit:{debt_id}")
    assert "Кредит" in replies[0]
    replies = await send_callback(f"debt_ename:{debt_id}")
    assert "Новое название" in replies[0]
    replies = await send_message("Автокредит")
    assert "переименован: Автокредит" in replies[0]

    session.expire_all()
    stored = (await debts_repo.get_debts(session, 1))[0]
    assert stored.name == "Автокредит"


async def test_debts_edit_regular_schedule(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    """Правка регулярного долга: число месяца и сумма, платежи пересобираются."""
    await _onboard(send_message, send_callback)
    debt = await debts_repo.create_debt(session, 1, "Кредит", DebtType.REGULAR.value)
    debt_id = debt.id
    for due_date in debts_repo.monthly_dates(
        debts_repo.next_payment_date(5, TODAY), 12
    ):
        await debts_repo.add_payment(session, debt_id, 46000, due_date)

    await send_message("/debts")
    await send_callback("debts:edit")
    await send_callback(f"debt_edit:{debt_id}")
    replies = await send_callback(f"debt_eschedule:{debt_id}")
    assert "число месяца" in replies[0]
    await send_message("20")
    replies = await send_message("50000")
    assert "обновлён" in replies[0]

    session.expire_all()
    payments = await debts_repo.get_payments(session, debt_id)
    assert all(payment.amount == 50000 for payment in payments)
    assert {date.fromisoformat(payment.due_date).day for payment in payments} == {20}


async def test_debts_edit_payment_amount(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback)
    debt_id, payment_id = await _add_debt(
        session, amount=46000, due_date=TODAY, debt_type=DebtType.ONE.value
    )

    await send_message("/debts")
    await send_callback("debts:edit")
    await send_callback(f"debt_edit:{debt_id}")
    replies = await send_callback(f"debt_pedit:{payment_id}")
    assert "Что изменить?" in replies[0]
    replies = await send_callback("debt_pfield:amount")
    assert "Новая сумма" in replies[0]
    replies = await send_message("50000")
    assert "Платёж обновлён" in replies[0]

    session.expire_all()
    payment = await debts_repo.get_payment(session, payment_id)
    assert payment is not None
    assert payment.amount == 50000


async def test_debts_payment_menu_has_no_delete(
    send_message: Send, send_callback: Press, session: AsyncSession, bot: object
) -> None:
    """В меню платежа нет удаления — только сумма и дата."""
    await _onboard(send_message, send_callback)
    debt_id, payment_id = await _add_debt(
        session, debt_type=DebtType.ONE.value, due_date=TODAY
    )

    await send_message("/debts")
    await send_callback("debts:edit")
    await send_callback(f"debt_edit:{debt_id}")
    await send_callback(f"debt_pedit:{payment_id}")

    labels = _button_labels(bot)
    assert "Сумма" in labels
    assert "Дата" in labels
    assert "🗑 Удалить платёж" not in labels


# --- 11. авто-оплата и границы долгов ----------------------------------------


async def test_close_overdue_marks_paid(session: AsyncSession) -> None:
    """Прошедший по дате платёж помечается оплаченным, paid_at = дата платежа."""
    _, payment_id = await _add_debt(session, due_date=PAST_THIS_MONTH)

    assert await debts_repo.close_overdue_payments(session, 1, TODAY) == 1
    payment = await debts_repo.get_payment(session, payment_id)
    assert payment is not None
    assert payment.status == PaymentStatus.PAID.value
    assert payment.paid_at == PAST_THIS_MONTH.isoformat()
    # повторный вызов ничего не меняет
    assert await debts_repo.close_overdue_payments(session, 1, TODAY) == 0


async def test_close_overdue_keeps_today_pending(session: AsyncSession) -> None:
    """Платёж со сроком «сегодня» ещё не оплачен."""
    _, payment_id = await _add_debt(session, due_date=TODAY)

    assert await debts_repo.close_overdue_payments(session, 1, TODAY) == 0
    payment = await debts_repo.get_payment(session, payment_id)
    assert payment is not None
    assert payment.status == PaymentStatus.PENDING.value


async def test_extend_finished_regular_adds_next_year(session: AsyncSession) -> None:
    """Регулярный долг без pending-платежей продлевается на 12 вперёд."""
    debt = await debts_repo.create_debt(session, 1, "Кредит", DebtType.REGULAR.value)
    for offset in (90, 60, 30):
        await debts_repo.add_payment(
            session, debt.id, 10000, TODAY - timedelta(days=offset)
        )
    await debts_repo.close_overdue_payments(session, 1, TODAY)

    assert await debts_repo.extend_finished_regular(session, 1, TODAY) == 1

    payments = await debts_repo.get_payments(session, debt.id)
    pending = [
        payment
        for payment in payments
        if payment.status == PaymentStatus.PENDING.value
    ]
    assert len(pending) == 12
    assert all(payment.amount == 10000 for payment in pending)
    assert all(date.fromisoformat(payment.due_date) >= TODAY for payment in pending)


async def test_extend_skips_regular_with_pending(session: AsyncSession) -> None:
    """Активный регулярный долг не продлевается."""
    await _add_debt(session, due_date=FUTURE)

    assert await debts_repo.extend_finished_regular(session, 1, TODAY) == 0


async def test_debts_hides_finished_short(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    """Краткосрочный долг исчезает, когда все платежи прошли."""
    await _onboard(send_message, send_callback)
    debt = await debts_repo.create_debt(session, 1, "Рассрочка", DebtType.SHORT.value)
    await debts_repo.add_payment(session, debt.id, 5000, PAST)

    replies = await send_message("/debts")
    assert "нет долгов" in replies[0]
    # в БД долг остался
    assert len(await debts_repo.get_debts(session, 1)) == 1


async def test_debts_short_shows_next_future_date(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    """Прошедший платёж не показывается как «следующий»."""
    await _onboard(send_message, send_callback)
    debt = await debts_repo.create_debt(session, 1, "Кредитка", DebtType.SHORT.value)
    await debts_repo.add_payment(session, debt.id, 10000, PAST_THIS_MONTH)
    future = TODAY + timedelta(days=15)
    await debts_repo.add_payment(session, debt.id, 10000, future)

    text = (await send_message("/debts"))[0]
    assert f"следующий {future.strftime('%d.%m')}" in text
    assert PAST_THIS_MONTH.strftime("%d.%m") not in text


async def test_debts_keeps_regular_and_extends(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    """Регулярный долг остаётся в списке и получает новые платежи."""
    await _onboard(send_message, send_callback)
    debt = await debts_repo.create_debt(session, 1, "Кредит", DebtType.REGULAR.value)
    await debts_repo.add_payment(session, debt.id, 46000, PAST)

    replies = await send_message("/debts")
    assert "1. Кредит — 46 000 ₽/мес," in replies[0]

    payments = await debts_repo.get_payments(session, debt.id)
    assert any(
        payment.status == PaymentStatus.PENDING.value for payment in payments
    )


async def test_stats_income_covers_future_payment(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    """Зарплата до даты платежа делает вердикт «хватает» и показывается строкой."""
    await _onboard(send_message, send_callback)
    user = await users_repo.get_by_telegram_id(session, 1)
    assert user is not None
    await users_repo.save_onboarding_profile(
        session,
        user,
        income_type="fixed",
        income_dates=dump_income_dates([(TODAY.day, 50000)]),
    )
    await _add_debt(
        session,
        name="Штраф",
        amount=46000,
        due_date=TODAY + timedelta(days=3),
        debt_type=DebtType.ONE.value,
    )

    text = (await send_message("/stats"))[0]
    assert f"  + {TODAY.strftime('%d.%m')}: 50 000 ₽" in text
    assert "Свободно: 62 000 ₽ — хватает ✅" in text


async def test_stats_income_today_skipped_when_recorded(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    """Если доход за сегодня уже записан, прогноз не задваивает его."""
    await _onboard(send_message, send_callback)
    user = await users_repo.get_by_telegram_id(session, 1)
    assert user is not None
    await users_repo.save_onboarding_profile(
        session,
        user,
        income_type="fixed",
        income_dates=dump_income_dates([(TODAY.day, 50000)]),
    )
    # зарплата уже зачислена: баланс 12000 + операция дохода
    card = await accounts_repo.ensure_account(session, 1, "card")
    await accounts_repo.correct_balance(session, card.id, 62000)
    await transactions_repo.add_transaction(session, 1, "income", 50000, card.id)
    await _add_debt(
        session,
        name="Штраф",
        amount=46000,
        due_date=TODAY + timedelta(days=3),
        debt_type=DebtType.ONE.value,
    )

    text = (await send_message("/stats"))[0]
    assert "Свободно: 62 000 ₽ — хватает ✅" in text
    assert f"  + {TODAY.strftime('%d.%m')}: 50 000 ₽" not in text
