"""Обработка текстовых целей (телефон/ник/email) в состояниях FSM."""
from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import SETTINGS
from bot.db import DB
from bot.exceptions import ProbivError, ServiceError, ToolNotConfigured
from bot.filters import IsAdmin
from bot.handlers.common import _STATE_BY_CATEGORY
from bot.keyboards import after_result_menu
from bot.services import email_service, phone_service, username_service
from bot.services import public_api as public_api_service
from bot.services import maigret_service, registration_service, twscrape_service
from bot.states import ProbivStates
from bot.texts import STATUS_TEXT, error_text
from bot.utils.formatting import split_message
from bot.utils.validators import normalize_email, normalize_phone, normalize_username

import uuid

# Хранилище постраничных отчётов (один процесс бота). Ключ -> страницы + мета.
_PAGER: dict[str, dict] = {}
_PAGER_MAX = 200
PAGE_SIZE = 3800


def _pager_store(pages: list[str], category: str, tool: str) -> str:
    key = uuid.uuid4().hex[:12]
    _PAGER[key] = {"pages": pages, "category": category, "tool": tool}
    if len(_PAGER) > _PAGER_MAX:
        # вытесняем самый старый ключ
        old = next(iter(_PAGER))
        _PAGER.pop(old, None)
    return key


def _pager_keyboard(key: str, idx: int, total: int, category: str, tool: str) -> InlineKeyboardMarkup:
    """Клавиатура навигации по страницам + кнопки повтора/меню."""
    builder = InlineKeyboardBuilder()
    nav: list[InlineKeyboardButton] = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"pg:{key}:{idx - 1}"))
    nav.append(InlineKeyboardButton(text=f"📄 {idx + 1}/{total}", callback_data=f"pg:{key}:{idx}"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"pg:{key}:{idx + 1}"))
    if nav:
        builder.row(*nav)
    # кнопки «Повторить / ТГ / Ключи / Меню» из after_result_menu
    for row in after_result_menu(category, tool).inline_keyboard:
        builder.row(*row)
    return builder.as_markup()

router = Router(name="input")

# Внешний таймаут должен быть больше внутренних (cli_timeout), чтобы движки
# успевали сами завершить и убить свои подпроцессы (а не отменяться снаружи).
NET_TIMEOUT = SETTINGS.cli_timeout + 30


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


async def _safe_many(specs: list[tuple[str, object, tuple, str]]) -> dict[str, tuple]:
    """Запускает движки параллельно. specs: (ключ, функция, args, note).

    Возвращает {ключ: (результат|None, note|None)}. Упавший движок не роняет
    остальных — это и есть «Всё сразу» без потери всего отчёта.
    """
    coros = [_safe(fn, *args, note=note) for _, fn, args, note in specs]
    outcomes = await asyncio.gather(*coros)
    return {key: outcome for (key, _, _, _), outcome in zip(specs, outcomes)}


async def _send_report(message: Message, builder, target: str, tool: str, category: str,
                       state: FSMContext | None = None) -> None:
    """Пайплайн: статус → построение отчёта → отправка (с цитированием запроса)."""
    user_id = message.from_user.id if message.from_user else 0
    if state is not None:
        await state.update_data(last_target=target, last_category=category)
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
    parts = split_message(text, max_len=PAGE_SIZE)
    key = _pager_store(parts, category, tool)
    kb = _pager_keyboard(key, 0, len(parts), category, tool)
    await message.reply(parts[0], reply_markup=kb)
    # одно сообщение-«моталка»: навигация переключает страницы в нём же.

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
    specs: list[tuple[str, object, tuple, str]] = [
        ("info", phone_service.phonenumbers_info, (e164,), "phonenumbers"),
    ]
    if tool in ("all", "reg"):
        specs.append(("reg", registration_service.check_registrations, (e164, "phone"), "регистрации"))
    if tool in ("all", "pinf"):
        specs.append(("pinf", phone_service.run_phoneinfoga, (e164,), "PhoneInfoga"))
    if tool in ("all", "tg"):
        specs.append(("tg", phone_service.check_telegram, (e164,), "Telegram"))
    if tool in ("all", "ig"):
        specs.append(("ig", phone_service.run_ignorant, (e164,), "ignorant"))

    out = await _safe_many(specs)
    notes: list[str] = []

    info = out["info"][0] or {}
    if out["info"][1]:
        notes.append(out["info"][1])

    registrations = None
    if "reg" in out:
        res, note = out["reg"]
        if note:
            notes.append(note)
        elif res:
            registrations = res

    pinf_lines = None
    if "pinf" in out:
        raw, note = out["pinf"]
        if note:
            notes.append(note)
        elif raw:
            pinf_lines = phone_service.summarize_phoneinfoga(raw, e164)

    phone_telegram = None
    if "tg" in out:
        res, note = out["tg"]
        if note:
            notes.append(note)
        elif res:
            phone_telegram = res

    igr_map = None
    if "ig" in out:
        raw, note = out["ig"]
        if note:
            notes.append(note)
        elif raw:
            igr_map = phone_service.parse_ignorant(raw, e164)

    text = phone_service.format_phone_report(
        e164,
        info,
        telegram=phone_telegram,
        phoneinfoga=pinf_lines,
        ignorant=igr_map,
        registrations=registrations,
    )
    return _join_notes(text, notes)


