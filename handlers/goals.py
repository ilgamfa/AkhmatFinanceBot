"""Команда /goals: цели и кнопки управления (Фаза 4)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from models import Goal
from services import allocations_repo, goals_repo
from services.calculations import (
    format_goal_deadline,
    goal_emoji,
    goal_progress_percent,
    monthly_goal_amount,
    parse_goal_deadline,
)
from utils.money import format_amount, format_rubles, parse_amount

NO_GOALS_TEXT = "У тебя пока нет целей"
GOAL_NOT_FOUND_TEXT = "Цель не найдена"
GOAL_DONE_PREFIX = "Цель добавлена: "
GOAL_UPDATED_PREFIX = "Цель обновлена: "
GOAL_DELETED_PREFIX = "Цель удалена: "
EDIT_LIST_TITLE = "Выбери цель для редактирования:"
DELETE_LIST_TITLE = "Выбери цель для удаления:"
FIELDS_TITLE = "Что изменить?"
CANCEL_TEXT = "Отменено"

ADD_BUTTON_TEXT = "➕ Добавить цель"
ALLOCATE_BUTTON_TEXT = "💰 Распределить"
EDIT_BUTTON_TEXT = "✏️ Редактировать"
DELETE_BUTTON_TEXT = "🗑 Удалить"
CANCEL_BUTTON_TEXT = "❌ Отмена"

CALLBACK_ADD = "goals:add"
CALLBACK_ALLOCATE = "alloc:start"
CALLBACK_EDIT_LIST = "goals:edit"
CALLBACK_DELETE_LIST = "goals:del"
CALLBACK_EDIT_CANCEL = "goals_edit:cancel"
CALLBACK_DELETE_CANCEL = "goals_del:cancel"

NAME_PROMPT = "Название цели? Например: Машина"
TARGET_PROMPT = "Целевая сумма? Например: 1500000"
DEADLINE_PROMPT = (
    "К какому сроку? Напиши дату: 01.12.2027. "
    "Или напиши skip, если срока нет."
)
PRIORITY_PROMPT = "Приоритет цели?"

EDIT_NAME_PROMPT = "Новое название? Например: Машина"
EDIT_TARGET_PROMPT = "Новая сумма? Например: 1500000"
EDIT_DEADLINE_PROMPT = "Новый срок? Напиши дату: 01.12.2027 или skip."

PRIORITY_LABELS = {1: "Высокий", 2: "Средний", 3: "Низкий"}


class GoalFlow(StatesGroup):
    """Шаги добавления цели."""

    name = State()
    target = State()
    deadline = State()
    priority = State()


class GoalEditFlow(StatesGroup):
    """Шаги редактирования цели."""

    field_value = State()


def _force_reply(prompt: str) -> ForceReply:
    return ForceReply(input_field_placeholder=prompt, selective=True)


def _priority_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=label, callback_data=f"goal_priority:{value}")
        for value, label in PRIORITY_LABELS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def _manage_keyboard() -> InlineKeyboardMarkup:
    """Кнопки управления списком целей."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=ADD_BUTTON_TEXT, callback_data=CALLBACK_ADD
                ),
                InlineKeyboardButton(
                    text=ALLOCATE_BUTTON_TEXT, callback_data=CALLBACK_ALLOCATE
                ),
            ],
            [
                InlineKeyboardButton(
                    text=EDIT_BUTTON_TEXT, callback_data=CALLBACK_EDIT_LIST
                ),
                InlineKeyboardButton(
                    text=DELETE_BUTTON_TEXT, callback_data=CALLBACK_DELETE_LIST
                ),
            ],
        ]
    )


