"""Тесты парсера и форматтера Maigret (оффлайн)."""
from __future__ import annotations

from bot.services.maigret_service import format_maigret_section, parse_maigret

MAIGRET_SAMPLE = r"""
[+] MAIGRET - collect a dossier by username from 3000+ sites
[+] Using sites database: data.json (3221 sites)
[*] Checking username johnsmith on:

[+] GitHub: https://github.com/johnsmith
 ├─uid: 296614
 ├─fullname: John
 └─public_repos_count: 0

[+] GitHubGist [GitHub]: https://gist.github.com/johnsmith
[!] Too many errors of type "Request failed" (14.29%)
[*] Short text report:
Search by username johnsmith returned 2 accounts.
Extended info extracted from 1 accounts.
Interests (tags): coding, business, networking, sharing
"""


def test_parse_maigret_found_sites():
    parsed = parse_maigret(MAIGRET_SAMPLE)
    assert parsed["count"] == 2
    assert parsed["tags"] == "coding, business, networking, sharing"
    assert len(parsed["found"]) == 2
    assert parsed["found"][0]["site"] == "GitHub"
    assert parsed["found"][0]["url"] == "https://github.com/johnsmith"
    assert any("uid: 296614" in d for d in parsed["found"][0]["detail"])
    assert "GitHubGist" in parsed["found"][1]["site"]


def test_parse_maigret_empty():
    parsed = parse_maigret("Search by username x returned 0 accounts.")
    assert parsed["count"] == 0
    assert parsed["found"] == []
    assert parsed["tags"] is None


def test_format_maigret_section_empty():
    assert format_maigret_section({"found": [], "count": 0, "tags": None}) == []


def test_format_maigret_section():
    lines = format_maigret_section(parse_maigret(MAIGRET_SAMPLE))
    assert any("Maigret — аккаунтов найдено: 2" in line for line in lines)
    assert any("GitHub" in line and "открыть профиль" in line for line in lines)
