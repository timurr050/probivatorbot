"""
Сервис поиска по email.

Двигатели:
  * holehe     — проверка регистрации email на 120+ сайтах;
  * h8mail     — поиск email в утечках (требует h8mail_config.ini / hunter.io ключ);
  * socialscan — проверка доступности email на ключевых сервисах;
  * GHunt      — разведка Google-аккаунта по email.
"""
from __future__ import annotations

import asyncio
import re

from bot.config import SETTINGS
from bot.exceptions import ToolNotConfigured
from bot.services.base import ensure_binary, run_cli
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

    proc = await asyncio.create_subprocess_exec(
        str(binary),
        email,
        "--no-color",
        "--only-used",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=SETTINGS.cli_timeout)
        return raw.decode(SETTINGS.cli_encoding, errors="replace")
    except asyncio.TimeoutError:
        raise ToolNotConfigured("holehe прерван по таймауту. Попробуйте снова позже.")


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

    proc = await asyncio.create_subprocess_exec(
        str(binary),
        "-t",
        email,
        "--loose",
        "-q",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=SETTINGS.cli_timeout)
        return raw.decode(SETTINGS.cli_encoding, errors="replace")
    except asyncio.TimeoutError:
        raise ToolNotConfigured("h8mail прерван по таймауту.")


def parse_h8mail(raw: str, email: str) -> list[str]:
    """Извлекает найденные строки из вывода h8mail."""
    result: list[str] = []
    lines = raw.splitlines()
    start = None
    for i, line in enumerate(lines):
        if "Results" in line and "for" in line:
            start = i
            break
    pool = lines[start + 1:] if start is not None else lines
    for line in pool:
        line = line.strip()
        if not line or line.startswith(("Saving", "Output", "Done", "Query", ">", "[i]")):
            continue
        result.append(line)
    return result[:40]


# ----------------------------------------------------------------------------
# GHunt
# ----------------------------------------------------------------------------

async def run_ghunt(email: str) -> str:
    """Запускает GHunt по email (требуется предварительная авторизация ghunt check)."""
    try:
        binary = ensure_binary(None, "ghunt")
    except ToolNotConfigured:
        raise ToolNotConfigured("GHunt не установлен:\n<code>pip install ghunt</code>")

    proc = await asyncio.create_subprocess_exec(
        str(binary),
        "email",
        email,
        "--cookie",
        "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=SETTINGS.cli_timeout)
        return raw.decode(SETTINGS.cli_encoding, errors="replace")
    except asyncio.TimeoutError:
        raise ToolNotConfigured("GHunt прерван по таймауту.")


def parse_ghunt(raw: str, email: str) -> dict:
    """Парсит ключевые поля JSON-вывода GHunt."""
    import json
    data = {}
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
    except (json.JSONDecodeError, TypeError):
        return {"raw": raw[:1500]}
    return data


def format_email_report(email: str, holehe: dict | None = None,
                        h8mail_out: list[str] | None = None,
                        social: dict | None = None,
                        ghunt: dict | None = None) -> str:
    """Собирает итоговый отчёт по email."""
    lines: list[str] = []
    add = lines.append
    add("<b>📧 ОТЧЁТ ПО EMAIL</b>")
    add(f"└ <code>{str(email)}</code>")
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