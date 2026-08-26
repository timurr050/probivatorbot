"""
Сервис поиска никнейма через Maigret (3000+ сайтов, без API-ключей).

Maigret сканирует публичные страницы прямыми HTTP-запросами + регулярками.
Запускается как CLI: `python -m maigret <username> ...`.

Особенности:
  * на Windows штатный async-DNS (aiodns) падает — нужен `--dns-resolver threaded`;
  * баннер с эмодзи роняет cp1251-консоль — выставляем PYTHONIOENCODING=utf-8;
  * найденные аккаунты печатаются строками `[+] Сайт: url`, детали — ` ├─ ...`;
  * JSON-отчёты (`reports/`) уходили в каталог проекта — поэтому запуск идёт
    во временной папке (`cwd`), чтобы не засорять репозиторий.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path

from bot.exceptions import ToolNotConfigured
from bot.services.base import run_cli_async

_FOUND_LINE = re.compile(r"^\[\+\]\s*(.*?):\s*(https?://\S+)$")
_DETAIL_LINE = re.compile(r"^[├└└┌]─\s*(.*)$")
_SUMMARY_RE = re.compile(r"returned\s+(\d+)\s+accounts?", re.IGNORECASE)
_TAGS_RE = re.compile(r"Interests\s*\(tags\):\s*(.+)$", re.IGNORECASE)


def _maigret_available() -> bool:
    try:
        return importlib.util.find_spec("maigret") is not None
    except (ImportError, ValueError):
        return False


def _maigret_env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("LC_ALL", None)
    env.pop("LANG", None)
    return env


async def run_maigret(username: str, top_sites: int = 150) -> str:
    """Запускает maigret по никнейму, возвращает сырой stdout отчёта."""
    if not _maigret_available():
        raise ToolNotConfigured(
            "maigret не установлен:\n<code>pip install maigret</code>\n"
            "Maigret сканирует 3000+ сайтов по никнейму без API-ключей."
        )

    args = [
        sys.executable, "-m", "maigret", username,
        "--timeout", "15",
        "--dns-resolver", "threaded",
        "--no-color",
        "--no-progressbar",
        "--top-sites", str(top_sites),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        return await run_cli_async(args, env=_maigret_env(), cwd=tmp)


def parse_maigret(raw: str) -> dict:
    """Разбирает stdout maigret в структурированный результат.

    Возвращает:
      {
        'found': [{'site': str, 'url': str, 'detail': list[str]}, ...],
        'count': int | None,
        'tags': str | None,
      }
    """
    found: list[dict] = []
    last: dict | None = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _FOUND_LINE.match(line)
        if m:
            entry = {"site": m.group(1).strip(), "url": m.group(2).strip(), "detail": []}
            found.append(entry)
            last = entry
            continue
        d = _DETAIL_LINE.match(line)
        if last and d:
            detail = d.group(1).strip()
            if detail and detail not in last["detail"]:
                last["detail"].append(detail)

    count = None
    s = _SUMMARY_RE.search(raw)
    if s:
        count = int(s.group(1))

    tags = None
    t = _TAGS_RE.search(raw)
    if t:
        tags = t.group(1).strip()

    return {"found": found, "count": count, "tags": tags}


def format_maigret_section(parsed: dict) -> list[str]:
    """Готовит секцию «🕵️ Maigret» для общего отчёта."""
    lines: list[str] = []
    found = parsed.get("found") or []
    if not found:
        return lines

    add = lines.append
    add(f"<b>🕵️ Maigret — аккаунтов найдено: {len(found)}</b>")
    for entry in found:
        site = str(entry["site"])
        url = str(entry["url"]).strip()
        if url:
            add(f"│ 🔗 <b>{site}</b>: <a href='{url}'>открыть профиль</a>")
        else:
            add(f"│ 🔗 <b>{site}</b>")
        for detail in entry["detail"][:8]:
            add(f"│    └ {detail}")
    return lines
