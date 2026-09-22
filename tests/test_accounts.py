"""Тесты счетов card/savings (Фаза 5, задача 5.2)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models import Account
from services import accounts_repo, family_repo


async def test_create_accounts_makes_card_and_savings(session: AsyncSession) -> None:
    accounts = await accounts_repo.create_accounts(session, 1, card_balance=50000)
    types = {account.type for account in accounts}
    assert types == {"card", "savings"}

    card = await accounts_repo.get_account(session, 1, "card")
    savings = await accounts_repo.get_account(session, 1, "savings")
    assert card is not None and card.balance == 50000
    assert savings is not None and savings.balance == 0


async def test_create_accounts_sets_default_names(session: AsyncSession) -> None:
    """У карты и копилки непустые имена, по умолчанию «Карта» и «Копилка»."""
    await accounts_repo.create_accounts(session, 1, card_balance=50000)

    card = await accounts_repo.get_account(session, 1, "card")
    savings = await accounts_repo.get_account(session, 1, "savings")
    assert card is not None and card.name == "Карта"
    assert savings is not None and savings.name == "Копилка"


async def test_create_accounts_uses_card_name(session: AsyncSession) -> None:
    """Название карты берётся из параметра, копилка остаётся «Копилка»."""
    accounts = await accounts_repo.create_accounts(
        session, 1, card_balance=50000, card_name="Т-Банк"
    )
    names = {account.type: account.name for account in accounts}
    assert names == {"card": "Т-Банк", "savings": "Копилка"}


async def test_duplicate_account_type_raises(session: AsyncSession) -> None:
    """UNIQUE(telegram_id, type) не даёт завести вторую карту."""
    await accounts_repo.create_accounts(session, 1, card_balance=1000)
    session.add(
        Account(
            telegram_id=1,
            type="card",
            name="Дубль",
            balance=0,
            created_at="2026-09-21T00:00:00+00:00",
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_create_accounts_is_idempotent(session: AsyncSession) -> None:
    await accounts_repo.create_accounts(session, 1, card_balance=1000)
    await accounts_repo.create_accounts(session, 1, card_balance=9999)

    accounts = await accounts_repo.get_accounts(session, 1)
    assert len(accounts) == 2
    card = await accounts_repo.get_account(session, 1, "card")
    assert card is not None and card.balance == 1000


async def test_get_account_by_type(session: AsyncSession) -> None:
    assert await accounts_repo.get_account(session, 1, "card") is None
    assert await accounts_repo.get_balance(session, 1, "card") == 0

    await accounts_repo.create_accounts(session, 1, card_balance=3000)
    card = await accounts_repo.get_account(session, 1, "card")
    assert card is not None
    assert card.telegram_id == 1
    assert card.type == "card"


async def test_update_balance(session: AsyncSession) -> None:
    accounts = await accounts_repo.create_accounts(session, 1, card_balance=5000)
    card = next(account for account in accounts if account.type == "card")

    assert await accounts_repo.update_balance(session, card.id, 1500) == 6500
    assert await accounts_repo.update_balance(session, card.id, -2000) == 4500


async def test_update_balance_denies_negative_card(session: AsyncSession) -> None:
    accounts = await accounts_repo.create_accounts(session, 1, card_balance=1000)
    card = next(account for account in accounts if account.type == "card")

    with pytest.raises(ValueError):
        await accounts_repo.update_balance(session, card.id, -1001)


async def test_update_balance_missing_account(session: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await accounts_repo.update_balance(session, 999, 100)


async def test_correct_balance(session: AsyncSession) -> None:
    accounts = await accounts_repo.create_accounts(session, 1, card_balance=5000)
    savings = next(account for account in accounts if account.type == "savings")

    assert await accounts_repo.correct_balance(session, savings.id, 550000) == 550000
    assert await accounts_repo.get_balance(session, 1, "savings") == 550000

    # корректировка не ограничена балансом карты
    assert await accounts_repo.correct_balance(session, savings.id, 0) == 0


async def test_transfer_card_to_savings(session: AsyncSession) -> None:
    await accounts_repo.create_accounts(session, 1, card_balance=50000)

    card_balance, savings_balance = await accounts_repo.transfer_card_to_savings(
        session, 1, 20000
    )
    assert card_balance == 30000
    assert savings_balance == 20000


async def test_transfer_denies_insufficient(session: AsyncSession) -> None:
    await accounts_repo.create_accounts(session, 1, card_balance=5000)
    with pytest.raises(ValueError):
        await accounts_repo.transfer_card_to_savings(session, 1, 10000)
    with pytest.raises(ValueError):
        await accounts_repo.transfer_card_to_savings(session, 1, 0)


async def test_get_family_accounts(session: AsyncSession) -> None:
    family = await family_repo.create_family(session, 1)
    await family_repo.join_family(session, 2, family.invite_code)
    await accounts_repo.create_accounts(session, 1, card_balance=10000)
    await accounts_repo.create_accounts(session, 2, card_balance=20000)

    accounts = await accounts_repo.get_family_accounts(session, family.id)
    assert len(accounts) == 4
    assert {account.telegram_id for account in accounts} == {1, 2}


async def test_family_id_set_on_own_accounts(session: AsyncSession) -> None:
    await accounts_repo.create_accounts(session, 1, card_balance=10000)
    family = await family_repo.create_family(session, 1)

    accounts = await accounts_repo.get_accounts(session, 1)
    assert all(account.family_id == family.id for account in accounts)


def test_normalize_card_name() -> None:
    """Пустое имя → «Карта», длинное — обрезается до 64 символов."""
    assert accounts_repo.normalize_card_name(None) == "Карта"
    assert accounts_repo.normalize_card_name("   ") == "Карта"
    assert accounts_repo.normalize_card_name("  Т-Банк ") == "Т-Банк"
    assert len(accounts_repo.normalize_card_name("x" * 100)) == 64


async def test_rename_account(session: AsyncSession) -> None:
    await accounts_repo.create_accounts(session, 1, card_balance=5000)
    renamed = await accounts_repo.rename_account(session, 1, "card", "Т-Банк")
    assert renamed is not None and renamed.name == "Т-Банк"

    card = await accounts_repo.get_account(session, 1, "card")
    assert card is not None and card.name == "Т-Банк"


async def test_rename_account_missing(session: AsyncSession) -> None:
    assert await accounts_repo.rename_account(session, 1, "card", "Сбер") is None