@router.message(IsAdmin(), F.text, ProbivStates.PHONE)
async def phone_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tool = data.get("tool", "all")
    await _send_report(message, lambda t: phone_tool(t, tool), message.text, tool, "phone", state)


# --------------------------------------------------------------------------
# Никнейм
# --------------------------------------------------------------------------

async def username_tool(target: str, tool: str) -> str:
    username = normalize_username(target)
    specs: list[tuple[str, object, tuple, str]] = []
    if tool in ("all", "maigret"):
        specs.append(("maigret", maigret_service.run_maigret, (username,), "Maigret"))
    if tool in ("all", "sherlock"):
        specs.append(("sherlock", username_service.run_sherlock, (username,), "Sherlock"))
    if tool in ("all", "ss"):
        specs.append(("ss", username_service.run_socialscan, (f"@{username}",), "socialscan"))
    if tool == "snscrape":
        # snscrape устарел и не работает на Python 3.12 — включаем только по явному
        # выбору движка, чтобы не ронять автопробив трейсбеками.
        specs.append(("snscrape", username_service.run_snscrape, (username,), "snscrape"))
    if tool in ("all", "tg"):
        specs.append(("tg", username_service.telegram_user_lookup, (username,), "Telegram"))
    if tool in ("all", "pub"):
        specs.append(("pub", public_api_service.check_public_profiles, (username,), "публичные API"))
    if tool == "tw":
        # twscrape требует аккаунт Twitter — подключаем только по явному выбору
        specs.append(("tw", twscrape_service.run_twscrape, (username,), "Twitter/X"))

    out = await _safe_many(specs)
    notes: list[str] = []

    sherlock_lines = social_dict = snscrape_out = tg_dict = maigret_dict = pub_list = tw_dict = None
    if "maigret" in out:
        raw, note = out["maigret"]
        if note:
            notes.append(note)
        else:
            maigret_dict = maigret_service.parse_maigret(raw)
    if "sherlock" in out:
        res, note = out["sherlock"]
        if note:
            notes.append(note)
        else:
            sherlock_lines = res
    if "ss" in out:
        raw, note = out["ss"]
        if note:
            notes.append(note)
        else:
            social_dict = username_service.parse_socialscan(raw)
    if "snscrape" in out:
        raw, note = out["snscrape"]
        if note:
            notes.append(note)
        else:
            snscrape_out = raw
    if "tg" in out:
        res, note = out["tg"]
        if note:
            notes.append(note)
        else:
            tg_dict = res
    if "pub" in out:
        res, note = out["pub"]
        if note:
            notes.append(note)
        else:
            pub_list = res
    if "tw" in out:
        raw, note = out["tw"]
        if note:
            notes.append(note)
        else:
            tw_dict = raw

    text = username_service.format_username_report(
        username,
        sherlock=sherlock_lines,
        social=social_dict,
        snscrape_out=snscrape_out,
        telegram=tg_dict,
        maigret=maigret_dict,
        public=pub_list,
        tw=tw_dict,
    )
    return _join_notes(text, notes)


@router.message(IsAdmin(), F.text, ProbivStates.USERNAME)
async def username_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tool = data.get("tool", "all")
    await _send_report(message, lambda t: username_tool(t, tool), message.text, tool, "username", state)


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------

