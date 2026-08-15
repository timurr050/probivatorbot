"""
Проверка регистрации email/телефона/ника в популярных сервисах.

Метод — «форма регистрации / восстановления пароля»: сервис отвечает по-разному
для уже занятого и свободного значения. Запросы идут через `curl_cffi`,
который подделывает TLS-отпечаток (JA3/JA4) Chrome — это обходит базовые
антибот-экраны (Cloudflare и аналоги), но БЕЗ авторизации и API-ключей.

Честность результата:
  * ✅ найден     — сервис подтвердил, что аккаунт существует;
  * ❌ не найден  — сервис ответил, что значения нет;
  * ⚠️ не удалось — сайт заблокировал/изменил форму — не выдаём за факт.

Какие сервисы проверять — настраивается через `REG_SERVICES` в `.env`
(через запятую: instagram, tiktok, vk, whatsapp, telegram, github; пусто = все).
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import re

from bot.config import SETTINGS
from bot.exceptions import ToolNotConfigured
from bot.utils.formatting import esc

_SESSION_KW = {"impersonate": "chrome", "timeout": 20, "allow_redirects": False}

# Похожий на реальный браузер (нужен формам регистрации)
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_ALL_SERVICES = ("instagram", "tiktok", "vk", "whatsapp", "telegram", "github")


def _curl_available() -> bool:
    try:
        return importlib.util.find_spec("curl_cffi") is not None
    except (ImportError, ValueError):
        return False


async def _get(session, url: str, headers: dict | None = None):
    resp = await session.get(url, headers=headers or {}, **_SESSION_KW)
    return resp.status_code, resp.text or ""


async def _post(session, url: str, data=None, json=None, headers=None):
    resp = await session.post(
        url, data=data, json=json, headers=headers or {}, **_SESSION_KW
    )
    return resp.status_code, resp.text or ""


def _cookie(session, name: str, default: str = "") -> str:
    """Читает cookie из сессии (у фейковых сессий в тестах cookies нет)."""
    try:
        jar = session.cookies
        value = jar.get(name, default)
        return str(value or default)
    except Exception:  # noqa: BLE001
        return default


def _cc_and_national(digits: str) -> tuple[str, str]:
    """Разбивает международный номер на код страны и местный номер."""
    try:
        import phonenumbers

        num = phonenumbers.parse("+" + digits, None)
        return str(num.country_code), str(num.national_number)
    except Exception:  # noqa: BLE001
        return "", digits


# ----------------------------------------------------------------------------
# Пробники: каждый принимает (session, target) и возвращает True/False/None.
# True — аккаунт существует, False — нет, None — не удалось достоверно понять.
# ----------------------------------------------------------------------------

def probe_github_email(email: str):
    """GitHub: POST /signup_check/email — JSON-ответ различает занят/свободен."""
    async def check(session, target):
        status, body = await _post(
            session,
            "https://github.com/signup_check/email",
            json={"value": target, "authenticity_token": ""},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if status not in (200, 422):  # GitHub отдаёт и 200, и 422 с полезным JSON
            return None
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        msg = str(data.get("message") or "").lower()
        if data.get("status") == "ok" and "already" not in msg and "taken" not in msg:
            return False
        if data.get("status") == "fail" or "already" in msg or "taken" in msg or "account" in msg:
            return True
        return None
    return check


def probe_instagram_email(email: str):
    """Instagram: форма регистрации — «email уже используется» при существующем."""
    async def check(session, target):
        # сначала берём cookies (csrftoken) с формы регистрации
        await _get(session, "https://www.instagram.com/accounts/emailsignup/")
        csrf = _cookie(session, "csrftoken")
        headers = {
            "User-Agent": _UA, "X-Instagram-AJAX": "1", "X-CSRFToken": csrf,
            "Origin": "https://www.instagram.com",
            "Referer": "https://www.instagram.com/accounts/emailsignup/",
        }
        status, body = await _post(
            session,
            "https://i.instagram.com/api/v1/web/accounts/web_create_ajax/attempt/",
            data={"email": target, "username": "u" + re.sub(r"[^a-z0-9]", "", email[:12]) or "uuser"},
            headers=headers,
        )
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, dict):
            errs = data.get("errors") or {}
            joined = " ".join(str(v) for v in errs.values() if v).lower()
            if "already" in joined or "another account" in joined or "используется" in joined:
                return True
            if data.get("status") == "ok" or not errs:
                return False
        low = body.lower()
        if "already" in low or "another account" in low or "занят" in low or "used" in low:
            return True
        return None
    return check


def probe_instagram_phone(phone_digits: str):
    async def check(session, target):
        await _get(session, "https://www.instagram.com/accounts/emailsignup/")
        csrf = _cookie(session, "csrftoken")
        headers = {
            "User-Agent": _UA, "X-Instagram-AJAX": "1", "X-CSRFToken": csrf,
            "Origin": "https://www.instagram.com",
            "Referer": "https://www.instagram.com/accounts/emailsignup/",
        }
        status, body = await _post(
            session,
            "https://i.instagram.com/api/v1/web/accounts/web_create_ajax/attempt/",
            data={"phone_number": target},
            headers=headers,
        )
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, dict):
            errs = data.get("errors") or {}
            joined = " ".join(str(v) for v in errs.values() if v).lower()
            if "already" in joined or "another account" in joined or "используется" in joined:
                return True
            if data.get("status") == "ok" or not errs:
                return False
        low = body.lower()
        if "already" in low or "another account" in low or "занят" in low or "used" in low:
            return True
        return None
    return check


def probe_tiktok_email(email: str):
    """TikTok: регистрация по email — код 2032/2033 при существующем аккаунте."""
    async def check(session, target):
        await _get(session, "https://www.tiktok.com/")  # s_v_web_id / антибот-cookies
        headers = {
            "User-Agent": _UA, "Content-Type": "application/json",
            "Referer": "https://www.tiktok.com/", "Origin": "https://www.tiktok.com",
        }
        status, body = await _post(
            session,
            "https://www.tiktok.com/api/v1/auth/register/email/check/",
            json={"email": target, "nickname": "user", "password": "Password123!"},
            headers=headers,
        )
        low = body.lower()
        if "already" in low or "exist" in low or "registered" in low:
            return True
        code = ""
        try:
            data = json.loads(body)
            code = str(data.get("code") or data.get("status_code") or "")
        except (json.JSONDecodeError, TypeError):
            pass
        if "2032" in code or "2033" in code:  # email/phone занят
            return True
        if code == "0":
            return False
        return None
    return check


def probe_tiktok_phone(phone_digits: str):
    async def check(session, target):
        await _get(session, "https://www.tiktok.com/")
        cc, _national = _cc_and_national(target)
        headers = {
            "User-Agent": _UA, "Content-Type": "application/json",
            "Referer": "https://www.tiktok.com/", "Origin": "https://www.tiktok.com",
        }
        status, body = await _post(
            session,
            "https://www.tiktok.com/api/v1/auth/register/phone/check/",
            json={"mobile": target, "country_code": cc or "7"},
            headers=headers,
        )
        low = body.lower()
        if "already" in low or "exist" in low or "registered" in low:
            return True
        code = ""
        try:
            data = json.loads(body)
            code = str(data.get("code") or data.get("status_code") or "")
        except (json.JSONDecodeError, TypeError):
            pass
        if "2032" in code or "2033" in code:
            return True
        if code == "0":
            return False
        return None
    return check


def probe_vk_email(email: str):
    """ВКонтакте: быстрая форма регистрации отвечает «занят» для существующего."""
    async def check(session, target):
        await _get(session, "https://m.vk.com/join?act=quick")
        status, body = await _post(
            session,
            "https://m.vk.com/join?act=quick",
            data={"email": target, "act": "quick"},
            headers={
                "User-Agent": _UA, "Origin": "https://m.vk.com",
                "Referer": "https://m.vk.com/join?act=quick",
            },
        )
        low = body.lower()
        if any(mark in low for mark in ("занят", "занято", "already", "used", "существует")):
            return True
        if any(mark in low for mark in ("свободен", "доступен", "вы успешно")):
            return False
        return None
    return check


def probe_vk_phone(phone_digits: str):
    async def check(session, target):
        await _get(session, "https://m.vk.com/join?act=quick")
        status, body = await _post(
            session,
            "https://m.vk.com/join?act=quick",
            data={"phone": target, "act": "quick"},
            headers={
                "User-Agent": _UA, "Origin": "https://m.vk.com",
                "Referer": "https://m.vk.com/join?act=quick",
            },
        )
        low = body.lower()
        if any(mark in low for mark in ("занят", "занято", "already", "used", "существует")):
            return True
        return None
    return check


def probe_whatsapp_phone(phone_digits: str):
    """WhatsApp: официальный endpoint v2/exist — status 'ok' = номер зарегистрирован."""
    async def check(session, target):
        cc, national = _cc_and_national(target)
        if not cc:
            return None
        url = (
            "https://v.whatsapp.net/v2/exist"
            f"?cc={cc}&in={national}&lc=en&lg=en&network_radio_type=1"
            "&sim_mcc=000&sim_mnc=000&method=sms&reason=default"
        )
        status, body = await _get(session, url, headers={"User-Agent": _UA})
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            return None
        st = str(data.get("status") or "").lower()
        if st == "ok":
            return True
        if st == "fail":
            return False
        return None
    return check


def probe_telegram_username(username: str):
    """Telegram: t.me/<ник> редиректит на t.me/s/... только если ник занят."""
    async def check(session, target):
        resp = await session.get(
            f"https://t.me/{target}", impersonate="chrome",
            timeout=15, allow_redirects=False,
        )
        status = resp.status_code
        location = ""
        try:
            location = str(resp.headers.get("location") or "").lower()
        except Exception:  # noqa: BLE001
            location = ""
        if status == 302:
            return True  # занятый ник редиректится на t.me/s/<ник>
        if status == 404:
            return False
        if status == 200:
            return True  # открытая страница ника — ник существует
        return None
    return check


# ----------------------------------------------------------------------------
# Реестр сервисов
# ----------------------------------------------------------------------------

_REGISTRY = [
    {"key": "instagram", "label": "Instagram", "emoji": "📸",
     "types": {"email": probe_instagram_email, "phone": probe_instagram_phone}},
    {"key": "tiktok", "label": "TikTok", "emoji": "🎵",
     "types": {"email": probe_tiktok_email, "phone": probe_tiktok_phone}},
    {"key": "vk", "label": "ВКонтакте", "emoji": "🔵",
     "types": {"email": probe_vk_email, "phone": probe_vk_phone}},
    {"key": "whatsapp", "label": "WhatsApp", "emoji": "💬",
     "types": {"phone": probe_whatsapp_phone}},
    {"key": "telegram", "label": "Telegram", "emoji": "✈️",
     "types": {"username": probe_telegram_username}},
    {"key": "github", "label": "GitHub", "emoji": "🐙",
     "types": {"email": probe_github_email}},
]


def _digits(value: str) -> str:
    return re.sub(r"[^\d]", "", value)


def _err_note(exc: Exception) -> str:
    """Короткая и понятная пометка в отчёт: таймаут/антибот/тип ошибки."""
    name = type(exc).__name__
    if "timeout" in name.lower() or "curl" in name.lower():
        return "таймаут — сайт не ответил"
    if name == "CurlError":
        return "сеть недоступна"
    return name


def _profile_url(service: dict, target: str, target_type: str) -> str:
    if target_type == "username":
        return {"telegram": f"https://t.me/{target}",
                "instagram": f"https://www.instagram.com/{target}/",
                "tiktok": f"https://www.tiktok.com/@{target}"}.get(service["key"], "")
    return ""


async def check_registrations(target: str, target_type: str) -> list[dict]:
    """Проверяет регистрацию target в популярных сервисах.

    target_type: 'email' | 'phone' | 'username'.
    Какие сервисы проверять — фильтруется через REG_SERVICES в .env.
    Возвращает список: [{key, label, emoji, found: bool|None, url, note}].
    """
    if not _curl_available():
        raise ToolNotConfigured(
            "curl_cffi не установлен:\n<code>pip install curl-cffi</code>\n"
            "Нужен для проверки аккаунтов в сервисах (обход Cloudflare)."
        )

    from curl_cffi import requests as crequests

    enabled = SETTINGS.reg_services or _ALL_SERVICES
    norm = target if target_type != "phone" else _digits(target)
    candidates = [
        s for s in _REGISTRY
        if target_type in s["types"] and s["key"] in enabled
    ]
    if not candidates:
        return []

    async def run_one(service: dict) -> dict | None:
        try:
            # фабрика пробника принимает цель и возвращает check(session, target)
            probe = service["types"][target_type](norm)
        except Exception as exc:  # noqa: BLE001
            return {
                "key": service["key"], "label": service["label"],
                "emoji": service["emoji"], "found": None,
                "note": _err_note(exc),
            }
        try:
            found = await probe(session_holder["session"], norm)
        except Exception as exc:  # noqa: BLE001
            return {
                "key": service["key"], "label": service["label"],
                "emoji": service["emoji"], "found": None,
                "note": _err_note(exc),
            }
        return {
            "key": service["key"], "label": service["label"],
            "emoji": service["emoji"],
            "found": bool(found) if found is not None else None,
            "url": _profile_url(service, norm, target_type),
            "note": "",
        }

    session_holder: dict = {}
    try:
        async with crequests.AsyncSession() as session:
            session_holder["session"] = session
            results = await asyncio.gather(
                *(run_one(s) for s in candidates)
            )
    except Exception as exc:  # noqa: BLE001 — сессия не поднялась
        return [{
            "key": s["key"], "label": s["label"], "emoji": s["emoji"],
            "found": None, "note": f"сессия: {type(exc).__name__}",
        } for s in candidates]

    return [r for r in results if r]


def format_registrations_section(results: list[dict]) -> list[str]:
    """Готовит секцию «🪪 Аккаунты в популярных сервисах» для отчёта."""
    if not results:
        return []
    found_n = sum(1 for r in results if r.get("found") is True)
    lines: list[str] = []
    add = lines.append
    add(f"<b>🪪 Аккаунты в популярных сервисах — найдено {found_n} из {len(results)}</b>")
    add("│ (проверка «занято/свободно» через публичные формы, без API-ключей)")
    for r in results:
        found = r.get("found")
        if found is True:
            mark = "✅ <b>аккаунт найден</b>"
        elif found is False:
            mark = "❌ аккаунт не найден"
        else:
            mark = "⚠️ не удалось проверить"
        line = f"│ {r.get('emoji', '')} {r.get('label', '')}: {mark}"
        note = r.get("note")
        if note:
            line += f" <i>({esc(note)})</i>"
        if r.get("url"):
            line += f" — <a href='{r['url']}'>профиль</a>"
        add(line)
    add("│ Instagram/TikTok/VK/WhatsApp защищены от ботов — "
        "результат может требовать повтора.")
    return lines
