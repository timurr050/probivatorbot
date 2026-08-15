"""Тесты проверки профилей по публичным API (оффлайн, с фейковым HTTP)."""
from __future__ import annotations

import asyncio

import pytest

from bot.services.public_api import (
    _PROBES,
    _page,
    check_public_profiles,
    format_public_profiles_section,
)


class FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]):
        self.responses = responses

    async def get(self, url, **_kw):
        # точное совпадение либо любой ответ с «кодом» по умолчанию
        if url in self.responses:
            return self.responses[url]
        return FakeResponse(200, "")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_github_found_with_details():
    probe = next(p for p in _PROBES if p["label"] == "GitHub")
    session = FakeSession({
        "https://api.github.com/users/alex": FakeResponse(
            200, '{"login":"alex","name":"Alex","location":"Moscow","followers":42,"public_repos":7,"created_at":"2015-01-01T00:00:00Z"}'
        ),
    })
    found, detail = await probe["check"](session, "alex")
    assert found is True
    assert "Alex" in detail and "Moscow" in detail and "42" in detail


@pytest.mark.asyncio
async def test_github_not_found():
    probe = next(p for p in _PROBES if p["label"] == "GitHub")
    session = FakeSession({"https://api.github.com/users/nope": FakeResponse(404)})
    found, detail = await probe["check"](session, "nope")
    assert found is False


@pytest.mark.asyncio
async def test_page_probe_statuses():
    check = _page("https://t.me/{u}")
    session = FakeSession({
        "https://t.me/alex": FakeResponse(302),
        "https://t.me/none": FakeResponse(404),
        "https://t.me/x": FakeResponse(503),
    })
    assert await check(session, "alex") == (True, "")
    assert await check(session, "none") == (False, "")
    found, detail = await check(session, "x")
    assert found is None and "503" in detail


@pytest.mark.asyncio
async def test_check_public_profiles_all_runs():
    """Весь список пробников отрабатывает и возвращает N записей."""
    session = FakeSession({})
    results = await check_public_profiles("alex", session=session)
    assert isinstance(results, list)
    assert len(results) == len(_PROBES)
    for r in results:
        assert r["label"] and "found" in r and "url" in r


def test_format_section():
    results = [
        {"label": "GitHub", "emoji": "🐙", "found": True, "url": "https://github.com/alex", "detail": "имя: Alex"},
        {"label": "Reddit", "emoji": "🔺", "found": False, "url": "", "detail": ""},
        {"label": "Twitch", "emoji": "🎮", "found": None, "url": "", "detail": "код 503"},
    ]
    lines = format_public_profiles_section(results)
    joined = "\n".join(lines)
    assert "Профили по публичным API" in joined
    assert "найден" in joined
    assert "не найден" in joined
    assert "не удалось" in joined


def test_format_section_empty():
    assert format_public_profiles_section([]) == []
    assert format_public_profiles_section(None) == []
