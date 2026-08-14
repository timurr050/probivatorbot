"""
Сервис поиска по никнейму.

Двигатели:
  * sherlock    — поиск username на 400+ сайтах;
  * socialscan  — проверка доступности username на ключевых соцсетях;
  * snscrape    — сбор последних постов username в Twitter/X и Instagram;
  * Telethon    — поиск Telegram-аккаунта по username.
"""
from __future__ import annotations

import asyncio
import re

from bot.config import SETTINGS
from bot.exceptions import ServiceError, ToolNotConfigured
from bot.services.base import ensure_binary, run_cli, session_path

RESULT_LINK_HINT = "llll: лдн"

_SHERLOCK_SUMMARY_RE = re.compile(
    r"(\d+)\s+result[s]?\s+found|Found\s+(\d+)", re.IGNORECASE
)


def run_sherlock(username: str) -> list[str]:
    """Запускает sherlock в режиме CLI, возвращает список найденных сервисов."""
    try:
        binary = ensure_binary(None, "sherlock")
    except ToolNotConfigured:
        raise ToolNotConfigured(
            "sherlock не установлен.\n<code>pip install sherlock-project</code>\n"
            "ВНИМАНИЕ: из-за блокировок соцсетей результат может быть неполным."
        )

    args = [str(binary), "--print-found", "--timeout", "12", username]
    if SETTINGS.sherlock_officially_verified:
        args.append("--officially-verified")

    raw = run_cli(args)
    lines = [ln.strip("░=: ") for ln in raw.splitlines() if ln.strip()]
    # оставляем только те строки, что содержат ссылки вида https://
    found: list[str] = []
    for ln in lines:
        if "https://" in ln:
            found.append(ln.strip())
    return found


async def run_socialscan(target: str) -> str:
    """Проверяет доступность email/username на соцсетях через библиотеку socialscan.

    Возвращает текст вида «Platform: Status» для parse_socialscan.
    """
    from socialscan.platforms import Platforms
    from socialscan.util import execute_queries

    wanted = ["github", "gitlab", "instagram", "pinterest", "reddit",
              "twitter", "tumblr", "firefox"]  # доступные платформы socialscan 2.x
    platforms = [Platforms[p.upper()] for p in wanted]

    try:
        results = await execute_queries([target], platforms=platforms)
    except Exception as exc:  # noqa: BLE001
        raise ToolNotConfigured(f"socialscan: {type(exc).__name__}: {str(exc)[:120]}") from exc

    lines: list[str] = []
    for res in results:
        if res is None:
            continue
        name = res.platform.value.__name__
        if not res.success:
            status = "Error"
        elif not res.valid:
            status = "Invalid"
        elif res.available:
            status = "Available"
        else:
            status = "Taken/Reserved"
        lines.append(f"{name}: {status}")
    return "\n".join(lines)


_KNOWN_PLATFORMS = {
    "instagram", "twitter", "github", "reddit", "telegram", "youtube",
    "gitlab", "snapchat", "discord", "pinterest", "tiktok", "facebook",
    "linkedin", "spotify", "twitch", "vk", "mastodon", "steam",
    "tumblr", "firefox", "lastfm", "yahoo", "mailru",
}


def parse_socialscan(raw: str) -> dict[str, str]:
    """Парсит вывод socialscan вида «Platform: Available | Taken/Reserved | ...».

    Результат: {платформа: Найден|Свободен|Ошибка}.
    """
    result: dict[str, str] = {}

    def map_status(status: str) -> str:
        s = status.lower()
        if s == "available":
            return "Свободен"
        if "taken" in s or "reserved" in s or "exists" in s or "found" in s:
            return "Найден"
        if s == "invalid":
            return "Невалиден"
        if "error" in s or "timeout" in s or s in {"unknown", "na"}:
            return "Ошибка"
        return status

    for line in raw.splitlines():
        line = line.strip()
        if ": " not in line:
            continue
        platform, _, status = line.partition(": ")
        platform = platform.strip().lower().rstrip(":")
        # отсекаем мусорные строки (заголовки, прогресс)
        if platform not in _KNOWN_PLATFORMS:
            continue
        if not status:
            continue
        result[platform] = map_status(status.strip())
    return result


# ----------------------------------------------------------------------------
# snscrape
# ----------------------------------------------------------------------------

async def run_snscrape(username: str) -> str:
    """Собирает посты username в Twitter/X и Instagram через snscrape."""
    try:
        binary = ensure_binary(None, "snscrape")
    except ToolNotConfigured:
        raise ToolNotConfigured(
            "snscrape не установлен:\n<code>pip install snscrape</code>"
        )

    chunks: list[str] = []
    for platform, q in (("Twitter/X", f"twitter-user {username}"), ("Instagram", f"instagram-user {username}")):
        args = [str(binary), *q.split()]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            raw, _ = await asyncio.wait_for(proc.communicate(), timeout=SETTINGS.cli_timeout)
            text = raw.decode(SETTINGS.cli_encoding, errors="replace")
        except asyncio.TimeoutError:
            text = ""
        posts = [l for l in text.splitlines() if l.strip()]
        if posts:
            chunks.append(f"<b>{platform}</b>|" + "|".join(posts[:8]))
    return "\n".join(chunks)


