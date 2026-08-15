"""Тесты проверки регистрации в популярных сервисах (оффлайн, с фейковым HTTP)."""
from __future__ import annotations

import asyncio

import pytest

from bot.services.registration_service import (
    _digits,
    _profile_url,
    format_registrations_section,
    probe_github_email,
    probe_instagram_email,
    probe_telegram_username,
    probe_whatsapp_phone,
)


class FakeHeaders:
    def __init__(self, location: str = ""):
        self._loc = location

    def get(self, key: str, default: str = ""):
        return self._loc if key.lower() == "location" else default


class FakeResponse:
    def __init__(self, status_code: int, text: str = "", location: str = ""):
        self.status_code = status_code
        self.text = text
        self.headers = FakeHeaders(location)


class FakeSession:
    """Фейковый сессион: отдаёт заранее подготовленные ответы подряд."""

    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **_kw):
        self.calls.append(f"GET {url}")
        return self.responses.pop(0)

    async def post(self, url, **_kw):
        self.calls.append(f"POST {url}")
        return self.responses.pop(0)


async def _run(check, responses, target="x"):
    session = FakeSession(responses)
    return await check(session, target)


def test_digits_helper():
    assert _digits("+7 (900) 123-45-67") == "79001234567"


def test_profile_url():
    svc = {"key": "telegram"}
    assert _profile_url(svc, "alex", "username") == "https://t.me/alex"
    svc = {"key": "instagram"}
    assert _profile_url(svc, "alex", "username") == "https://www.instagram.com/alex/"
    svc = {"key": "github"}
    assert _profile_url(svc, "alex", "email") == ""


@pytest.mark.asyncio
async def test_github_probe_found():
    ok = await _run(
        probe_github_email("x@y.z"),
        [FakeResponse(200, '{"status":"fail","message":"There is already an account with this email address"}')],
    )
    assert ok is True


@pytest.mark.asyncio
async def test_github_probe_available():
    ok = await _run(
        probe_github_email("x@y.z"),
        [FakeResponse(200, '{"status":"ok","message":null}')],
    )
    assert ok is False


@pytest.mark.asyncio
async def test_github_probe_unknown():
    ok = await _run(
        probe_github_email("x@y.z"),
        [FakeResponse(422, "<!DOCTYPE html>blocked")],
    )
    assert ok is None


@pytest.mark.asyncio
async def test_github_probe_422_with_json():
    """GitHub отдаёт и 422 с полезным JSON — это тоже «аккаунт есть»."""
    ok = await _run(
        probe_github_email("x@y.z"),
        [FakeResponse(422, '{"status":"fail","message":"There is already an account with this email address"}')],
    )
    assert ok is True


@pytest.mark.asyncio
async def test_instagram_probe_found_with_cookies():
    """Сначала берём cookies (GET), потом POST — ответ JSON «email занят»."""
    probe = probe_instagram_email("x@y.z")
    ok = await probe(
        FakeSession([
            FakeResponse(200, ""),
            FakeResponse(200, '{"errors":{"email":["Another account is using this email address."]}}'),
        ]),
        "x@y.z",
    )
    assert ok is True


@pytest.mark.asyncio
async def test_whatsapp_probe():
    assert await _run(
        probe_whatsapp_phone("79161234567"),
        [FakeResponse(200, '{"status":"ok"}')],
        target="79161234567",
    ) is True
    assert await _run(
        probe_whatsapp_phone("79161234567"),
        [FakeResponse(200, '{"status":"fail","reason":"account_unavailable"}')],
        target="79161234567",
    ) is False
    assert await _run(
        probe_whatsapp_phone("79161234567"),
        [FakeResponse(503, "")],
        target="79161234567",
    ) is None


@pytest.mark.asyncio
async def test_telegram_probe():
    assert await _run(
        probe_telegram_username("alex"),
        [FakeResponse(302, location="https://t.me/s/alex")],
    ) is True
    assert await _run(probe_telegram_username("alex"), [FakeResponse(404)]) is False
    assert await _run(probe_telegram_username("alex"), [FakeResponse(503)]) is None


def test_format_registrations_section_states():
    results = [
        {"key": "whatsapp", "label": "WhatsApp", "emoji": "💬", "found": True, "url": ""},
        {"key": "github", "label": "GitHub", "emoji": "🐙", "found": False, "url": ""},
        {"key": "tiktok", "label": "TikTok", "emoji": "🎵", "found": None, "url": ""},
    ]
    lines = format_registrations_section(results)
    joined = "\n".join(lines)
    assert "Аккаунты в популярных сервисах" in joined
    assert "аккаунт найден" in joined
    assert "аккаунт не найден" in joined
    assert "не удалось проверить" in joined


def test_format_registrations_section_empty():
    assert format_registrations_section([]) == []
    assert format_registrations_section(None) == []


@pytest.mark.asyncio
async def test_check_registrations_calls_probe_factory(monkeypatch):
    """Регрессия: фабрика пробника вызывалась как await probe(...) →
    TypeError «object function can't be used in await expression» и все
    сервисы показывали «⚠️ не удалось проверить (TypeError)»."""
    import curl_cffi.requests as crequests

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **_kw):
            self.calls.append(("POST", url))
            return FakeResponse(
                200,
                '{"status":"fail","message":"There is already an account with this email address"}',
            )

        async def get(self, url, **_kw):
            self.calls.append(("GET", url))
            return FakeResponse(200, "")

    fake = FakeSession()
    fake.calls = []

    monkeypatch.setattr(crequests, "AsyncSession", lambda: fake)
    monkeypatch.setattr(
        "bot.services.registration_service._curl_available", lambda: True
    )
    from bot.services import registration_service as reg_svc

    monkeypatch.setattr(reg_svc, "_ALL_SERVICES", ["github"])

    results = await reg_svc.check_registrations("test@example.com", "email")
    assert results, "должен быть хотя бы один результат"
    github = next(r for r in results if r["key"] == "github")
    assert github["found"] is True, github
    assert github["note"] != "TypeError", github
