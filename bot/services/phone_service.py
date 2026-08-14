"""
Сервис анализа телефонного номера.

Двигатели:
  * phonenumbers   — валидация и расшифровка номера (тип, регион, оператор, таймзона);
  * PhoneInfoga    — CLI-бинарник (сканирование);
  * Telethon       — проверка регистрации номера в Telegram (аналог telegram-phone-number-checker);
  * ignorant       — поиск номера по соцсетям.
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

import phonenumbers
from phonenumbers import carrier, geocoder, timezone

from bot.config import SETTINGS
from bot.exceptions import ServiceError, ToolNotConfigured
from bot.services.base import avatar_path, ensure_binary, run_cli, session_path

# удаляем спецсимволы для CLI-инструментов, оставив цифровой формат
_DIGITS_RE = re.compile(r"[^\d]")


def _digits(e164: str) -> str:
    return _DIGITS_RE.sub("", e164)


# ----------------------------------------------------------------------------
# phonenumbers
# ----------------------------------------------------------------------------

_NUMBER_TYPES = {
    phonenumbers.PhoneNumberType.FIXED_LINE: "Фиксированная линия",
    phonenumbers.PhoneNumberType.MOBILE: "Мобильный",
    phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "Городской/Мобильный",
    phonenumbers.PhoneNumberType.TOLL_FREE: "Бесплатный (800)",
    phonenumbers.PhoneNumberType.PREMIUM_RATE: "Платный (Premium)",
    phonenumbers.PhoneNumberType.SHARED_COST: "Shared cost",
    phonenumbers.PhoneNumberType.VOIP: "VoIP",
    phonenumbers.PhoneNumberType.PERSONAL_NUMBER: "Личный",
    phonenumbers.PhoneNumberType.PAGER: "Пейджер",
    phonenumbers.PhoneNumberType.UAN: "UAN",
    phonenumbers.PhoneNumberType.VOICEMAIL: "Голосовая почта",
    phonenumbers.PhoneNumberType.UNKNOWN: "Неизвестный",
}


def phonenumbers_info(e164: str) -> dict:
    """Расшифровка номера через libphonenumber."""
    number = phonenumbers.parse(e164, None)
    region_code = phonenumbers.region_code_for_number(number)
    num_type = phonenumbers.number_type(number)
    info = {
        "e164": e164,
        "country_code": f"+{number.country_code}",
        "national": phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL),
        "international": phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
        "region": region_code or "UN001",
        "region_name": phonenumbers.region_name_for_number_raw if hasattr(phonenumbers, "region_name_for_number_raw") else region_code,
        "type": _NUMBER_TYPES.get(num_type, "Неизвестный"),
        "carrier": "",
        "geo": "",
        "timezones": [],
        "valid": phonenumbers.is_valid_number(number),
        "possible": phonenumbers.is_possible_number(number),
    }

    if info["valid"]:
        try:
            info["carrier"] = carrier.name_for_number(number, "ru")
        except Exception:  # noqa: BLE001
            info["carrier"] = ""
        try:
            info["geo"] = geocoder.description_for_number(number, "ru")
        except Exception:  # noqa: BLE001
            info["geo"] = ""
        try:
            info["timezones"] = list(timezone.time_zones_for_number(number))
        except Exception:  # noqa: BLE001
            info["timezones"] = []
    return info


# ----------------------------------------------------------------------------
# PhoneInfoga
# ----------------------------------------------------------------------------

def _phoneinfoga_command() -> tuple[str, ...]:
    binary = ensure_binary(SETTINGS.phoneinfoga_path, "phoneinfoga")
    return tuple(str(binary).split())


def run_phoneinfoga(e164: str) -> str:
    """Запускает PhoneInfoga и возвращает сырой отчёт."""
    base = _phoneinfoga_command()
    args = list(base) + ["scan", "-n", e164]
    if SETTINGS.phoneinfoga_api_key:
        args = [*base, "--api-key", SETTINGS.phoneinfoga_api_key,
                "--name", "other", "scan", "-n", e164]
    try:
        return run_cli(args)
    except ServiceError:
        # падаем на legacy-режим для старых версий PhoneInfoga
        try:
            return run_cli([*base, "number", e164])
        except ServiceError:
            raise


def summarize_phoneinfoga(raw: str, e164: str) -> list[str]:
    """Вытаскивает пригодные для показа строчки из вывода PhoneInfoga."""
    out = _fragment_lines(raw)
    if not out:
        return []
    return out[:60]


def _fragment_lines(raw: str) -> list[str]:
    lines: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith(("[", "We are", "Started", "Running")):
            continue
        lines.append(line)
    # обрезаем повторяющийся прогресс
    seen: set[str] = set()
    unique: list[str] = []
    for line in lines:
        norm = re.sub(r"\s+", " ", line)[:80]
        if norm not in seen:
            seen.add(norm)
            unique.append(line)
    return unique


# ----------------------------------------------------------------------------
# Telegram-проверка номера (Telethon) — аналог telegram-phone-number-checker
# ----------------------------------------------------------------------------

async def check_telegram(e164: str) -> dict:
    """Проверяет, зарегистрирован ли номер в Telegram.

    Возвращает {'registered': bool, 'username': str|None, 'first_name': str|None, 'last_name': str|None, 'bot': bool, 'photo': str|None}
    """
    if not SETTINGS.is_telethon_ready:
        raise ToolNotConfigured(
            "Telethon не настроен.\nДобавьте в .env:\n"
            "<code>TG_API_ID</code> и <code>TG_API_HASH</code> (https://my.telegram.org/apps)\n"
            "и пару <code>phone</code>:<code>session_file</code> в <code>TG_ACCOUNTS</code>"
        )

    from telethon import TelegramClient
    from telethon.errors import UsernameNotOccupiedError  # noqa: F401

    accounts = SETTINGS.tg_accounts
    if not accounts:
        raise ToolNotConfigured(
            "Не заданы Telegram-аккаунты (<code>TG_ACCOUNTS</code> в .env).\n"
            'Пример: {"+375291234567": "sess_1"}'
        )

    phone = next(iter(accounts), None)
    session_name = accounts[phone] if phone else "anon"

    client = TelegramClient(
        session_path(session_name),
        api_id=SETTINGS.tg_api_id,
        api_hash=SETTINGS.tg_api_hash,
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"registered": None, "hint": "Сессия не авторизована (нужен вход по коду)"}

        me = await client.get_me()
        try:
            entity = await client.get_input_entity(e164)
        except (ValueError, TypeError):
            return {"registered": False}
        except Exception as exc:  # noqa: BLE001
            return {"registered": None, "hint": f"Ошибка при запросе: {exc}"}

        # нормализуем entity в полноценного юзера
        try:
            user = await client.get_entity(entity)
        except Exception:  # noqa: BLE001
            user = entity

        result = {
            "registered": True,
            "username": getattr(user, "username", None),
            "first_name": getattr(user, "first_name", None),
            "last_name": getattr(user, "last_name", None),
            "bot": bool(getattr(user, "bot", False)),
            "premium": bool(getattr(user, "premium", False)),
            "verified": bool(getattr(user, "verified", False)),
            "fake": bool(getattr(user, "fake", False)),
            "scam": bool(getattr(user, "scam", False)),
            "phone": getattr(user, "phone", None),
            "restricted": bool(getattr(user, "restricted", False)),
        }
        # подтягиваем фото для аватара, если оно есть
        result["photo"] = await _maybe_avatar_photo(client, user)
        return result
    finally:
        await client.disconnect()


async def _maybe_avatar_photo(client, user) -> Optional[str]:
    try:
        photos = await client.get_profile_photos(user)
        if not photos:
            return None
        return await client.download_media(photos[0], file=avatar_path())
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------------------
# ignorant — поиск номера по соцсетям
# ----------------------------------------------------------------------------

async def run_ignorant(e164: str) -> str:
    """Ищет номер в соцсетях через CLI ignorant."""
    args = "ignorant"
    try:
        binary = ensure_binary(None, args)
        proc = await asyncio.create_subprocess_exec(
            str(binary),
            "--phone",
            _digits(e164),
            "--only-used",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=SETTINGS.cli_timeout)
        text = raw.decode(SETTINGS.cli_encoding, errors="replace")
        status = await proc.wait()
        if status != 0 and not text.strip():
            return ""
        return text
    except asyncio.TimeoutError:
        return ""
    except (FileNotFoundError, ToolNotConfigured):
        raise ToolNotConfigured(
            "ignorant не установлен.\n<code>pip install ignorant</code>"
        )


def parse_ignorant(raw: str, e164: str) -> dict:
    """Превращает вывод ignorant в словарь {сайт: 'Found'|'Not found'|'Error'}."""
    result: dict[str, str] = {}
    for line in raw.splitlines():
        if "->" not in line:
            continue
        site, _, status = line.partition("->")
        site = site.strip(" ░.:=\t ")
        status = status.strip().split(".")[0]
        if site:
            result[site] = status
    return result


# ----------------------------------------------------------------------------
# Сборка полного отчёта
# ----------------------------------------------------------------------------

def format_phone_report(e164: str, info: dict, telegram: dict | None = None,
                        phoneinfoga: list[str] | None = None,
                        ignorant: dict | None = None) -> str:
    """Собирает итоговый текстовый отчёт по номеру."""
    lines: list[str] = []
    add = lines.append
    add("<b>📱 ОТЧЁТ ПО НОМЕРУ</b>\n")
    add(f"└ <code>{str(e164)}</code>")
    add("")

    add("<b>▫ Разбор номера</b>")
    add(f"│ Страна: <code>{str(info.get('region_name') or info.get('region'))}</code> (<code>{str(info.get('country_code'))}</code>)")
    add(f"│ Код страны: <code>{str(info.get('country_code'))}</code>")
    add(f"│ Национальный: <code>{str(info.get('national'))}</code>")
    add(f"│ Международный: <code>{str(info.get('international'))}</code>")
    add(f"│ Тип: <code>{str(info.get('type'))}</code>")
    add(f"│ Валидность: <code>{'Да' if info.get('valid') else 'Нет'}</code>")
    add(f"│ Возможен: <code>{'Да' if info.get('possible') else 'Нет'}</code>")
    if info.get("carrier"):
        add(f"│ Оператор: <code>{str(info['carrier'])}</code>")
    if info.get("geo"):
        add(f"│ Гео-регион: <code>{str(info['geo'])}</code>")
    if info.get("timezones"):
        add(f"│ Часовые пояса: <code>{', '.join(str(t) for t in info['timezones'][:3])}</code>")
    add("")

    if phoneinfoga:
        add("<b>🔍 PhoneInfoga</b>")
        for line in phoneinfoga:
            add(f"│ {str(line)}")
        add("")

    if telegram:
        add("<b>✈️ Telegram</b>")
        if telegram.get("registered") is True:
            add(f"│ Статус: <b>НАЙДЕН ⭕</b>")
            add(f"│ Username: <code>@{str(telegram.get('username', ''))}</code>" if telegram.get("username") else "│ Username: —")
            add(f"│ Имя: <blockquote>{str(telegram.get('first_name') or '—')} {str(telegram.get('last_name') or '')}</blockquote>")
            add(f"│ Бот: <code>{'да' if telegram.get('bot') else 'нет'}</code>")
            add(f"│ Premium: <code>{'да' if telegram.get('premium') else 'нет'}</code>")
        elif telegram.get("registered") is False:
            add(f"│ Статус: <b>ИЗВЕСТЕН ✖️ (не в TG)</b>")
        else:
            add(f"│ {str(telegram.get('hint', 'нет данных'))}")
        add("")

    if ignorant:
        found = [k for k, v in ignorant.items() if v.lower() not in {"not found", "error", "errored"}]
        missing = [k for k, v in ignorant.items() if v.lower() in {"not found", "error", "errored"}]
        add("<b>🌐 ignorant (соцсети)</b>")
        add(f"│ Найдено: <code>{len(found)}</code> из <code>{len(ignorant)}</code>")
        if found:
            for k in found[:15]:
                add(f"│ <b>{str(k)}</b> → {str(ignorant[k])}")
        if missing:
            add(f"│ Не найдено: {', '.join(str(k) for k in missing[:10])}")
        add("")

    add("⚡ Данные из открытых источников. Используйте только в законных целях.")
    return "\n".join(lines)