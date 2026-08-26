"""
Сервис анализа телефонного номера.

Двигатели:
  * phonenumbers   — валидация и расшифровка номера (тип, регион, оператор, таймзона);
  * PhoneInfoga    — CLI-бинарник (сканирование);
  * Telethon       — проверка регистрации номера в Telegram (аналог telegram-phone-number-checker);
  * ignorant       — поиск номера по соцсетям.
"""
from __future__ import annotations

import re
from typing import Optional

import phonenumbers
from phonenumbers import carrier, geocoder, timezone

from bot.config import SETTINGS
from bot.exceptions import ExternalToolError, ServiceError, ToolNotConfigured, ToolTimeout
from bot.services.base import avatar_path, ensure_binary, run_cli_async, session_path

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
    phonenumbers.PhoneNumberType.SHARED_COST: "С раздельной оплатой",
    phonenumbers.PhoneNumberType.VOIP: "IP-телефония",
    phonenumbers.PhoneNumberType.PERSONAL_NUMBER: "Личный",
    phonenumbers.PhoneNumberType.PAGER: "Пейджер",
    phonenumbers.PhoneNumberType.UAN: "Универсальный (UAN)",
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


async def run_phoneinfoga(e164: str) -> str:
    """Запускает PhoneInfoga и возвращает сырой отчёт."""
    base = _phoneinfoga_command()
    args = list(base) + ["scan", "-n", e164]
    if SETTINGS.phoneinfoga_api_key:
        args = [*base, "--api-key", SETTINGS.phoneinfoga_api_key,
                "--name", "other", "scan", "-n", e164]
    try:
        return await run_cli_async(args)
    except ServiceError:
        # падаем на legacy-режим для старых версий PhoneInfoga
        try:
            return await run_cli_async([*base, "number", e164])
        except ServiceError:
            raise


_PINFOGA_SECTIONS = {
    "Social media": "👤 Соцсети",
    "Disposable providers": "📨 Одноразовые SMS-сервисы",
    "Reputation": "⭐ Репутация / отзывы",
    "Individuals": "🧑 Персональные данные",
    "General": "📄 Общий поиск",
}

_MAX_LINKS_PER_SECTION = 1000  # без обрезки: все ссылки показываем (пагинация в боте)


def _link_domain(url: str) -> str:
    """Вытаскивает короткое имя сайта из поискового URL PhoneInfoga."""
    m = re.search(
        r"site%3A([a-z0-9.-]+(?:\.(?:com|ru|net|org|me|io|info|de|ca|ie|us|uk|in|"
        r"online|live|now|co|top|xyz|plus|app|eu|nl|cz|pl|by|ua|kz|es|it|fr|[a-z]{2})))",
        url,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).removeprefix("www.")
    m2 = re.search(r"https?://([^/?#]+)", url)
    if m2:
        return m2.group(1).removeprefix("www.")
    return ""


def summarize_phoneinfoga(raw: str, e164: str) -> list[str]:
    """Разбирает вывод PhoneInfoga в чистые русские строки.

    Ссылки группируются по категориям (соцсети, одноразовые SMS, репутация,
    персональные данные, общий поиск), заголовки переводятся, дубликаты
    убираются, количество ссылок в каждой категории ограничено — вместо
    нечитабельной простыни на английском.
    """
    sections: dict[str, list[str]] = {}
    info: dict[str, str] = {}
    succeeded: str | None = None
    current: str | None = None

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("Results for"):
            current = None
            continue
        # заголовки категорий ("Social media:", "Disposable providers:"…)
        if (line.endswith(":") and len(line) < 45
                and not line.startswith(("URL", "http", "time="))):
            candidate = line[:-1].strip()
            if candidate in _PINFOGA_SECTIONS:
                current = candidate
                continue
        if current and (line.startswith("URL:") or line.startswith("http")):
            url = line[4:].strip() if line.startswith("URL:") else line
            if url.startswith("http"):
                bucket = sections.setdefault(current, [])
                if url not in bucket:
                    bucket.append(url)
            continue
        m = re.match(r"^([A-Za-z][\w .-]+):\s*(.+)$", line)
        if m and not line.startswith(("time=", "level=")):
            info[m.group(1).strip()] = m.group(2).strip()
            continue
        m = re.search(r"(\d+) scanner\(s\) succeeded", line)
        if m:
            succeeded = m.group(1)

    if not sections and not info:
        return []

    out: list[str] = []
    for section, urls in sections.items():
        label = _PINFOGA_SECTIONS.get(section, section)
        shown = urls[:_MAX_LINKS_PER_SECTION]
        links = []
        for url in shown:
            site = _link_domain(url)
            links.append(f'<a href="{url}">{site or "ссылка"} 🔍</a>')
        extra = f" (+ещё {len(urls) - len(shown)})" if len(urls) > len(shown) else ""
        out.append(f"{label} ({len(urls)}): " + " · ".join(links) + extra)

    if info.get("Country"):
        out.append(f"🌍 Страна: <code>{info['Country']}</code>")
    if info.get("Local") or info.get("Raw local"):
        out.append(f"📞 Местный формат: <code>{info.get('Local') or info.get('Raw local')}</code>")
    if info.get("Carrier"):
        out.append(f"🏢 Оператор: <code>{info['Carrier']}</code>")
    if info.get("E164"):
        out.append(f"📟 E164: <code>{info['E164']}</code>")
    if succeeded:
        out.append(f"✅ Сканеров выполнено: {succeeded}")

    return out


