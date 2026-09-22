"""Операции со счетами пользователей (Фаза 5)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Account, FamilyMember
from models.account import CARD, SAVINGS

DEFAULT_CARD_NAME = "Карта"
DEFAULT_SAVINGS_NAME = "Копилка"
# Длина поля accounts.name (String(64)).
CARD_NAME_MAX = 64


def _now_iso() -> str:
    """Текущее время в ISO-формате (UTC)."""
    return datetime.now(UTC).isoformat()


def normalize_card_name(raw: str | None) -> str:
    """Приводит имя карты к безопасному виду.

    Обрезает пробелы и длину до ``CARD_NAME_MAX``. Пустой ввод заменяется
    на «Карта».
    """
    name = (raw or "").strip()
    return name[:CARD_NAME_MAX] if name else DEFAULT_CARD_NAME


async def create_accounts(
    session: AsyncSession,
    telegram_id: int,
    family_id: int | None = None,
    card_balance: int = 0,
    card_name: str = DEFAULT_CARD_NAME,
) -> list[Account]:
    """Создаёт карту и копилку пользователя. Повторный вызов дополняет пару."""
    existing = {
        account.type: account
        for account in await get_accounts(session, telegram_id)
    }
    created: list[Account] = []
    setup = (
        (CARD, card_balance, card_name),
        (SAVINGS, 0, DEFAULT_SAVINGS_NAME),
    )
    for account_type, balance, name in setup:
        account = existing.get(account_type)
        if account is None:
            account = Account(
                telegram_id=telegram_id,
                family_id=family_id,
                type=account_type,
                name=name,
                balance=balance,
                created_at=_now_iso(),
            )
            session.add(account)
        created.append(account)
    await session.commit()
    for account in created:
        await session.refresh(account)
    return created


async def get_account(
    session: AsyncSession, telegram_id: int, account_type: str
) -> Account | None:
    """Возвращает счёт пользователя по типу или None."""
    result = await session.execute(
        select(Account).where(
            Account.telegram_id == telegram_id, Account.type == account_type
        )
    )
    return result.scalar_one_or_none()


async def get_accounts(session: AsyncSession, telegram_id: int) -> list[Account]:
    """Все счета пользователя: сначала карта, затем копилка."""
    result = await session.execute(
        select(Account)
        .where(Account.telegram_id == telegram_id)
        .order_by(Account.id)
    )
    return list(result.scalars().all())


async def get_family_accounts(
    session: AsyncSession, family_id: int
) -> list[Account]:
    """Все счета участников семьи."""
    result = await session.execute(
        select(Account)
        .join(FamilyMember, FamilyMember.telegram_id == Account.telegram_id)
        .where(FamilyMember.family_id == family_id)
        .order_by(Account.telegram_id, Account.id)
    )
    return list(result.scalars().all())


async def get_balance(
    session: AsyncSession, telegram_id: int, account_type: str
) -> int:
    """Баланс счёта по типу (0, если счёт ещё не создан)."""
    account = await get_account(session, telegram_id, account_type)
    return account.balance if account is not None else 0


async def ensure_account(
    session: AsyncSession, telegram_id: int, account_type: str
) -> Account:
    """Возвращает счёт, создавая пару card+savings при её отсутствии."""
    account = await get_account(session, telegram_id, account_type)
    if account is None:
        await create_accounts(session, telegram_id)
        account = await get_account(session, telegram_id, account_type)
    assert account is not None
    return account


async def update_balance(
    session: AsyncSession, account_id: int, amount: int
) -> int:
    """Меняет баланс счёта на ``amount`` и возвращает новый баланс.

    Бросает ValueError, если счёт не найден или карта уходит в минус.
    """
    account = await session.get(Account, account_id)
    if account is None:
        raise ValueError("Счёт не найден.")
    new_balance = (account.balance or 0) + amount
    if account.type == CARD and new_balance < 0:
        raise ValueError("Недостаточно свободных денег.")
    account.balance = new_balance
    await session.commit()
    await session.refresh(account)
    return account.balance


async def correct_balance(
    session: AsyncSession, account_id: int, new_balance: int
) -> int:
    """Выравнивает баланс счёта под ``new_balance`` и возвращает его."""
    account = await session.get(Account, account_id)
    if account is None:
        raise ValueError("Счёт не найден.")
    account.balance = new_balance
    await session.commit()
    await session.refresh(account)
    return account.balance


async def rename_account(
    session: AsyncSession,
    telegram_id: int,
    account_type: str,
    new_name: str,
) -> Account | None:
    """Переименовывает счёт пользователя. None, если счёта нет."""
    account = await get_account(session, telegram_id, account_type)
    if account is None:
        return None
    account.name = new_name
    await session.commit()
    await session.refresh(account)
    return account


async def set_family_id(
    session: AsyncSession, telegram_id: int, family_id: int | None
) -> None:
    """Проставляет family_id на всех счетах пользователя."""
    await session.execute(
        update(Account)
        .where(Account.telegram_id == telegram_id)
        .values(family_id=family_id)
    )
    await session.commit()


async def transfer_card_to_savings(
    session: AsyncSession, telegram_id: int, amount: int
) -> tuple[int, int]:
    """Переводит сумму с карты на копилку. Возвращает (карта, копилка)."""
    if amount <= 0:
        raise ValueError("Сумма должна быть больше нуля.")
    card = await get_account(session, telegram_id, CARD)
    savings = await get_account(session, telegram_id, SAVINGS)
    if card is None or savings is None:
        await create_accounts(session, telegram_id)
        card = await get_account(session, telegram_id, CARD)
        savings = await get_account(session, telegram_id, SAVINGS)
    assert card is not None and savings is not None
    if (card.balance or 0) < amount:
        raise ValueError("Недостаточно свободных денег.")
    card.balance = (card.balance or 0) - amount
    savings.balance = (savings.balance or 0) + amount
    await session.commit()
    await session.refresh(card)
    await session.refresh(savings)
    return card.balance, savings.balance
