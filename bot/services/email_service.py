"""
Сервис поиска по email.

Двигатели:
  * holehe     — проверка регистрации email на 120+ сайтах;
  * h8mail     — поиск email в утечках (требует h8mail_config.ini / hunter.io ключ);
  * socialscan — проверка доступности email на ключевых сервисах;
  * GHunt      — разведка Google-аккаунта по email.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from bot.config import SETTINGS
from bot.exceptions import ToolNotConfigured
from bot.services.base import ensure_binary, run_cli_async
from bot.services.username_service import run_socialscan


# ----------------------------------------------------------------------------
# holehe
# ----------------------------------------------------------------------------

async def run_holehe(email: str) -> str:
    """Проверяет регистрацию email на сайтах через holehe."""
    try:
        binary = ensure_binary(None, "holehe")
    except ToolNotConfigured:
        raise ToolNotConfigured("holehe не установлен:\n<code>pip install holehe</code>")
    return await run_cli_async([str(binary), email, "--no-color", "--only-used"])


def parse_holehe(raw: str, email: str) -> dict[str, str]:
    """Превращает вывод holehe в {сайт: 'FOUND'|'NOT_FOUND'|'rate_limited'|'error'}."""
    mapping = {
        "+": "🇷🇺 FOUND",
        "x": "❌ NOT_FOUND",
        "-": "not_checked",
        "p": "rate_limited",
        "e": "error",
    }
    result: dict[str, str] = {}
    pattern = re.compile(r"^\s*\[([+\-xpe])\]\s*(.*?)\s*(?:\[[+\-xpe]\])?\s*$", re.IGNORECASE)
    for line in raw.splitlines():
        m = pattern.match(line)
        if not m:
            continue
        status_code = m.group(1).lower()
        site = m.group(2).strip()
        if not site or site.lower().startswith(("email used", "found account")) or len(site.split()) > 6:
            continue
        result[site] = mapping.get(status_code, status_code)
    return result


# ----------------------------------------------------------------------------
# h8mail
# ----------------------------------------------------------------------------

async def run_h8mail(email: str) -> str:
    """Ищет email в утечках через h8mail."""
    try:
        binary = ensure_binary(None, "h8mail")
    except ToolNotConfigured:
        raise ToolNotConfigured("h8mail не установлен:\n<code>pip install h8mail</code>")

    # -t <target> --loose: без ключей из .env работает по hunter.io (public API)
    return await run_cli_async([str(binary), "-t", email, "--loose"])


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def parse_h8mail(raw: str, email: str) -> list[str]:
    """Извлекает найденные строки из вывода h8mail (без баннера и ANSI-мусора)."""
    text = _ANSI_RE.sub("", raw)
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if "Results" in line and "for" in line:
            start = i
            break
    pool = lines[start + 1:] if start is not None else lines

    _BANNER_MARKS = (
        "h8mail", "use responsibly", "heartfelt email osint", "official h8mail",
        "posts:", "version 2", "up to date", "removing duplicates", "targets:",
        "target factory", "is down", "skipping", "github.com/khast3x",
        "targets started", "scylla",
    )

    result: list[str] = []
    for line in pool:
        line = line.strip()
        if not line:
            continue
        if line.startswith(("Saving", "Output", "Done", "Query", ">", "[i]", "[~]", "[!]", "[>]")):
            continue
        low = line.lower()
        if any(mark in low for mark in _BANNER_MARKS):
            continue
        # результаты вида «email:данные» (допускаем префикс [ + ])
        line = re.sub(r"^\[\+\]\s*", "", line)
        if email.lower() not in line.lower() and ":" not in line:
            continue
        if line not in result:
            result.append(line)
    return result[:40]


# ----------------------------------------------------------------------------
# GHunt
# ----------------------------------------------------------------------------

def _ghunt_creds_exist() -> bool:
    """Проверяет наличие авторизации GHunt (creds.data)."""
    cfg = SETTINGS.ghunt_config_path
    if cfg:
        p = Path(cfg)
        if p.is_dir():
            p = p / "creds.data"
        if p.exists():
            return True
    return (Path.home() / ".pyconfig" / "ghunt" / "creds.data").exists()


def _ghunt_env() -> dict:
    env = dict(os.environ)
    # ghunt печатает emoji-баннер через rich; в cp1251-консоли Windows это
    # роняет процесс, поэтому принудительно включаем UTF-8 на стороне потомка.
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("LC_ALL", None)
    env.pop("LANG", None)
    return env


async def run_ghunt(email: str) -> str:
    """Разведка Google-аккаунта через GHunt (требуется авторизация ghunt login)."""
    try:
        ensure_binary(None, "ghunt")
    except ToolNotConfigured:
        raise ToolNotConfigured("GHunt не установлен:\n<code>pip install ghunt</code>")

    if not _ghunt_creds_exist():
        raise ToolNotConfigured(
            "GHunt не авторизован в Google.\n"
            "Выполните один раз в консоли: <code>ghunt login</code> "
            "(https://github.com/mxrch/ghunt)"
        )

    # Запускаем модуль напрямую (минуя баннер, который падает на Windows),
    # через python -c в отдельном процессе с UTF-8 и закрытым stdin.
    code = (
        "import asyncio, sys\n"
        "from ghunt.modules import email\n"
        f"asyncio.run(email.hunt(None, {email!r}, None))\n"
    )
    return await run_cli_async(
        [sys.executable, "-c", code],
        env=_ghunt_env(),
    )


_FIELD_NAMES = {
    "Name": "Имя",
    "Email": "Email",
    "Gaia ID": "Gaia ID",
    "Username": "Ник",
    "Player ID": "Player ID",
    "Entity Type": "Тип аккаунта",
    "Last profile edit": "Последнее изменение профиля",
}


def parse_ghunt(raw: str, email: str) -> dict:
    """Парсит вывод GHunt (JSON или текстовый) в словарь полей."""
    try:
        payload = json.loads(raw)
        data = {
            "name": payload.get("name"),
            "localized_personal_name": payload.get("localized_personal_name"),
            "given_name": payload.get("given_name"),
            "family_name": payload.get("family_name"),
            "picture": payload.get("picture"),
            "email": payload.get("email"),
            "gmail_background_uri": payload.get("gmail_background_uri"),
            "uri": payload.get("uri"),
        }
        data = {k: v for k, v in data.items() if v}
        if data:
            return data
    except (json.JSONDecodeError, TypeError):
        pass

    data: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r"^(Email|Gaia ID|Username|Player ID|Entity Type|Last profile edit)\s*:\s*(.+)$", line)
        if m:
            data[_FIELD_NAMES.get(m.group(1), m.group(1))] = m.group(2).strip()
    if data:
        return data

    tail = "\n".join(raw.splitlines()[-20:]).strip()
    if tail:
        return {"raw": tail[:1500]}
    return {}


def format_email_report(email: str, holehe: dict | None = None,
                        h8mail_out: list[str] | None = None,
                        social: dict | None = None,
                        ghunt: dict | None = None) -> str:
    """Собирает итоговый отчёт по email."""
    lines: list[str] = []
    add = lines.append
    add("<b>📧 ОТЧЁТ ПО EMAIL</b>")
    add(f"<blockquote>{str(email)}</blockquote>")
    add("")

    if holehe:
        found = {k: v for k, v in holehe.items() if "FOUND" in str(v)}
        add(f"<b>🔎 holehe — аккаунтов найдено: {len(found)} из {len(holehe)}</b>")
        for site, status in sorted(found.items(), key=lambda kv: str(kv[0]))[:25]:
            add(f"│ <b>{str(site)}</b> — {str(status)}")
        if len(found) > 25:
            add(f"│ … ещё {len(found) - 25}")
        add("")

    if social:
        add("<b>🕸 socialscan</b>")
        for site, status in social.items():
            mark = "⭕" if status == "Найден" else "✖️"
            add(f"│ {str(site)}: {mark} {str(status)}")
        add("")

    if h8mail_out:
        add(f"<b>💥 h8mail — утечек/следов: {len(h8mail_out)}</b>")
        for line in h8mail_out[:25]:
            add(f"│ {str(line)[:256]}")
        add("")

    if ghunt:
        add("<b>🔮 GHunt (Google)</b>")
        if "raw" in ghunt:
            add(f"│ {str(ghunt['raw'])[:1000]}")
        else:
            for k, v in ghunt.items():
                add(f"│ {str(k)}: <code>{str(v)}</code>")
        add("")

    add("⚡ Данные из открытых источников. Используйте только в законных целях.")
    return "\n".join(lines)