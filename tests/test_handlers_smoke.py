"""Смоук-тесты кнопок и навигации (без сети и Telegram API).

Используем фейковые объекты aiogram, чтобы прогнать логику обработчиков.
"""
from __future__ import annotations

import pytest

from bot.handlers.common import on_cat_callback, on_cmd_callback, on_tool_callback
from bot.keyboards import after_result_menu, main_menu, tools_menu


class FakeCall:
    def __init__(self, data: str):
        self.data = data
        self.message = FakeMsg()
        self.answered = False

    async def answer(self, *a, **k):
        self.answered = True

    def __getattr__(self, item):  # от NetworkError при exception handling
        if item in ("from_user", "chat"):
            return None
        raise AttributeError(item)


class FakeMsg:
    def __init__(self):
        self.edited_text = None
        self.edited_kb = None
        self.answered_text = None
        self.answered_kb = None

    async def edit_text(self, text, reply_markup=None):
        self.edited_text = text
        self.edited_kb = reply_markup

    async def answer(self, text=None, reply_markup=None, **kwargs):
        self.answered_text = text
        self.answered_kb = reply_markup

    def __getattr__(self, item):
        if item in ("from_user", "chat", "message_id", "bot"):
            return None
        raise AttributeError(item)


class FakeState:
    def __init__(self):
        self.state = None
        self.data = {}

    async def set_state(self, state):
        self.state = state

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def get_data(self):
        return self.data


class TestCallbackCoverage:
    """Каждая data из клавиатуры должна иметь обработчик в common.py."""

    def _collect(self, kb):
        out = []
        for row in kb.inline_keyboard:
            for btn in row:
                out.append(btn.callback_data)
        return out

    def test_menu_callbacks_covered(self):
        for data in self._collect(main_menu()):
            assert data.startswith(("cat:", "cmd:")), data

    def test_tools_callbacks_covered(self):
        for cat in ("phone", "username", "email", "photo", "google"):
            for data in self._collect(tools_menu(cat)):
                assert data.startswith(("tool:", "cmd:")), data

    def test_after_result_callbacks_covered(self):
        for data in self._collect(after_result_menu("phone", "all")):
            assert data.startswith(("tool:", "cat:", "cmd:")), data


class TestNavigation:
    @pytest.mark.asyncio
    async def test_cat_opens_tools_menu(self):
        call = FakeCall("cat:phone")
        await on_cat_callback(call)
        assert "Выберите движок" in call.message.edited_text
        assert call.message.edited_kb is not None

    @pytest.mark.asyncio
    async def test_category_maps_to_proper_state(self):
        from bot.states import ProbivStates

        cases = {
            "phone": ProbivStates.PHONE,
            "username": ProbivStates.USERNAME,
            "email": ProbivStates.EMAIL,
            "photo": ProbivStates.PHOTO,
            "google": ProbivStates.GOOGLE,
        }
        for cat, state in cases.items():
            call = FakeCall(f"tool:{cat}:all")
            fake_state = FakeState()
            await on_tool_callback(call, fake_state)
            assert fake_state.state == state, cat
            assert fake_state.data.get("tool") == "all"
            assert fake_state.data.get("category") == cat

    @pytest.mark.asyncio
    async def test_cmd_menu_existing(self):
        call = FakeCall("cmd:formats")
        await on_cmd_callback(call)
        assert call.message.answered_text is not None
        assert "Формат ввода" in call.message.answered_text
        assert call.answered is True