"""Категории операций (Фаза 6)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Category, Transaction
from models.base import CategoryType, TransactionType
from models.category import CATEGORY_NAME_MAX

# Базовые категории по типам. Создаются лениво при первом обращении.
DEFAULT_CATEGORIES: dict[str, tuple[str, ...]] = {
    CategoryType.EXPENSE.value: (
        "Продукты",
        "Транспорт",
        "Жильё",
        "Связь",
        "Здоровье",
        "Развлечения",
        "Одежда",
        "Прочее",
    ),
    CategoryType.INCOME.value: (
        "Зарплата",
        "Аванс",
        "Подарок",
        "Прочее",
    ),
}


def _now_iso() -> str:
    """Текущее время в ISO-формате (UTC)."""
    return datetime.now(UTC).isoformat()


def get_default_categories(category_type: str) -> list[str]:
    """Базовый список названий категорий для типа (expense/income)."""
    return list(DEFAULT_CATEGORIES.get(category_type, ()))


def normalize_name(raw: str | None) -> str:
    """Приводит название категории к безопасному виду (trim + лимит длины)."""
    return (raw or "").strip()[:CATEGORY_NAME_MAX]


async def _existing_names(
    session: AsyncSession, telegram_id: int, category_type: str
) -> set[str]:
    """Названия уже созданных категорий пользователя данного типа."""
    result = await session.execute(
        select(Category.name).where(
            Category.telegram_id == telegram_id,
            Category.type == category_type,
        )
    )
    return set(result.scalars().all())


async def seed_default_categories(
    session: AsyncSession, telegram_id: int, category_type: str
) -> None:
    """Создаёт базовые категории пользователя, если их ещё нет."""
    existing = await _existing_names(session, telegram_id, category_type)
    created = False
    for name in get_default_categories(category_type):
        if name in existing:
            continue
        session.add(
            Category(
                telegram_id=telegram_id,
                name=name,
                type=category_type,
                is_custom=False,
                created_at=_now_iso(),
            )
        )
        created = True
    if created:
        await session.commit()


async def get_categories(
    session: AsyncSession, telegram_id: int, category_type: str
) -> list[Category]:
    """Категории пользователя типа: сначала базовые, затем пользовательские.

    При первом обращении лениво создаёт базовые категории.
    """
    await seed_default_categories(session, telegram_id, category_type)
    result = await session.execute(
        select(Category)
        .where(
            Category.telegram_id == telegram_id,
            Category.type == category_type,
        )
        .order_by(Category.is_custom, Category.id)
    )
    return list(result.scalars().all())


async def add_category(
    session: AsyncSession,
    telegram_id: int,
    name: str,
    category_type: str,
    is_custom: bool = True,
) -> Category:
    """Создаёт категорию и возвращает её."""
    category = Category(
        telegram_id=telegram_id,
        name=normalize_name(name),
        type=category_type,
        is_custom=is_custom,
        created_at=_now_iso(),
    )
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return category


async def get_category(
    session: AsyncSession, telegram_id: int, category_id: int
) -> Category | None:
    """Категория пользователя по id или None."""
    result = await session.execute(
        select(Category).where(
            Category.telegram_id == telegram_id,
            Category.id == category_id,
        )
    )
    return result.scalar_one_or_none()


async def find_by_name(
    session: AsyncSession, telegram_id: int, name: str, category_type: str
) -> Category | None:
    """Категория пользователя по названию (регистр не важен) или None."""
    target = normalize_name(name).lower()
    if not target:
        return None
    for category in await get_categories(session, telegram_id, category_type):
        if category.name.lower() == target:
            return category
    return None


async def delete_category(
    session: AsyncSession, telegram_id: int, category_id: int
) -> bool:
    """Удаляет пользовательскую категорию. Базовые удалять нельзя.

    У связанных операций сбрасывает ``category_id``. Возвращает True, если
    категория была удалена.
    """
    category = await get_category(session, telegram_id, category_id)
    if category is None or not category.is_custom:
        return False
    await session.execute(
        update(Transaction)
        .where(Transaction.category_id == category_id)
        .values(category_id=None)
    )
    await session.delete(category)
    await session.commit()
    return True


async def get_top_expense_categories(
    session: AsyncSession,
    telegram_id: int,
    since_iso: str,
    limit: int = 3,
) -> list[tuple[str, int]]:
    """Топ категорий трат за период: [(название, сумма), ...] по убыванию."""
    total = func.coalesce(func.sum(Transaction.amount), 0)
    result = await session.execute(
        select(Category.name, total)
        .join(Category, Category.id == Transaction.category_id)
        .where(
            Transaction.telegram_id == telegram_id,
            Transaction.type == TransactionType.EXPENSE.value,
            Transaction.created_at >= since_iso,
        )
        .group_by(Category.id)
        .order_by(total.desc(), Category.id)
        .limit(limit)
    )
    return [(name, int(amount)) for name, amount in result.all()]
