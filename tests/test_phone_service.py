"""Тесты сервисов по телефону (оффлайн, без сети)."""
from __future__ import annotations

from bot.exceptions import ValidationError
from bot.services.phone_service import (
    format_phone_report,
    parse_ignorant,
    phonenumbers_info,
    summarize_phoneinfoga,
)
from bot.utils.validators import normalize_phone


def test_phonenumbers_info_belarus():
    e164 = normalize_phone("+375291234567")
    info = phonenumbers_info(e164)
    assert info["e164"] == "+375291234567"
    assert info["valid"] is True
    assert info["region"] == "BY"
    assert info["country_code"] == "+375"
    assert "29" in info["national"]
    assert "Мобильный" in info["type"]
    assert isinstance(info["timezones"], list)


def test_phonenumbers_info_russia():
    info = phonenumbers_info("+79001234567")
    assert info["valid"] is True
    assert info["region"] == "RU"
    assert info["country_code"] == "+7"


def test_phonenumbers_info_india():
    # валидный индийский мобильный
    info = phonenumbers_info("+919876543210")
    assert info["valid"] is True
    assert info["region"] == "IN"


def test_format_phone_report_full():
    info = phonenumbers_info("+375291234567")
    text = format_phone_report(
        "+375291234567",
        info,
        telegram={"registered": False},
        phoneinfoga=["Country: Belarus", "Carrier: A1"],
        ignorant={"Instagram": "Not found", "VK": "Found"},
    )
    assert "ОТЧЁТ ПО НОМЕРУ" in text
    assert "ИЗВЕСТЕН" in text
    assert "PhoneInfoga" in text
    assert "Instagram" in text


def test_parse_ignorant_sample():
    raw = """
░ Starting ignorant
Instagram -> Not found
VK -> Found
Facebook -> Not found
"""
    parsed = parse_ignorant(raw, "+375291234567")
    assert parsed["Instagram"] == "Not found"
    assert parsed["VK"] == "Found"
    assert len(parsed) == 3


def test_summarize_phoneinfoga_dedupe():
    raw = """
[+] Started
[+] Started
Country: Belarus
Carrier: A1
Country: Belarus
"""
    lines = summarize_phoneinfoga(raw, "+375291234567")
    assert lines.count("Country: Belarus") == 1
    assert lines.count("Carrier: A1") == 1
    assert len(lines) <= 60