"""Обработка Google-разведки (GHunt) в состоянии GOOGLE."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.db import DB
from bot.exceptions import ProbivError
from bot.filters import IsAdmin
from bot.keyboards import after_result_menu
from bot.services.google_service import analyze_google
from bot.states import ProbivStates
from bot.texts import STATUS_TEXT, error_text
from bot.utils.formatting import split_message
from bot.utils.validators import normalize_email

router = Router(name="google")


@router.message(IsAdmin(), F.text, ProbivStates.GOOGLE)
async def google_input(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id if message.from_user else 0
    try:
        email = normalize_email(message.text)
    except ProbivError as exc:
        await message.reply(error_text(str(exc)))
        return

    data = await state.get_data()
    tool = data.get("tool", "all")
    status = await message.reply(STATUS_TEXT.format(target=email, tool="GHunt"))
    try:
        text = await analyze_google(email)
    except ProbivError as exc:
        await status.edit_text(error_text(str(exc)))
        _log(user_id, "google", tool, email, "error", str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        await status.edit_text(error_text(f"{type(exc).__name__}: {str(exc)}"))
        _log(user_id, "google", tool, email, "error", f"{type(exc).__name__}: {str(exc)}")
        return

    await status.delete()
    parts = split_message(text)
    for i, part in enumerate(parts):
        if i == 0:
            await message.reply(part)
        else:
            await message.answer(part)
    await message.answer(
        "✔️ Готово. Данные собраны из открытых источников.",
        reply_markup=after_result_menu("google", tool),
    )
    _log(user_id, "google", tool, email, "ok", report=text)


def _log(user_id: int, category: str, tool: str, target: str,
         status: str, error: str | None = None, report: str | None = None) -> None:
    try:
        DB.log_search(user_id, category, tool, target, status, error=error, report=report)
    except Exception:  # noqa: BLE001
        pass