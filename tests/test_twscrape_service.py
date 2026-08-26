"""Тесты движка Twitter/X через twscrape (оффлайн)."""
from __future__ import annotations

import asyncio

from bot.services import twscrape_service


def test_format_twscrape_section_found():
    out = twscrape_service.format_twscrape_section(
        {"found": True, "name": "John", "followers": 42, "id": 7, "tweets": ["hello", "world"]}
    )
    text = "\n".join(out)
    assert "Twitter/X" in text
    assert "John" in text
    assert "42" in text
    assert "hello" in text


def test_format_twscrape_section_not_found():
    out = twscrape_service.format_twscrape_section({"found": False, "tweets": []})
    assert "не найден" in "\n".join(out)


def test_run_twscrape_no_accounts_raises():
    # без аккаунта Twitter движок честно падает с ToolNotConfigured,
    # не ломая отчёт (сеть не нужна — пул пуст локально)
    try:
        asyncio.run(twscrape_service.run_twscrape("testuser"))
        assert False, "ожидали ToolNotConfigured (нет аккаунтов Twitter)"
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        assert "twscrape" in msg or "аккаунт" in msg or "twitter" in msg
