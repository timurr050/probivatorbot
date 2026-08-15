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

GHUNT_SETUP = (
    "🔮 Настройка GHunt (разведка Google-аккаунтов):\n\n"
    "1️⃣ Установите:\n"
    "   <code>pip install ghunt</code>\n\n"
    "2️⃣ Авторизуйтесь один раз в консоли:\n"
    "   <code>ghunt login</code>\n"
    "   Откроется браузер — войдите в Google и разрешите доступ.\n"
    "   GHunt сам сохранит токен в файл <code>creds.data</code>:\n"
    "   • Windows: <code>C:\\Users\\Имя\\.pyconfig\\ghunt\\creds.data</code>\n"
    "   • Linux/Docker: <code>/root/.pyconfig/ghunt/creds.data</code>\n\n"
    "3️⃣ Бот в Docker — примонтируйте папку с токеном (volume к сервису):\n"
    "   <code>./ghunt:/root/.pyconfig/ghunt</code>\n"
    "   и положите <code>creds.data</code> в папку <code>./ghunt</code> "
    "рядом с docker-compose.yml.\n"
    "   Либо укажите путь к папке с токеном в <code>.env</code>:\n"
    "   <code>GHUNT_CONFIG_PATH=/путь/к/папке/с/creds.data</code>\n\n"
    "4️⃣ Проверка: <code>ghunt check</code>\n"
    "Документация: https://github.com/mxrch/ghunt"
)


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
        raise ToolNotConfigured(
            "GHunt не установлен:\n<code>pip install ghunt</code>\n\n" + GHUNT_SETUP
        )

    if not _ghunt_creds_exist():
        raise ToolNotConfigured("GHunt не авторизован в Google.\n\n" + GHUNT_SETUP)

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


def _holehe_status_ru(status: object) -> str:
    """Русское отображение статуса сайта из holehe."""
    mapping = {
        "🇷🇺 FOUND": "найден",
        "❌ NOT_FOUND": "не найден",
        "rate_limited": "лимит запросов",
        "error": "ошибка",
        "not_checked": "не проверен",
    }
    return mapping.get(str(status), str(status))


# Краткое описание каждого движка для блока «Что и как проверено»
_ENGINE_DESC = {
    "reg": "🪪 Регистрации в популярных сервисах (ВК/Instagram/TikTok/WhatsApp/Telegram/GitHub)",
    "holehe": "🔎 holehe — на каких сайтах зарегистрирован email (120+ сервисов)",
    "h8mail": "💥 h8mail — поиск email в базах утечек",
    "ss": "🕸 socialscan — занятость email в соцсетях",
    "ghunt": "🔮 GHunt — Google-профиль и связанные данные",
}


def _holehe_counts(holehe: dict) -> tuple[int, int, int, int]:
    """Подсчёт (найдено, не найдено, ошибок/лимита, всего)."""
    found = sum(1 for v in holehe.values() if "FOUND" in str(v))
    not_found = sum(1 for v in holehe.values() if "NOT_FOUND" in str(v))
    other = sum(1 for v in holehe.values() if str(v) in ("rate_limited", "error"))
    return found, not_found, other, len(holehe)


