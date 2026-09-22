# AGENTS.md

## Контекст проекта

Telegram-бот «Карманный финсоветник» для планирования личных и семейных финансов.
Показывает будущее денег: свободный остаток, ближайшие платежи, цели, советы.

Публичное имя бота — «Карманный финсоветник» (используется в `/start` и текстах бота).

**Главный документ:** `PRD.md` в корне проекта. Всегда читай его перед началом работы.
Если задача не описана в PRD — спроси, прежде чем делать.

## Стек

- Python 3.12+
- aiogram 3.x
- SQLAlchemy 2.0 async + aiosqlite
- SQLite (MVP), PostgreSQL (позже)
- Конфиг: python-dotenv (`.env`)
- Parse mode: legacy Markdown (только там, где нужно)
- Хостинг: VPS в РФ
- LLM для советов: API (Фаза 8)
- Тесты: pytest + pytest-asyncio, БД для тестов — in-memory SQLite
- Линтер: ruff

## Команды

```bash
source .venv/bin/activate       # активация окружения
pip install -r requirements.txt # зависимости
python bot.py                   # запуск бота
pytest                          # тесты
ruff check .                    # линтер
python -m py_compile bot.py     # проверка синтаксиса
```

## Структура проекта

```
~/dev/Economic/
├── .agents/skills/       # скиллы (telegram-bot, xlsx)
├── PRD.md                # главный документ
├── AGENTS.md             # этот файл
├── opencode.json         # конфиг OpenCode
├── requirements.txt      # зависимости
├── pyproject.toml        # конфиг ruff и pytest
├── .env                  # секреты (не коммитить)
├── .env.example          # шаблон переменных окружения
├── bot.py                # точка входа
├── config.py             # токены, настройки
├── models/               # ORM-модели и подключение к БД
├── handlers/             # обработчики команд (роутеры)
├── services/             # логика (расчёты, репозитории, экраны)
├── utils/                # утилиты (деньги)
└── tests/                # тесты
```

## Правила кода

- Python 3.12+, async/await для всего I/O.
- Типизация обязательна для публичных функций.
- `snake_case` для функций, `PascalCase` для классов.
- БД — только асинхронные вызовы. Никаких синхронных запросов в хендлерах.
- Секреты и настройки — только через `config.py` и `.env`; токен не хардкодить.
- Роутеры собираются функциями `build_router()` в `handlers/` (чтобы диспетчер можно было пересоздавать в тестах).
- Бизнес-логика — в `services/` (чистые функции и репозитории), хендлеры тонкие.
- **Parse mode:** legacy Markdown, только там, где нужна разметка. Для заголовков — `*Заголовок*`. Не использовать HTML.
- **Не менять ORM** без явного указания.

## Работа с БД

- ORM — SQLAlchemy 2.0 async + aiosqlite.
- Движок и фабрика сессий — в классе `Database` (`models/database.py`).
- Сессия внедряется в хендлеры через middleware. Глобальных соединений нет.
- Суммы хранятся целыми рублями (`INTEGER`).
- `create_all` не меняет существующие таблицы — при смене полей удаляй dev-БД `finance.db`.

### Актуальные таблицы (9)

**`users`** — `id`, `telegram_id` (BigInteger, unique, index), `advice_style` (String(16), default `"soft"`), `onboarding_completed` (Boolean, default `False`), `income_type` (String(16), nullable), `income_dates` (Text, JSON), `income` (Integer, nullable), `created_at` (DateTime tz).
**Поля `free_money` нет** — баланс в `accounts.balance` для `type="card"`.

**`transactions`** — `id`, `telegram_id` (BigInteger, index), `account_id` (Integer, index, nullable), `category_id` (Integer, nullable, index), `type` (String(16), `expense`/`income`/`correction`/`savings_add`), `amount` (Integer), `created_at` (String(40), ISO).

**`debts`** — `id`, `telegram_id` (BigInteger, index), `name` (String(64)), `type` (String(16), `loan`/`mortgage`/`credit_card`/`installment`), `amount` (Integer), `payment_day` (Integer, 1–31), `created_at` (String(40), ISO).

**`accounts`** — `id`, `telegram_id` (BigInteger, index), `family_id` (Integer, index, nullable), `type` (String(16), `card`/`savings`), **`name` (String(64), NOT NULL)** — обязательно, спрашивается в онбординге, `balance` (Integer, default 0), `created_at` (String(40), ISO).
**UNIQUE-ограничение:** `(telegram_id, type)` — одна карта и одна копилка на пользователя.

**`goals`** — `id`, `telegram_id` (BigInteger, index), `family_id` (Integer, index, nullable), `name` (String(64)), `target` (Integer), `deadline` (String(10), ISO, nullable), `priority` (Integer, 1–3), `created_at` (String(40), ISO).

**`allocations`** — `id`, `goal_id` (BigInteger, index), `telegram_id` (BigInteger, index), `amount` (Integer).

**`families`** — `id`, `name` (String(64)), `invite_code` (String(8), unique, index), `created_at` (String(40), ISO).

