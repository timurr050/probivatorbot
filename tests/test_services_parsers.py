"""Тесты парсеров email-сервисов и username-сервисов (оффлайн)."""
from __future__ import annotations

from bot.services.email_service import parse_h8mail, parse_ghunt, parse_holehe
from bot.services.username_service import parse_socialscan, format_username_report


HOLEHE_SAMPLE = r"""
[+] Email used: example@gmail.com
   [+] = found account
   [-] = not found
   [p] = account requires payment
   [e] = error during obtaining data
   [x] = not an account

[+] Adobe [+]
[x] Airbnb [x]
[e] Amazon [e]
[+] Apple [+]
[p] DigitalOcean [p]
"""


def test_parse_holehe():
    parsed = parse_holehe(HOLEHE_SAMPLE, "example@gmail.com")
    assert "FOUND" in str(parsed.get("Adobe"))
    assert "NOT_FOUND" in str(parsed.get("Airbnb"))
    assert "rate_limited" in str(parsed.get("DigitalOcean"))
    assert "error" in str(parsed.get("Amazon"))
    # [e Amazon] etc


H8MAIL_SAMPLE = """
Query: example@gmail.com
h8mail v2.5.6
[Input] example@gmail.com
Saving results...

***** Results for example@gmail.com *****
[+] example@gmail.com:password123
[+] example@gmail.com:qwerty

Saving to ./h8mail_targets_example_gmail_com.csv
"""


def test_parse_h8mail():
    lines = parse_h8mail(H8MAIL_SAMPLE, "example@gmail.com")
    assert any("password123" in ln for ln in lines)
    assert len(lines) >= 1


GHUNT_SAMPLE = '{"name":"John Doe","given_name":"John","family_name":"Doe","email":"johndoe@example.com","localized_personal_name":"Johnny"}'
GHUNT_BAD = "ERROR: not authenticated. Run ghunt check"


def test_parse_ghunt():
    data = parse_ghunt(GHUNT_SAMPLE, "johndoe@example.com")
    assert data["given_name"] == "John"
    assert data["email"] == "johndoe@example.com"
    empty = parse_ghunt(GHUNT_BAD, "johndoe@example.com")
    assert "raw" in empty


SOCIALSCAN_SAMPLE = """
---------------
@alex
---------------

Instagram: Available
Twitter: Taken/Reserved
Github: Available
Reddit: ConnectionTimeoutError
Discord: Invalid
Facebook: exists
"""


def test_parse_socialscan():
    data = parse_socialscan(SOCIALSCAN_SAMPLE)
    assert data.get("instagram") == "Свободен"
    assert data.get("twitter") == "Найден"
    assert data.get("reddit") == "Ошибка"
    assert data.get("discord") == "Невалиден"
    assert data.get("facebook") == "Найден"
    # мусорные строки не попадают
    assert "@alex" not in data


def test_format_username_report():
    text = format_username_report(
        "alex",
        sherlock=[f"https://github.com/alex"],
        social={"instagram": "Найден", "twitter": "Свободен"},
        telegram={"found": True, "id": 123, "username": "alex", "first_name": "Alex", "bot": False, "premium": False, "verified": False, "scam": False, "fake": False, "type": "User"},
    )
    assert "ОТЧЁТ ПО НИКНЕЙМУ" in text
    assert "@alex" in text
    assert "ID: <code>123</code>" in text