async def email_tool(target: str, tool: str) -> str:
    email = normalize_email(target)
    specs: list[tuple[str, object, tuple, str]] = []
    if tool in ("all", "reg"):
        specs.append(("reg", registration_service.check_registrations, (email, "email"), "регистрации"))
    if tool in ("all", "holehe"):
        specs.append(("holehe", email_service.run_holehe, (email,), "holehe"))
    if tool in ("all", "h8mail"):
        specs.append(("h8mail", email_service.run_h8mail, (email,), "h8mail"))
    if tool in ("all", "ss"):
        specs.append(("ss", username_service.run_socialscan, (email,), "socialscan"))
    if tool in ("all", "ghunt"):
        specs.append(("ghunt", email_service.run_ghunt, (email,), "GHunt"))

    out = await _safe_many(specs)
    notes: list[str] = []

    holehe_dict = h8mail_lines = social_dict = ghunt_dict = registrations = None
    if "reg" in out:
        res, note = out["reg"]
        if note:
            notes.append(note)
        elif res:
            registrations = res
    if "holehe" in out:
        raw, note = out["holehe"]
        if note:
            notes.append(note)
        else:
            holehe_dict = email_service.parse_holehe(raw, email)
    if "h8mail" in out:
        raw, note = out["h8mail"]
        if note:
            notes.append(note)
        else:
            h8mail_lines = email_service.parse_h8mail(raw, email)
    if "ss" in out:
        raw, note = out["ss"]
        if note:
            notes.append(note)
        else:
            social_dict = username_service.parse_socialscan(raw)
    if "ghunt" in out:
        raw, note = out["ghunt"]
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
        registrations=registrations,
        attempted=[key for key, _, _, _ in specs],
    )
    return _join_notes(text, notes)


@router.message(IsAdmin(), F.text, ProbivStates.EMAIL)
async def email_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tool = data.get("tool", "all")
    await _send_report(message, lambda t: email_tool(t, tool), message.text, tool, "email", state)


# --------------------------------------------------------------------------
# Повторный поиск по кнопке (без повторного ввода цели)
# --------------------------------------------------------------------------

@router.callback_query(IsAdmin(), F.data.startswith("retool:"))
async def on_retool_callback(call: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Повторить» / «Искать аккаунт в ТГ» — ищет по сохранённой цели."""
    try:
        _, category, tool = call.data.split(":", 2)
    except ValueError:
        await call.answer("Неверная кнопка", show_alert=True)
        return

    data = await state.get_data()
    target = data.get("last_target")
    if not target:
        await call.answer("Сначала сделайте поиск — потом нажимайте кнопки", show_alert=True)
        return

    builders = {
        "phone": phone_tool,
        "username": username_tool,
        "email": email_tool,
    }
    builder = builders.get(category)
    if builder is None:
        await call.answer("Для этой категории повтор недоступен", show_alert=True)
        return

    await state.set_state(_STATE_BY_CATEGORY.get(category, ProbivStates.MENU))
    await state.update_data(tool=tool)
    await _send_report(call.message, lambda t: builder(t, tool), target, tool, category, state)
    try:
        await call.answer()
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------
# Постраничная навигация по отчёту (кнопки «Назад / Вперёд»)
# --------------------------------------------------------------------------

@router.callback_query(IsAdmin(), F.data.startswith("pg:"))
async def on_pg_callback(call: CallbackQuery) -> None:
    """Переключает страницу отчёта в том же сообщении."""
    try:
        _, key, idx_s = call.data.split(":")
        idx = int(idx_s)
    except (ValueError, AttributeError):
        await call.answer("Неверная кнопка", show_alert=True)
        return

    entry = _PAGER.get(key)
    if not entry:
        await call.answer("Отчёт устарел — сделайте поиск заново", show_alert=True)
        return

    pages = entry["pages"]
    if idx < 0 or idx >= len(pages):
        await call.answer()
        return

    kb = _pager_keyboard(key, idx, len(pages), entry["category"], entry["tool"])
    try:
        await call.message.edit_text(pages[idx], reply_markup=kb)
    except Exception:  # noqa: BLE001 — текст страницы совпал с текущим
        pass
    await call.answer()