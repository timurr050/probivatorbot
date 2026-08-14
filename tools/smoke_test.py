"""
Live-смоук-тест: проверяет, что каждый движок реально запускается и даёт данные.

Не является частью pytest (использует сеть). Запуск:
    .venv\\Scripts\\python.exe tools\\smoke_test.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.services import email_service, phone_service, username_service  # noqa: E402
from bot.services.base import ensure_binary  # noqa: E402


def check_binary(name: str) -> str:
    try:
        ensure_binary(None, name)
        return f"OK   {name}"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL {name}: {str(exc)[:80]}"


def check_phone_local() -> str:
    info = phone_service.phonenumbers_info("+375291234567")
    if info["valid"] and info["region"] == "BY":
        return f"OK   phonenumbers (+375291234567 -> BY, {info['type']})"
    return f"FAIL phonenumbers: {info}"


def check_phoneinfoga() -> str:
    raw = phone_service.run_phoneinfoga("+12125654777")
    ok = "Country: US" in raw or "succeeded" in raw
    return f"OK   PhoneInfoga (scan works)" if ok else f"FAIL PhoneInfoga: {raw[:120]}"


def check_socialscan() -> str:
    raw = asyncio.run(username_service.run_socialscan("@probivbot_test")) or ""
    parsed = username_service.parse_socialscan(raw)
    n_ok = sum(1 for v in parsed.values() if v == "Свободен")
    n_err = sum(1 for v in parsed.values() if v == "Ошибка")
    return (f"OK   socialscan ({len(parsed)} платформ, свободно: {n_ok}, "
            f"найдено: {sum(1 for v in parsed.values() if v == 'Найден')}, ошибок: {n_err})")


def check_holehe() -> str:
    raw = asyncio.run(email_service.run_holehe("test@mail.ru"))
    parsed = email_service.parse_holehe(raw, "test@mail.ru")
    found = sum(1 for v in parsed.values() if "FOUND" in str(v))
    if parsed:
        return f"OK   holehe ({len(parsed)} сайтов, найдено аккаунтов: {found})"
    return "WARN holehe: не удалось распарсить вывод"


def check_ghunt_not_authed() -> str:
    try:
        raw = asyncio.run(email_service.run_ghunt("test@example.com"))
        return f"INFO ghunt: запустился, но результат зависит от авторизации ({raw[:60]})"
    except Exception as exc:  # noqa: BLE001
        return f"INFO ghunt: {str(exc)[:90]}"


def check_telegram_not_configured() -> str:
    try:
        res = asyncio.run(phone_service.check_telegram("+375291234567"))
        return f"INFO telegram-check: {res}"
    except Exception as exc:  # noqa: BLE001
        return f"INFO telegram-check: {str(exc)[:100]}"


def main() -> None:
    print("=== ProbivBot smoke-test ===")
    checks = [
        ("BIN", lambda: check_binary("sherlock")),
        ("BIN", lambda: check_binary("holehe")),
        ("BIN", lambda: check_binary("h8mail")),
        ("BIN", lambda: check_binary("ignorant")),
        ("BIN", lambda: check_binary("snscrape")),
        ("BIN", lambda: check_binary("socialscan")),
        ("BIN", lambda: check_binary("ghunt")),
        ("PHONE", check_phone_local),
        ("PHONE", check_phoneinfoga),
        ("NET", check_socialscan),
        ("NET", check_holehe),
        ("INFO", check_ghunt_not_authed),
        ("INFO", check_telegram_not_configured),
    ]
    for kind, fn in checks:
        t0 = time.time()
        try:
            print(f"[{kind}] {fn()}  ({time.time() - t0:.1f}s)")
        except Exception as exc:  # noqa: BLE001
            print(f"[{kind}] ERROR {type(exc).__name__}: {str(exc)[:120]}  ({time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main()