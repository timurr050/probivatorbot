"""Обработка текстовых целей (телефон/ник/email) в состояниях FSM."""
from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.db import DB
from bot.exceptions import ProbivError, ServiceError, ToolNotConfigured
from bot.filters import IsAdmin
from bot.keyboards import after_result_menu
from bot.services import email_service, phone_service, username_service
from bot.states import ProbivStates
from bot.texts import STATUS_TEXT, error_text
from bot.utils.formatting import split_message
from bot.utils.validators import normalize_email, normalize_phone, normalize_username

router = Router(name="input")

NET_TIMEOUT = 60


async def _safe(fn, *args, note: str) -> tuple:
    """Запускает функцию с таймаутом, всегда возвращает (result|None, note|None)."""
    try:
        task = fn(*args) if asyncio.iscoroutinefunction(fn) else asyncio.to_thread(fn, *args)
        result = await asyncio.wait_for(task, timeout=NET_TIMEOUT)
        return result, None
    except asyncio.TimeoutError:
        return None, f"{note}: превышен таймаут"
    except (ToolNotConfigured, ServiceError, ProbivError) as exc:
        return None, f"{note}: {str(exc)}"
    except Exception as exc:  # noqa: BLE001
        return None, f"{note}: {type(exc).__name__}: {str(exc)[:120]}"


async def _send_report(message: Message, builder, target: str, tool: str, category: str):
    """Пайплайн: статус → построение отчёта → отправка (с цитированием запроса)."""
    user_id = message.from_user.id if message.from_user else 0
    status = await message.reply(STATUS_TEXT.format(target=target, tool=tool or "движок"))
    try:
        text = await builder(target)
    except ProbivError as exc:
        await status.edit_text(error_text(str(exc)))
        _log(user_id, category, tool, target, "error", str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        await status.edit_text(error_text(f"{type(exc).__name__}: {str(exc)}"))
        _log(user_id, category, tool, target, "error", f"{type(exc).__name__}: {str(exc)}")
        return

    await status.delete()
    parts = split_message(text)
    for i, part in enumerate(parts):
        if i == 0:
            await message.reply(part)
        else:
            await message.answer(part)
    await message.answer(
        "✔️ Готово. Результат собран из открытых источников.",
        reply_markup=after_result_menu(category, tool),
    )

    state = "partial" if "Частично не выполнено" in text else "ok"
    _log(user_id, category, tool, target, state, report=text)


def _log(user_id: int, category: str, tool: str, target: str,
         status: str, error: str | None = None, report: str | None = None) -> None:
    try:
        DB.log_search(user_id, category, tool, target, status, error=error, report=report)
    except Exception:  # noqa: BLE001 — БД не должна валить бота
        pass


def _join_notes(text: str, notes: list[str]) -> str:
    if not notes:
        return text
    return text + "\n\n<b>⚠️ Частично не выполнено:</b>\n" + "\n".join(notes)


# --------------------------------------------------------------------------
# Телефон
# --------------------------------------------------------------------------

async def phone_tool(target: str, tool: str) -> str:
    e164 = normalize_phone(target)
    notes: list[str] = []
    info, note = await _safe(phone_service.phonenumbers_info, e164, note="phonenumbers")
    if note:
        notes.append(note)

    pinf_lines = None
    if tool in ("all", "pinf"):
        raw, note = await _safe(phone_service.run_phoneinfoga, e164, note="PhoneInfoga")
        if note:
            notes.append(note)
        elif raw:
            pinf_lines = phone_service.summarize_phoneinfoga(raw, e164)

    phone_telegram = None
    if tool in ("all", "tg"):
        res, note = await _safe(phone_service.check_telegram, e164, note="Telegram")
        if note:
            notes.append(note)
        elif res:
            phone_telegram = res

    igr_map = None
    if tool in ("all", "ig"):
        raw, note = await _safe(phone_service.run_ignorant, e164, note="ignorant")
        if note:
            notes.append(note)
        elif raw:
            igr_map = phone_service.parse_ignorant(raw, e164)

    text = phone_service.format_phone_report(
        e164,
        info or {},
        telegram=phone_telegram,
        phoneinfoga=pinf_lines,
        ignorant=igr_map,
    )
    return _join_notes(text, notes)


@router.message(IsAdmin(), F.text, ProbivStates.PHONE)
async def phone_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tool = data.get("tool", "all")
    await _send_report(message, lambda t: phone_tool(t, tool), message.text, tool, "phone")


# --------------------------------------------------------------------------
# Никнейм
# --------------------------------------------------------------------------

async def username_tool(target: str, tool: str) -> str:
    username = normalize_username(target)
    notes: list[str] = []
    sherlock_lines = social_dict = snscrape_out = tg_dict = None

    if tool in ("all", "sherlock"):
        res, note = await _safe(username_service.run_sherlock, username, note="Sherlock")
        if note:
            notes.append(note)
        else:
            sherlock_lines = res

    if tool in ("all", "ss"):
        raw, note = await _safe(username_service.run_socialscan, f"@{username}", note="socialscan")
        if note:
            notes.append(note)
        else:
            social_dict = username_service.parse_socialscan(raw)

    if tool in ("all", "snscrape"):
        raw, note = await _safe(username_service.run_snscrape, username, note="snscrape")
        if note:
            notes.append(note)
        else:
            snscrape_out = raw

    if tool in ("all", "tg"):
        res, note = await _safe(username_service.telegram_user_lookup, username, note="Telegram")
        if note:
            notes.append(note)
        else:
            tg_dict = res

    text = username_service.format_username_report(
        username,
        sherlock=sherlock_lines,
        social=social_dict,
        snscrape_out=snscrape_out,
        telegram=tg_dict,
    )
    return _join_notes(text, notes)


@router.message(IsAdmin(), F.text, ProbivStates.USERNAME)
async def username_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tool = data.get("tool", "all")
    await _send_report(message, lambda t: username_tool(t, tool), message.text, tool, "username")


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------

async def email_tool(target: str, tool: str) -> str:
    email = normalize_email(target)
    notes: list[str] = []
    holehe_dict = h8mail_lines = social_dict = ghunt_dict = None

    if tool in ("all", "holehe"):
        raw, note = await _safe(email_service.run_holehe, email, note="holehe")
        if note:
            notes.append(note)
        else:
            holehe_dict = email_service.parse_holehe(raw, email)

    if tool in ("all", "h8mail"):
        raw, note = await _safe(email_service.run_h8mail, email, note="h8mail")
        if note:
            notes.append(note)
        else:
            h8mail_lines = email_service.parse_h8mail(raw, email)

    if tool in ("all", "ss"):
        raw, note = await _safe(username_service.run_socialscan, email, note="socialscan")
        if note:
            notes.append(note)
        else:
            social_dict = username_service.parse_socialscan(raw)

    if tool in ("all", "ghunt"):
        raw, note = await _safe(email_service.run_ghunt, email, note="GHunt")
        if note:
            notes.append(note)
        else:
            ghunt_dict = email_service.parse_ghunt(raw, email)

    text = email_service.format_email_report(
        email,
        holehe=holehe_dict,
        h8mail_out=h8mail_lines,
        social=social_dict,
        ghunt=ghunt_dict,
    )
    return _join_notes(text, notes)


@router.message(IsAdmin(), F.text, ProbivStates.EMAIL)
async def email_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tool = data.get("tool", "all")
    await _send_report(message, lambda t: email_tool(t, tool), message.text, tool, "email")