def _empty_keyboard() -> InlineKeyboardMarkup:
    """Кнопки при пустом списке — только добавление."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=ADD_BUTTON_TEXT, callback_data=CALLBACK_ADD)]
        ]
    )


def _goal_select_keyboard(
    goals: list[Goal], prefix: str, cancel_callback: str
) -> InlineKeyboardMarkup:
    """Кнопки целей для выбора в списках редактирования/удаления."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"{index}. {goal.name}", callback_data=f"{prefix}{goal.id}"
            )
        ]
        for index, goal in enumerate(goals, start=1)
    ]
    rows.append(
        [InlineKeyboardButton(text=CANCEL_BUTTON_TEXT, callback_data=cancel_callback)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _edit_fields_keyboard() -> InlineKeyboardMarkup:
    """Кнопки выбора поля цели для редактирования."""
    rows = [
        [
            InlineKeyboardButton(text="Название", callback_data="goal_field:name"),
            InlineKeyboardButton(text="Сумма", callback_data="goal_field:target"),
            InlineKeyboardButton(text="Срок", callback_data="goal_field:deadline"),
        ],
        [
            InlineKeyboardButton(
                text="Приоритет", callback_data="goal_field:priority"
            ),
            InlineKeyboardButton(
                text=CANCEL_BUTTON_TEXT, callback_data=CALLBACK_EDIT_CANCEL
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_goal_summary(goal: Goal) -> str:
    """«Машина — 1 500 000 ₽ до 01.12.2027» (без срока — без «до …»)."""
    deadline = format_goal_deadline(goal.deadline)
    body = f"{goal.name} — {format_amount(goal.target)}"
    if deadline:
        body += f" до {deadline}"
    return body


def format_goals_list(
    goals: list[Goal],
    allocated_by_goal: dict[int, int] | None = None,
    today: date | None = None,
) -> str:
    """Собирает текст списка целей: прогресс из связей копилки и итог."""
    today = today or datetime.now(UTC).date()
    allocated_by_goal = allocated_by_goal or {}
    lines = ["Твои цели:", ""]
    for index, goal in enumerate(goals, start=1):
        progress = allocated_by_goal.get(goal.id, 0)
        percent = goal_progress_percent(progress, goal.target)
        lines.append(
            f"{index}. {goal_emoji(goal.name)} {goal.name}: "
            f"{format_rubles(progress)} / {format_rubles(goal.target)} ₽ "
            f"({percent}%)"
        )
        deadline = format_goal_deadline(goal.deadline)
        if deadline:
            lines.append(f"   Срок: {deadline}")
        monthly = monthly_goal_amount(progress, goal.target, goal.deadline, today)
        if monthly is not None:
            lines.append(f"   Нужно в месяц: {format_amount(monthly)}")
    lines.append("")
    lines.append(
        f"Итого закреплено: {format_amount(sum(allocated_by_goal.values()))} ₽"
    )
    return "\n".join(lines)


async def cmd_goals(message: Message, session: AsyncSession) -> None:
    """Показывает список целей с кнопками управления."""
    if message.from_user is None:
        return

    goals = await goals_repo.get_goals(session, message.from_user.id)
    if not goals:
        await message.answer(NO_GOALS_TEXT, reply_markup=_empty_keyboard())
        return
    allocated = await allocations_repo.get_allocations_by_user(
        session, message.from_user.id
    )
    await message.answer(
        format_goals_list(goals, allocated), reply_markup=_manage_keyboard()
    )


async def on_add_pressed(callback: CallbackQuery, state: FSMContext) -> None:
    """[➕ Добавить цель]: запускает пошаговое добавление."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await state.set_state(GoalFlow.name)
    await callback.message.answer(
        NAME_PROMPT, reply_markup=_force_reply(NAME_PROMPT)
    )


async def process_name(message: Message, state: FSMContext) -> None:
    """Шаг 1: название цели."""
    name = (message.text or "").strip()
    if not name:
        await message.answer("Напиши название. Например: Машина")
        return
    await state.update_data(name=name)
    await state.set_state(GoalFlow.target)
    await message.answer(TARGET_PROMPT, reply_markup=_force_reply(TARGET_PROMPT))


async def process_target(message: Message, state: FSMContext) -> None:
    """Шаг 2: целевая сумма."""
    try:
        target = parse_amount(message.text)
    except ValueError:
        await message.answer("Не понял сумму. Напиши число, например: 1500000")
        return
    if target <= 0:
        await message.answer("Сумма должна быть больше нуля. Попробуй ещё раз.")
        return
    await state.update_data(target=target)
    await state.set_state(GoalFlow.deadline)
    await message.answer(DEADLINE_PROMPT, reply_markup=_force_reply(DEADLINE_PROMPT))


async def process_deadline(message: Message, state: FSMContext) -> None:
    """Шаг 3: срок (дата или skip)."""
    try:
        deadline = parse_goal_deadline(message.text)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(deadline=deadline)
    await state.set_state(GoalFlow.priority)
    await message.answer(PRIORITY_PROMPT, reply_markup=_priority_keyboard())


async def process_priority(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Шаг 4: приоритет и сохранение цели."""
    if callback.data is None or callback.from_user is None:
        return
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    priority = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    await state.clear()
    goal = await goals_repo.add_goal(
        session,
        callback.from_user.id,
        data["name"],
        data["target"],
        data["deadline"],
        priority,
    )
    await message.answer(f"{GOAL_DONE_PREFIX}{format_goal_summary(goal)}")


async def on_edit_list_pressed(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[✏️ Редактировать]: показывает список целей с кнопками."""
    await callback.answer()
    if callback.from_user is None or not isinstance(callback.message, Message):
        return
    goals = await goals_repo.get_goals(session, callback.from_user.id)
    if not goals:
        await callback.message.answer(NO_GOALS_TEXT)
        return
    await callback.message.answer(
        EDIT_LIST_TITLE,
        reply_markup=_goal_select_keyboard(
            goals, "goal_edit:", CALLBACK_EDIT_CANCEL
        ),
    )


async def on_edit_goal_picked(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """[N. Название]: показывает поля цели для редактирования."""
    await callback.answer()
    if callback.data is None or not isinstance(callback.message, Message):
        return
    goal_id = int(callback.data.split(":", 1)[1])
    await state.set_state(GoalEditFlow.field_value)
    await state.update_data(goal_id=goal_id)
    await callback.message.answer(FIELDS_TITLE, reply_markup=_edit_fields_keyboard())


async def on_edit_field_pressed(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """[Название/Сумма/Срок/Приоритет]: запрашивает новое значение."""
    await callback.answer()
    if callback.data is None or not isinstance(callback.message, Message):
        return
    data = await state.get_data()
    if "goal_id" not in data:
        await state.clear()
        await callback.message.answer(CANCEL_TEXT)
        return

    field = callback.data.split(":", 1)[1]
    if field == "priority":
        await state.update_data(field="priority")
        await callback.message.answer(
            PRIORITY_PROMPT, reply_markup=_priority_keyboard()
        )
        return

    prompts = {
        "name": EDIT_NAME_PROMPT,
        "target": EDIT_TARGET_PROMPT,
        "deadline": EDIT_DEADLINE_PROMPT,
    }
    await state.update_data(field=field)
    await callback.message.answer(
        prompts[field], reply_markup=_force_reply(prompts[field])
    )


async def process_edit_message(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Новое значение поля цели."""
    if message.from_user is None:
        await state.clear()
        return

    data = await state.get_data()
    goal_id = data.get("goal_id")
    field = data.get("field")
    if goal_id is None or field is None:
        await state.clear()
        await message.answer(CANCEL_TEXT)
        return

    if field == "name":
        value = (message.text or "").strip()
        if not value:
            await message.answer("Напиши название. Например: Машина")
            return
    elif field == "target":
        try:
            value = parse_amount(message.text)
        except ValueError:
            await message.answer("Не понял сумму. Напиши число, например: 1500000")
            return
        if value <= 0:
            await message.answer("Сумма должна быть больше нуля. Попробуй ещё раз.")
            return
    else:
        try:
            value = parse_goal_deadline(message.text)
        except ValueError as exc:
            await message.answer(str(exc))
            return

    await state.clear()
    updated = await goals_repo.update_goal(
        session, message.from_user.id, goal_id, **{field: value}
    )
    if updated is None:
        await message.answer(GOAL_NOT_FOUND_TEXT)
        return
    await message.answer(f"{GOAL_UPDATED_PREFIX}{format_goal_summary(updated)}")


async def process_edit_priority(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Выбор нового приоритета цели (кнопки)."""
    if callback.data is None or callback.from_user is None:
        return
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    data = await state.get_data()
    goal_id = data.get("goal_id")
    await state.clear()
    if goal_id is None:
        await message.answer(CANCEL_TEXT)
        return

    priority = int(callback.data.split(":", 1)[1])
    updated = await goals_repo.update_goal(
        session, callback.from_user.id, goal_id, priority=priority
    )
    if updated is None:
        await message.answer(GOAL_NOT_FOUND_TEXT)
        return
    await message.answer(f"{GOAL_UPDATED_PREFIX}{format_goal_summary(updated)}")


async def on_edit_cancel_pressed(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """[❌ Отмена]: отменяет редактирование."""
    await callback.answer()
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.answer(CANCEL_TEXT)


async def on_delete_list_pressed(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[🗑 Удалить]: показывает список целей с кнопками."""
    await callback.answer()
    if callback.from_user is None or not isinstance(callback.message, Message):
        return
    goals = await goals_repo.get_goals(session, callback.from_user.id)
    if not goals:
        await callback.message.answer(NO_GOALS_TEXT)
        return
    await callback.message.answer(
        DELETE_LIST_TITLE,
        reply_markup=_goal_select_keyboard(
            goals, "goal_del:", CALLBACK_DELETE_CANCEL
        ),
    )


async def on_delete_goal_pressed(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[N. Название]: удаляет выбранную цель."""
    await callback.answer()
    if (
        callback.data is None
        or callback.from_user is None
        or not isinstance(callback.message, Message)
    ):
        return
    goal_id = int(callback.data.split(":", 1)[1])
    goal = await goals_repo.get_goal(session, callback.from_user.id, goal_id)
    if goal is None:
        await callback.message.answer(GOAL_NOT_FOUND_TEXT)
        return
    await goals_repo.delete_goal(session, callback.from_user.id, goal_id)
    await callback.message.answer(
        f"{GOAL_DELETED_PREFIX}{goal.name}. "
        "Связи сняты, деньги вернулись в свободные копилки."
    )


async def on_delete_cancel_pressed(callback: CallbackQuery) -> None:
    """[❌ Отмена]: отменяет удаление."""
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(CANCEL_TEXT)


def build_router() -> Router:
    """Создаёт роутер команды /goals."""
    router = Router(name="goals")

    router.message.register(cmd_goals, Command("goals"))
    router.message.register(process_name, GoalFlow.name, ~F.text.startswith("/"))
    router.message.register(process_target, GoalFlow.target, ~F.text.startswith("/"))
    router.message.register(
        process_deadline, GoalFlow.deadline, ~F.text.startswith("/")
    )
    router.message.register(
        process_edit_message,
        GoalEditFlow.field_value,
        ~F.text.startswith("/"),
    )

    router.callback_query.register(on_add_pressed, F.data == CALLBACK_ADD)
    router.callback_query.register(
        on_edit_list_pressed, F.data == CALLBACK_EDIT_LIST
    )
    router.callback_query.register(
        on_delete_list_pressed, F.data == CALLBACK_DELETE_LIST
    )
    router.callback_query.register(
        on_edit_goal_picked, F.data.regexp(r"^goal_edit:\d+$")
    )
    router.callback_query.register(
        on_edit_field_pressed, F.data.regexp(r"^goal_field:(name|target|deadline|priority)$")
    )
    router.callback_query.register(
        process_priority, GoalFlow.priority, F.data.startswith("goal_priority:")
    )
    router.callback_query.register(
        process_edit_priority,
        GoalEditFlow.field_value,
        F.data.startswith("goal_priority:"),
    )
    router.callback_query.register(
        on_edit_cancel_pressed, F.data == CALLBACK_EDIT_CANCEL
    )
    router.callback_query.register(
        on_delete_goal_pressed, F.data.regexp(r"^goal_del:\d+$")
    )
    router.callback_query.register(
        on_delete_cancel_pressed, F.data == CALLBACK_DELETE_CANCEL
    )
    return router