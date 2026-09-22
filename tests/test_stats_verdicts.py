"""Тесты вердиктов «хватает / не хватает» в /stats (Фаза 5.1)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from handlers.stats import genitive_name
from services import accounts_repo, debts_repo, family_repo

Send = Callable[..., Awaitable[list[str]]]
Press = Callable[..., Awaitable[list[str]]]

TODAY = datetime.now(UTC).date()
TODAY_DAY = TODAY.day


async def _onboard(
    send_message: Send, send_callback: Press, *, user_id: int, first_name: str
) -> None:
    await send_message("/start", user_id=user_id, first_name=first_name)
    await send_callback("onboarding:start", user_id=user_id, first_name=first_name)
    await send_message("12000", user_id=user_id, first_name=first_name)
    await send_callback(
        "onboarding:income_fixed", user_id=user_id, first_name=first_name
    )
    await send_callback(
        "onboarding:times_1", user_id=user_id, first_name=first_name
    )
    await send_message("10, 50000", user_id=user_id, first_name=first_name)


async def _set_card(
    session: AsyncSession, telegram_id: int, amount: int
) -> None:
    card = await accounts_repo.ensure_account(session, telegram_id, "card")
    await accounts_repo.correct_balance(session, card.id, amount)


async def _family(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback, user_id=1, first_name="Илья")
    await _onboard(send_message, send_callback, user_id=2, first_name="Жена")
    family = await family_repo.create_family(session, 1, "Наша семья", "Илья")
    await family_repo.join_family(session, 2, family.invite_code, "Жена")


async def test_family_overall_shows_verdicts(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _family(send_message, send_callback, session)
    await _set_card(session, 1, 50000)
    await _set_card(session, 2, 30000)
    await debts_repo.add_debt(session, 1, "Кредит", "loan", 46000, TODAY_DAY)
    await debts_repo.add_debt(session, 2, "Ипотека", "mortgage", 61000, TODAY_DAY)

    text = (await send_message("/stats", user_id=1, first_name="Илья"))[0]
    assert "*Платежи до конца месяца:*" in text
    assert "— Кредит (Илья): 46 000 ₽" in text
    assert "Свободно у Ильи: 50 000 ₽ — хватает ✅" in text
    assert "— Ипотека (Жена): 61 000 ₽" in text
    assert (
        "Свободно у Жены: 30 000 ₽ — не хватает ❌ (нужно ещё 31 000 ₽)"
        in text
    )


async def test_family_member_view_only_own_payments(
    send_message: Send, send_callback: Press, session: AsyncSession, bot: object
) -> None:
    await _family(send_message, send_callback, session)
    await _set_card(session, 1, 50000)
    await _set_card(session, 2, 30000)
    await debts_repo.add_debt(session, 1, "Кредит", "loan", 46000, TODAY_DAY)
    await debts_repo.add_debt(session, 2, "Ипотека", "mortgage", 61000, TODAY_DAY)

    await send_message("/stats", user_id=1, first_name="Илья")
    await send_callback("stats_user_2", user_id=1, first_name="Илья")

    edited = bot.session.edited[-1].text  # type: ignore[attr-defined]
    assert "*Мои платежи:*" in edited
    assert "— Ипотека: 61 000 ₽" in edited
    assert "Кредит" not in edited
    assert "Свободно: 30 000 ₽ — не хватает ❌ (нужно ещё 31 000 ₽)" in edited


async def test_no_payments_hides_block(
    send_message: Send, send_callback: Press
) -> None:
    await _onboard(send_message, send_callback, user_id=1, first_name="Илья")
    text = (await send_message("/stats", user_id=1, first_name="Илья"))[0]
    assert "*Платежи до конца месяца:*" not in text


async def test_solo_verdict_short(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback, user_id=1, first_name="Илья")
    await debts_repo.add_debt(session, 1, "Кредит", "loan", 46000, TODAY_DAY)

    text = (await send_message("/stats", user_id=1, first_name="Илья"))[0]
    assert "*Платежи до конца месяца:*" in text
    assert "— Кредит: 46 000 ₽" in text
    assert "Свободно: 12 000 ₽ — не хватает ❌ (нужно ещё 34 000 ₽)" in text


async def test_solo_verdict_enough(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback, user_id=1, first_name="Илья")
    await _set_card(session, 1, 50000)
    await debts_repo.add_debt(session, 1, "Кредит", "loan", 46000, TODAY_DAY)

    text = (await send_message("/stats", user_id=1, first_name="Илья"))[0]
    assert "Свободно: 50 000 ₽ — хватает ✅" in text


async def test_solo_verdict_negative_balance(
    send_message: Send, send_callback: Press, session: AsyncSession
) -> None:
    await _onboard(send_message, send_callback, user_id=1, first_name="Илья")
    await _set_card(session, 1, -5000)
    await debts_repo.add_debt(session, 1, "Кредит", "loan", 46000, TODAY_DAY)

    text = (await send_message("/stats", user_id=1, first_name="Илья"))[0]
    assert (
        "Свободно: −5 000 ₽ — не хватает ❌ (нужно ещё 51 000 ₽)" in text
    )


def test_genitive_name() -> None:
    """Имя владельца для «Свободно у …» ставится в родительный падеж."""
    assert genitive_name("Ильгам") == "Ильгама"
    assert genitive_name("Жена") == "Жены"
    assert genitive_name("Илья") == "Ильи"
    assert genitive_name("Андрей") == "Андрея"
    assert genitive_name("Игорь") == "Игоря"
    assert genitive_name("") == ""
