"""Конфигурация бота: загрузка переменных окружения.

Секреты не хранятся в коде — только в файле `.env` в корне проекта.
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    """Возвращает значение переменной окружения или выбрасывает ValueError."""
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ValueError(
            f"Не найдена переменная окружения {name}. "
            "Создайте файл .env в корне проекта (образец — .env.example) "
            "и укажите в нём токен бота, полученный у @BotFather."
        )
    return value.strip()


BOT_TOKEN: str = _require_env("BOT_TOKEN")

# Путь к файлу базы данных SQLite. Можно переопределить через .env.
DB_PATH: str = os.getenv("DB_PATH", "finance.db").strip() or "finance.db"
