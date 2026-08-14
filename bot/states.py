"""Состояния FSM бота."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ProbivStates(StatesGroup):
    """Одно состояние на категорию входных данных."""

    MENU = State()
    PHONE = State()
    USERNAME = State()
    EMAIL = State()
    PHOTO = State()
    GOOGLE = State()