# ----------------------------------------------------------------------------
# Telegram-проверка номера (Telethon) — аналог telegram-phone-number-checker
# ----------------------------------------------------------------------------

async def check_telegram(e164: str) -> dict:
    """Проверяет, зарегистрирован ли номер в Telegram.

    Перебирает ВСЕ сессии из TG_ACCOUNTS по очереди — первая авторизованная,
    которая смогла ответить, и есть результат. Возвращает
    {'registered': bool, 'username': ..., 'photo': ...}.
    """
    from bot.services.telethon_lookup import for_each_session

    async def _lookup(client, phone):
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

    result, hints = await for_each_session(_lookup)
    if result:
        return result
    return {"registered": None, "hint": "; ".join(hints) or "нет сессий"}


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
    """Ищет номер в соцсетях через CLI ignorant.

    ignorant принимает positional-аргументы: <country code> <phone number>
    (пример: ``ignorant +375 291234567``). Флага ``--phone`` не существует,
    поэтому раскладываем E.164 на код страны и национальный номер через
    phonenumbers.
    """
    try:
        binary = ensure_binary(None, "ignorant")
    except ToolNotConfigured:
        raise ToolNotConfigured(
            "ignorant не установлен.\n<code>pip install ignorant</code>"
        )
    try:
        number = phonenumbers.parse(e164, None)
        cc = f"+{number.country_code}"
        nn = str(number.national_number)
    except Exception:  # noqa: BLE001 — невалидный номер, искать негде
        return ""
    try:
        return await run_cli_async(
            [str(binary), cc, nn, "--only-used"],
            timeout=SETTINGS.cli_timeout,
        )
    except (ToolTimeout, ExternalToolError, ServiceError):
        return ""


_IGNORANT_RE = re.compile(r"^\[([+\-x])\]\s*(\S+)")


def parse_ignorant(raw: str, e164: str) -> dict:
    """Превращает вывод ignorant в словарь {сайт: 'Found'|'Not found'|'Error'}.

    Поддерживаются оба формата вывода:
      * реальный ignorant: ``[+] site.com`` / ``[-] site.com`` / ``[x] site.com``;
      * устаревший/тестовый: ``Site -> Text``.
    Легенда ``[+] Phone number used, [-] ...`` отсекается (домен должен
    содержать точку и не содержать пробелов/запятых).
    """
    result: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        m = _IGNORANT_RE.match(line)
        if m:
            mark, site = m.group(1), m.group(2).strip()
            if " " in site or "," in site or "." not in site:
                continue  # легенда/баннер, а не результат по сайту
            status = {"+": "Found", "-": "Not found", "x": "Error"}.get(mark, "Error")
            if site:
                result[site] = status
            continue
        if "->" in line:
            site, _, status = line.partition("->")
            site = site.strip(" ░.:=\t ")
            status = status.strip()
            if site:
                result[site] = status
    return result


# ----------------------------------------------------------------------------
# Сборка полного отчёта
# ----------------------------------------------------------------------------

def format_phone_report(e164: str, info: dict, telegram: dict | None = None,
                        phoneinfoga: list[str] | None = None,
                        ignorant: dict | None = None,
                        registrations: list[dict] | None = None) -> str:
    """Собирает итоговый текстовый отчёт по номеру."""
    from bot.services.registration_service import format_registrations_section

    lines: list[str] = []
    add = lines.append
    add("<b>📱 ОТЧЁТ ПО НОМЕРУ</b>\n")
    add(f"<blockquote>{str(e164)}</blockquote>")
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
            add(f"│ Ник: <code>@{str(telegram.get('username', ''))}</code>" if telegram.get("username") else "│ Ник: —")
            add(f"│ Имя: <blockquote>{str(telegram.get('first_name') or '—')} {str(telegram.get('last_name') or '')}</blockquote>")
            add(f"│ Бот: <code>{'да' if telegram.get('bot') else 'нет'}</code>")
            add(f"│ Premium: <code>{'да' if telegram.get('premium') else 'нет'}</code>")
        elif telegram.get("registered") is False:
            add(f"│ Статус: <b>не найден в Telegram</b>")
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
                site = str(k)
                if "." in site:
                    add(f"│ <a href='https://{site}'>{site}</a> → {str(ignorant[k])}")
                else:
                    add(f"│ <b>{site}</b> → {str(ignorant[k])}")
        if missing:
            add(f"│ Не найдено: {', '.join(str(k) for k in missing[:10])}")
        add("")

    if registrations:
        add("\n".join(format_registrations_section(registrations)))
        add("")

    add("⚡ Данные из открытых источников. Используйте только в законных целях.")
    return "\n".join(lines)