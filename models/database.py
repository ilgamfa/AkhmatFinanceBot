"""Подключение к базе данных и инициализация схемы."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from models.base import Base


class Database:
    """Владелец движка и фабрики сессий.

    Создаётся один раз при старте приложения и передаётся в middleware —
    глобальных соединений в модулях нет.
    """

    def __init__(self, url: str, *, use_static_pool: bool = False) -> None:
        kwargs: dict[str, object] = {}
        if use_static_pool:
            # Нужно для in-memory SQLite в тестах: одна общая соединение.
            kwargs["poolclass"] = StaticPool
            kwargs["connect_args"] = {"check_same_thread": False}
        self._engine: AsyncEngine = create_async_engine(url, **kwargs)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    async def init(self) -> None:
        """Создаёт таблицы, если их ещё нет."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        """Закрывает соединения с БД."""
        await self._engine.dispose()


def build_sqlite_url(path: str) -> str:
    """Собирает async-URL SQLite для файла или ``:memory:``."""
    if path == ":memory:":
        return "sqlite+aiosqlite:///:memory:"
    return f"sqlite+aiosqlite:///{path}"