**`family_members`** — `id`, `family_id` (Integer, FK `families.id`, index), `telegram_id` (BigInteger, index, UniqueConstraint), `role` (String(16), `owner`/`member`), `first_name` (String(64), nullable).

**`categories`** — `id`, `telegram_id` (BigInteger, index), `name` (String(64)), `type` (String(16), `expense`/`income`), `is_custom` (Boolean, default False), `created_at` (String(40), ISO).

### Репозитории

- `services/accounts_repo.py` — `create_accounts`, `get_balance`, `get_account`, `get_accounts`, `get_family_accounts`, `update_balance`, `correct_balance`, `rename_account`.
- `services/transactions_repo.py` — операции с транзакциями.
- `services/debts_repo.py` — операции с долгами.
- `services/goals_repo.py` — операции с целями.
- `services/allocations_repo.py` — `allocate`, `unallocate`, `get_allocations_by_goal`, `get_allocations_by_user`.
- `services/family_repo.py` — `create_family`, `join_family`, `get_family`, `get_family_members`.
- `services/categories_repo.py` — `get_categories`, `add_category`, `get_default_categories`.

## Логика расчётов

- **Свободные деньги** = `accounts.balance` при `type="card"`.
- **Копилка** = `accounts.balance` при `type="savings"`.
- **Свободно в копилке** = `savings.balance` − сумма `allocations` пользователя.
- **Прогресс цели** = сумма `allocations` по цели (с обоих `savings`, если семья).
- **Обязательные платежи** уменьшают «Свободно до ЗП» и «Свободно до конца месяца» в `/stats`.
- **Разделение статистики по участникам** (Фаза 5.1): `/stats` показывает кнопки `[📊 Общая]` `[👤 Имя1]` `[👤 Имя2]`. При нажатии — редактировать сообщение через `edit_message_text`. Для одиночки — без кнопок.
- **Вердикт «хватает / не хватает»** (Фаза 5.1): для каждого платежа до конца месяца сравнить свободные деньги владельца долга (`accounts.balance` для `type="card"`) с суммой платежа. Доход не учитывать. Накопительная проверка внутри одного дня. Между днями — не накопительно.
- **Прогноз** (`/forecast`): свободно + доход до конца месяца − платежи долгов − «нужно в месяц» на цели.
- **`/minus`** уменьшает баланс `card`, **`/plus`** увеличивает, **`/correct`** задаёт новое значение. Все пишут в `transactions`.
- **`/savings add N`** списывает N из `card`, кладёт в `savings`, пишет `savings_add`.
- **Категории** (Фаза 6): при `/minus` и `/plus` без категории — показать кнопки. При выборе — сохранить `category_id`. Кнопка `[➕ Своя]` — ForceReply + `add_category`. Кнопка `[❌ Без категории]` — сохранить без `category_id`. Топ-3 категорий за месяц в `/stats`.
- **Счета создаёт онбординг.** При вступлении в семью счета заранее не создаются: счета нового участника создаёт онбординг сразу с балансом карты и `family_id`; уже прошедшему онбординг при вступлении проставляется `family_id` у существующих счетов.
- Если покупка ломает план — предупредить, но не запрещать.

## Скиллы

Скиллы лежат в `.agents/skills/`:
- `telegram-bot` — паттерны aiogram, хендлеры, FSM.
- `xlsx` — экспорт (Фаза 8).

Загружай нужный скилл через инструмент `skill` и следуй его инструкциям.

## Документация

- `PRD.md` — что строим (продукт, команды, модель данных, фазы). Только актуальное состояние и активные задачи.
- `AGENTS.md` — как строим (стек, правила, схема БД, репозитории). Только актуальные правила.
- `CHANGELOG.md` — история выполненного.
- `TODO.md` — активные задачи.

После завершения пункта или фазы:
1. Отметить пункт в TODO.md как выполненный или удалить его.
2. Добавить выполненное в CHANGELOG.md.
3. Убрать выполненное из PRD.md и AGENTS.md.
4. Если изменилась схема БД или правила — обновить AGENTS.md.

## Фазы разработки

| Фаза | Название | Статус |
|---|---|---|
| 1–5 | Онбординг, операции, долги, копилка/цели, семья | ✅ (см. CHANGELOG.md) |
| 5.1 | Фиксы Фазы 5 | ✅ (см. CHANGELOG.md) |
| 6 | Категории | ✅ (см. CHANGELOG.md) |
| 7 | /can, советы, напоминания | ⏳ |
| 8 | LLM-советник, экспорт | ⏳ |

## Что НЕ делать (глобально)

- ❌ Автоподгрузка из банков.
- ❌ Несколько карт у одного пользователя.
- ❌ Скрытые счета.
- ❌ Инвестиции, налоги.
- ❌ Веб-интерфейс.
- ❌ Хранение данных вне РФ.
- ❌ Синхронные запросы к БД в хендлерах.
- ❌ Хардкод токена.