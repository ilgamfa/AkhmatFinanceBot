"""Флоу «💰 Распределить»: закрепить деньги копилки за целью (Фаза 4)."""

from __future__ import annotations

from aiogram import F, Router
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
from services import allocations_repo, goals_repo, savings_repo
from services.calculations import goal_progress_percent
from utils.money import format_amount, format_rubles, parse_amount

CHOOSE_GOAL_TEXT = "К какой цели закрепить деньги?"
NO_GOALS_TEXT = "У тебя пока нет целей. Сначала добавь цель: /goals"
GOAL_NOT_FOUND_TEXT = "Цель не найдена"
CANCEL_TEXT = "Отменено"
ALLOCATE_PARSE_ERROR = "Не понял сумму. Напиши число, например: 50000"
POSITIVE_ERROR = "Сумма должна быть больше нуля."
INSUFFICIENT_TEXT = "Недостаточно свободных денег в копилке. Свободно: {amount}"

CALLBACK_START = "alloc:start"
CALLBACK_CANCEL = "alloc:cancel"
CANCEL_BUTTON_TEXT = "❌ Отмена"


class AllocateFlow(StatesGroup):
    """Ожидание суммы для закрепления за целью."""

    amount = State()


def _force_reply(prompt: str) -> ForceReply:
    return ForceReply(input_field_placeholder=prompt, selective=True)


def _goal_keyboard(
    goals: list[Goal], allocated_by_goal: dict[int, int]
) -> InlineKeyboardMarkup:
    """Кнопки целей с прогрессом: «1. Машина (400 000 / 1 500 000)»."""
    rows = []
    for index, goal in enumerate(goals, start=1):
        progress = allocated_by_goal.get(goal.id, 0)
        label = (
            f"{index}. {goal.name} "
            f"({format_rubles(progress)} / {format_rubles(goal.target)})"
        )
        if len(label) > 64:
            label = label[:61] + "..."
        rows.append(
            [
                InlineKeyboardButton(
                    text=label, callback_data=f"alloc:goal:{goal.id}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=CANCEL_BUTTON_TEXT, callback_data=CALLBACK_CANCEL
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def on_start_pressed(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """[💰 Распределить]: показывает список целей с кнопками."""
    await callback.answer()
    if callback.from_user is None or not isinstance(callback.message, Message):
        return
    telegram_id = callback.from_user.id
    goals = await goals_repo.get_goals(session, telegram_id)
    if not goals:
        await callback.message.answer(NO_GOALS_TEXT)
        return
    allocated = await allocations_repo.get_allocations_by_user(
        session, telegram_id
    )
    await callback.message.answer(
        CHOOSE_GOAL_TEXT, reply_markup=_goal_keyboard(goals, allocated)
    )


async def on_goal_picked(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """[N. Цель]: запрашивает сумму закрепления."""
    await callback.answer()
    if (
        callback.data is None
        or callback.from_user is None
        or not isinstance(callback.message, Message)
    ):
        return
    goal_id = int(callback.data.split(":")[-1])
    goal = await goals_repo.get_goal(session, callback.from_user.id, goal_id)
    if goal is None:
        await callback.message.answer(GOAL_NOT_FOUND_TEXT)
        return
    free = await savings_repo.get_free_in_savings(session, callback.from_user.id)
    prompt = (
        f"Сколько закрепить за целью «{goal.name}»? "
        f"Свободно в копилке: {format_amount(free)}"
    )
    await state.set_state(AllocateFlow.amount)
    await state.update_data(goal_id=goal_id)
    await callback.message.answer(prompt, reply_markup=_force_reply(prompt))


async def process_amount(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Принимает сумму закрепления и сохраняет связь."""
    if message.from_user is None:
        await state.clear()
        return
    data = await state.get_data()
    await state.clear()
    goal_id = data.get("goal_id")
    if goal_id is None:
        await message.answer(CANCEL_TEXT)
        return

    try:
        amount = parse_amount(message.text)
    except ValueError:
        await message.answer(ALLOCATE_PARSE_ERROR)
        return
    if amount <= 0:
        await message.answer(POSITIVE_ERROR)
        return

    telegram_id = message.from_user.id
    goal = await goals_repo.get_goal(session, telegram_id, goal_id)
    if goal is None:
        await message.answer(GOAL_NOT_FOUND_TEXT)
        return

    try:
        progress = await allocations_repo.allocate(session, goal_id, amount)
    except ValueError:
        free_now = await savings_repo.get_free_in_savings(session, telegram_id)
        await message.answer(INSUFFICIENT_TEXT.format(amount=format_amount(free_now)))
        return

    free_after = await savings_repo.get_free_in_savings(session, telegram_id)
    percent = goal_progress_percent(progress, goal.target)
    await message.answer(
        f"Закреплено за целью «{goal.name}»: {format_amount(amount)}\n"
        f"Прогресс: {format_rubles(progress)} / {format_rubles(goal.target)} ₽ "
        f"({percent}%)\n"
        f"Свободно в копилке: {format_amount(free_after)}"
    )


async def on_cancel_pressed(callback: CallbackQuery, state: FSMContext) -> None:
    """[❌ Отмена]: отменяет распределение."""
    await callback.answer()
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.answer(CANCEL_TEXT)


def build_router() -> Router:
    """Создаёт роутер флоу распределения."""
    router = Router(name="allocate")

    router.callback_query.register(on_start_pressed, F.data == CALLBACK_START)
    router.callback_query.register(
        on_goal_picked, F.data.regexp(r"^alloc:goal:\d+$")
    )
    router.callback_query.register(on_cancel_pressed, F.data == CALLBACK_CANCEL)
    router.message.register(
        process_amount, AllocateFlow.amount, ~F.text.startswith("/")
    )
    return router