def format_email_report(email: str, holehe: dict | None = None,
                        h8mail_out: list[str] | None = None,
                        social: dict | None = None,
                        ghunt: dict | None = None,
                        registrations: list[dict] | None = None,
                        attempted: list[str] | None = None) -> str:
    """Собирает итоговый отчёт по email.

    attempted — какие движки запускались («всё сразу»), чтобы честно показать,
    что именно проверялось и что не выполнилось.
    """
    from bot.services.registration_service import format_registrations_section

    lines: list[str] = []
    add = lines.append
    add("<b>📧 ОТЧЁТ ПО EMAIL</b>")
    add(f"<blockquote>{str(email)}</blockquote>")
    add("")

    # ---- Что и как проверено (сводка всех движков) ----
    if attempted:
        add("<b>🧰 Что и как проверено</b>")
        for key in attempted:
            desc = _ENGINE_DESC.get(key, f"⚙️ {key}")
            if key == "reg" and registrations is not None:
                ok = len([r for r in registrations if r.get("found")])
                add(f"✅ {desc}: аккаунтов найдено — {ok}")
            elif key == "holehe" and holehe is not None:
                f, nf, oth, total = _holehe_counts(holehe)
                add(f"✅ {desc}: найдено {f} из {total} · не найдено {nf}"
                    + (f" · ошибок {oth}" if oth else ""))
            elif key == "h8mail" and h8mail_out is not None:
                add(f"✅ {desc}: найдено следов — {len(h8mail_out)}")
            elif key == "ss" and social is not None:
                found = sum(1 for v in social.values() if v == "Найден")
                add(f"✅ {desc}: найдено {found} из {len(social)}")
            elif key == "ghunt" and ghunt:
                extra = "профиль получен"
                if ghunt.get("name") or ghunt.get("email"):
                    extra = f"имя: {ghunt.get('name') or ghunt.get('email')}"
                add(f"✅ {desc}: {extra}")
            else:
                add(f"❌ {desc}: не выполнилось (см. ниже)")
        add("")
    elif any(x is not None for x in (holehe, h8mail_out, social, ghunt, registrations)):
        add("<b>🧰 Что и как проверено</b>")
        if registrations is not None:
            ok = len([r for r in registrations if r.get("found")])
            add(f"✅ {_ENGINE_DESC['reg']}: аккаунтов найдено — {ok}")
        if holehe is not None:
            f, nf, oth, total = _holehe_counts(holehe)
            add(f"✅ {_ENGINE_DESC['holehe']}: найдено {f} из {total} · не найдено {nf}"
                + (f" · ошибок {oth}" if oth else ""))
        if h8mail_out is not None:
            add(f"✅ {_ENGINE_DESC['h8mail']}: найдено следов — {len(h8mail_out)}")
        if social is not None:
            found = sum(1 for v in social.values() if v == "Найден")
            add(f"✅ {_ENGINE_DESC['ss']}: найдено {found} из {len(social)}")
        if ghunt:
            add(f"✅ {_ENGINE_DESC['ghunt']}: профиль получен")
        add("")

    # ---- holehe: полный список проверенных сайтов ----
    if holehe:
        f, nf, oth, total = _holehe_counts(holehe)
        add(f"<b>🔎 holehe — {total} сайтов: найдено {f}, не найдено {nf}"
            + (f", ошибок {oth}" if oth else "") + "</b>")
        found_sorted = sorted(
            ((k, v) for k, v in holehe.items() if "FOUND" in str(v)),
            key=lambda kv: str(kv[0]),
        )
        if found_sorted:
            add("— где email ЗАРЕГИСТРИРОВАН:")
            for site, status in found_sorted[:40]:
                add(f"│ ✅ <b>{str(site)}</b>")
            if len(found_sorted) > 40:
                add(f"│ … и ещё {len(found_sorted) - 40} сайтов")
        if not found_sorted:
            add("│ 🚫 Ни одного аккаунта не найдено")
        add("")

    # ---- socialscan ----
    if social:
        add("<b>🕸 socialscan — занятость email в соцсетях</b>")
        for site, status in social.items():
            mark = "⭕" if status == "Найден" else ("✖️" if status == "Свободен" else "⚠️")
            add(f"│ {str(site)}: {mark} {str(status)}")
        add("")

    # ---- h8mail: все утечки ----
    if h8mail_out:
        add(f"<b>💥 h8mail — утечек/следов: {len(h8mail_out)}</b>")
        for line in h8mail_out[:40]:
            add(f"│ {str(line)[:256]}")
        if len(h8mail_out) > 40:
            add(f"│ … и ещё {len(h8mail_out) - 40}")
        add("")

    # ---- GHunt (Google) ----
    if ghunt:
        add("<b>🔮 GHunt (Google) — профиль аккаунта</b>")
        if "raw" in ghunt:
            add(f"│ {str(ghunt['raw'])[:1000]}")
        else:
            for k, v in ghunt.items():
                add(f"│ {str(k)}: <code>{str(v)}</code>")
        add("")

    if registrations:
        add("\n".join(format_registrations_section(registrations)))
        add("")

    add("⚡ Данные из открытых источников. Используйте только в законных целях.")
    return "\n".join(lines)