# ----------------------------------------------------------------------------
# Telegram-аккаунт
# ----------------------------------------------------------------------------

async def telegram_user_lookup(username: str) -> dict:
    """Ищет Telegram-аккаунт по username через Telethon."""
    if not SETTINGS.is_telethon_ready:
        raise ToolNotConfigured(
            "Telethon не настроен.\nДобавьте в .env TG_API_ID и TG_API_HASH (https://my.telegram.org/apps)"
        )
    from telethon import TelegramClient

    accounts = SETTINGS.tg_accounts
    if not accounts:
        raise ToolNotConfigured(
            "Не заданы Telegram-аккаунты (<code>TG_ACCOUNTS</code> в .env).\n"
            'Пример: {"+375291234567": "sess_1"}'
        )

    phone = next(iter(accounts), None)
    session = accounts[phone] if phone else "anon"
    client = TelegramClient(
        session_path(session),
        api_id=SETTINGS.tg_api_id,
        api_hash=SETTINGS.tg_api_hash,
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"found": None, "hint": "Сессия не авторизована"}
        try:
            entity = await client.get_entity(username)
        except ValueError:
            return {"found": False}
        except Exception as exc:  # noqa: BLE001
            return {"found": None, "hint": f"Ошибка: {exc}"}
        return {
            "found": True,
            "id": getattr(entity, "id", None),
            "username": getattr(entity, "username", None),
            "first_name": getattr(entity, "first_name", None),
            "last_name": getattr(entity, "last_name", None),
            "bot": bool(getattr(entity, "bot", False)),
            "premium": bool(getattr(entity, "premium", False)),
            "verified": bool(getattr(entity, "verified", False)),
            "fake": bool(getattr(entity, "fake", False)),
            "scam": bool(getattr(entity, "scam", False)),
            "phone": getattr(entity, "phone", None),
            "type": type(entity).__name__,
        }
    finally:
        await client.disconnect()


def format_username_report(username: str, sherlock: list[str] | None = None,
                           social: dict | None = None,
                           snscrape_out: str | None = None,
                           telegram: dict | None = None) -> str:
    """Собирает итоговый отчёт по никнейму."""
    lines: list[str] = []
    add = lines.append
    add(f"<b>🧑‍💻 ОТЧЁТ ПО НИКНЕЙМУ</b>")
    add(f"└ <code>@{str(username)}</code>")
    add("")

    if telegram:
        add("<b>✈️ Telegram</b>")
        if telegram.get("found") is True:
            add(f"│ ID: <code>{str(telegram.get('id'))}</code>")
            add(f"│ Username: <code>@{str(telegram.get('username', ''))}</code>")
            name = " ".join(
                str(telegram.get(k) or "").strip()
                for k in ("first_name", "last_name")
                if telegram.get(k)
            )
            add(f"│ Имя: <blockquote>{name or '—'}</blockquote>")
            add(f"│ Тип: <code>{str(telegram.get('type', 'User').replace('User', 'Пользователь').replace('Channel', 'Канал').replace('Chat', 'Группа'))}</code>")
            add(f"│ Бот: <code>{'да' if telegram.get('bot') else 'нет'}</code>")
            add(f"│ Premium: <code>{'да' if telegram.get('premium') else 'нет'}</code>")
            add(f"│ Verified/Scam/Fake: <code>{telegram.get('verified')}/{telegram.get('scam')}/{telegram.get('fake')}</code>")
            add(f"│ Телефон (если виден): <code>{str(telegram.get('phone') or '—')}</code>")
        elif telegram.get("found") is False:
            add(f"│ Статус: <b>не найден</b>")
        else:
            add(f"│ {str(telegram.get('hint', ''))}")
        add("")

    if social:
        add("<b>🕸 socialscan</b>")
        for site, status in social.items():
            mark = "⭕" if status == "Найден" else "✖️"
            add(f"│ {str(site)}: {mark} {str(status)}")
        add("")

    if sherlock:
        add(f"<b>🕵️ Sherlock — найдено на {len(sherlock)} сервисах</b>")
        for line in sherlock[:30]:
            add(f"│ {str(line)}")
        if len(sherlock) > 30:
            add(f"│ … и ещё {len(sherlock) - 30}")
        add("")

    if snscrape_out:
        add("<b>📰 snscrape (свежие посты)</b>")
        for chunk in snscrape_out.split("|"):
            if chunk.strip():
                add(f"│ {str(chunk)[:512]}")
        add("")

    add("⚡ Данные из открытых источников. Используйте только в законных целях.")
    return "\n".join(lines)