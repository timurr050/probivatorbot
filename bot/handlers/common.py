"""Базовые команды и навигация по меню (callbacks)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.db import DB
from bot.filters import IsAdmin
from bot.keyboards import (
    CATEGORY_FORMATS,
    CATEGORY_PROMPT_HINTS,
    TOOLS,
    main_menu,
    simple_menu,
    tools_menu,
)
from bot.states import ProbivStates
from bot.texts import (
    ABOUT_TEXT,
    FORMATS_TEXT,
    HELP_TEXT,
    NOT_ADMIN_TEXT,
    PROMPT_TEXT,
    START_TEXT,
)
from bot.utils.validators import EMAIL_FORMAT_HINT

router = Router(name="common")

_CMD_DESC = {
    "menu": ("🏠 Главное меню", main_menu),
    "help": ("❓ Помощь", None),
    "formats": ("📐 Форматы ввода", None),
    "about": ("ℹ️ О боте", None),
}


@router.message(IsAdmin(), CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    _record_user(message)
    await message.answer(START_TEXT, reply_markup=main_menu())


def _record_user(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    DB.upsert_user(
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        is_premium=bool(getattr(user, "is_premium", False)),
    )


@router.message(IsAdmin(), Command("menu", "help", "formats", "about"))
async def cmd_common(message: Message, command: Command) -> None:
    await _run_cmd(message, command.command)


@router.message(IsAdmin(), Command("history", "stats"))
async def cmd_db(message: Message, command: Command) -> None:
    _record_user(message)
    if command.command == "history":
        user = message.from_user
        rows = DB.history(user.id if user else 0, limit=10)
        if not rows:
            await message.reply("📂 История пуста — пока нет ни одного прогона.")
            return
        lines = ["<b>📂 Моя история (последние 10)</b>\n"]
        for r in rows:
            mark = {"ok": "✅", "partial": "⚠️", "error": "❌"}.get(r.status, "•")
            lines.append(
                f"{mark} <b>{r.category}</b> | {r.tool} | <code>{r.target}</code>\n"
                f"   {r.created_at}  #id{r.id}"
            )
        await message.reply("\n".join(lines), reply_markup=simple_menu())
        return

    s = DB.stats()
    cats = s["by_category"]
    statuses = s["by_status"]
    cat_line = ", ".join(f"{k}: {v}" for k, v in sorted(cats.items())) or "—"
    status_line = ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items())) or "—"
    text = (
        "<b>📊 Статистика бота</b>\n"
        f"👥 Пользователей: <code>{s['users']}</code>\n"
        f"🔎 Всего прогонов: <code>{s['searches']}</code>\n"
        f"📁 По категориям: <code>{cat_line}</code>\n"
        f"🚦 По статусам: <code>{status_line}</code>"
    )
    await message.reply(text, reply_markup=simple_menu())


@router.callback_query(IsAdmin(), F.data.startswith("cmd:"))
async def on_cmd_callback(call: CallbackQuery) -> None:
    cmd = call.data.split(":", 1)[1]
    await _run_cmd(call.message, cmd)
    try:
        await call.answer()
    except Exception:  # noqa: BLE001
        pass


async def _run_cmd(message: Message | None, cmd: str) -> None:
    if message is None:
        return
    if cmd in _CMD_DESC:
        title, kb_maker = _CMD_DESC[cmd]
        text = title
        if cmd == "help":
            text = HELP_TEXT
        elif cmd == "formats":
            text = FORMATS_TEXT
        elif cmd == "about":
            text = ABOUT_TEXT
        kb = kb_maker() if kb_maker else None
        await message.answer(text, reply_markup=kb)


@router.callback_query(IsAdmin(), F.data.startswith("cat:"))
async def on_cat_callback(call: CallbackQuery) -> None:
    category = call.data.split(":", 1)[1]
    text = f"<b>{_cat_emoji(category)} {_cat_label(category)}</b>\nВыберите движок:"
    await call.message.edit_text(text, reply_markup=tools_menu(category))
    try:
        await call.answer()
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(IsAdmin(), F.data.startswith("tool:"))
async def on_tool_callback(call: CallbackQuery, state: FSMContext) -> None:
    _, category, tool = call.data.split(":", 2)
    _state = {
        "phone": ProbivStates.PHONE,
        "username": ProbivStates.USERNAME,
        "email": ProbivStates.EMAIL,
        "photo": ProbivStates.PHOTO,
        "google": ProbivStates.GOOGLE,
    }.get(category, ProbivStates.MENU)
    await state.set_state(_state)
    await state.update_data(tool=tool, category=category)

    hint = CATEGORY_FORMATS.get(category, "")
    prompt = PROMPT_TEXT.format(
        label=CATEGORY_PROMPT_HINTS.get(category, category),
        hint=hint,
    )
    await call.message.edit_text(prompt, reply_markup=None)
    try:
        await call.answer()
    except Exception:  # noqa: BLE001
        pass


def _cat_emoji(category: str) -> str:
    return {
        "phone": "📱",
        "username": "🧑‍💻",
        "email": "📧",
        "photo": "🖼",
        "google": "🔮",
    }.get(category, "🔎")


def _cat_label(category: str) -> str:
    return {
        "phone": "Телефон",
        "username": "Никнейм",
        "email": "Email",
        "photo": "Фото и Видео",
        "google": "Google (GHunt)",
    }.get(category, category)