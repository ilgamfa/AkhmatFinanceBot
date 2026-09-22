"""Тесты репозитория категорий (Фаза 6)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from models.base import CategoryType
from services import categories_repo


async def test_get_categories_returns_defaults(session: AsyncSession) -> None:
    categories = await categories_repo.get_categories(
        session, 1, CategoryType.EXPENSE.value
    )
    names = [category.name for category in categories]
    assert "Продукты" in names
    assert names == categories_repo.get_default_categories(
        CategoryType.EXPENSE.value
    )
    assert all(not category.is_custom for category in categories)


async def test_get_categories_includes_custom(
    session: AsyncSession,
) -> None:
    await categories_repo.get_categories(session, 1, CategoryType.EXPENSE.value)
    await categories_repo.add_category(
        session, 1, "Кофе", CategoryType.EXPENSE.value
    )

    categories = await categories_repo.get_categories(
        session, 1, CategoryType.EXPENSE.value
    )
    names = [category.name for category in categories]
    assert "Продукты" in names
    assert "Кофе" in names
    # Базовые категории идут раньше пользовательских.
    default_count = len(
        categories_repo.get_default_categories(CategoryType.EXPENSE.value)
    )
    assert names.index("Кофе") >= default_count


async def test_add_category_creates_custom(session: AsyncSession) -> None:
    category = await categories_repo.add_category(
        session, 7, "Спорт", CategoryType.EXPENSE.value
    )
    assert category.id is not None
    assert category.name == "Спорт"
    assert category.type == CategoryType.EXPENSE.value
    assert category.is_custom is True


async def test_get_categories_is_idempotent(session: AsyncSession) -> None:
    first = await categories_repo.get_categories(
        session, 1, CategoryType.EXPENSE.value
    )
    second = await categories_repo.get_categories(
        session, 1, CategoryType.EXPENSE.value
    )
    assert len(first) == len(second)


async def test_find_by_name_ignores_case(session: AsyncSession) -> None:
    found = await categories_repo.find_by_name(
        session, 1, "продукты", CategoryType.EXPENSE.value
    )
    assert found is not None
    assert found.name == "Продукты"


async def test_delete_category_only_custom(session: AsyncSession) -> None:
    base = (
        await categories_repo.get_categories(
            session, 1, CategoryType.EXPENSE.value
        )
    )[0]
    assert await categories_repo.delete_category(session, 1, base.id) is False

    custom = await categories_repo.add_category(
        session, 1, "Кофе", CategoryType.EXPENSE.value
    )
    assert await categories_repo.delete_category(session, 1, custom.id) is True
