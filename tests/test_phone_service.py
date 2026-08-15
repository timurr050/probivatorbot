"""Тесты сервисов по телефону (оффлайн, без сети)."""
from __future__ import annotations

from bot.exceptions import ValidationError
from bot.services.phone_service import (
    _link_domain,
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
        registrations=[
            {"key": "whatsapp", "label": "WhatsApp", "emoji": "💬", "found": True, "url": ""},
        ],
    )
    assert "ОТЧЁТ ПО НОМЕРУ" in text
    assert "не найден в Telegram" in text
    assert "PhoneInfoga" in text
    assert "Instagram" in text
    assert "Аккаунты в популярных сервисах" in text
    assert "WhatsApp" in text


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
    joined = "\n".join(lines)
    # дубликаты схлопнулись, инфо на русском
    assert "Belarus" in joined
    assert "A1" in joined
    assert joined.count("Belarus") == 1
    assert len(lines) <= 60


def test_summarize_phoneinfoga_sections():
    """Реальный вывод PhoneInfoga: категории переводятся, ссылки чистятся."""
    raw = """
Running scan for phone number +375291234567...

Results for googlesearch
Social media:
\tURL: https://www.google.com/search?q=site%3Afacebook.com+intext%3A%22375291234567%22

\tURL: https://www.google.com/search?q=site%3Atwitter.com+intext%3A%22375291234567%22
Disposable providers:
\tURL: https://www.google.com/search?q=site%3Ahs3x.com+intext%3A%22375291234567%22
Reputation:
\tURL: https://www.google.com/search?q=site%3Awhosenumber.info+intext%3A%22375291234567%22
Results for local
Raw local: 80291234567
Local: 8 029 123-45-67
E164: +375291234567
Country: BY
2 scanner(s) succeeded
"""
    lines = summarize_phoneinfoga(raw, "+375291234567")
    joined = "\n".join(lines)
    # категории на русском, без простыни английских заголовков
    assert "Соцсети" in joined
    assert "Одноразовые" in joined
    assert "Репутация" in joined
    # чистые короткие ссылки вместо огромных URL
    assert "facebook.com" in joined
    assert "twitter.com" in joined
    assert "hs3x.com" in joined
    assert "whosenumber.info" in joined
    # локальная информация и итог
    assert "Страна: <code>BY</code>" in joined
    assert "Местный формат" in joined
    assert "Сканеров выполнено: 2" in joined
    # длинные URL спрятаны в href, виден только домен
    assert "facebook.com" in joined
    assert not any(ln.startswith("https://") for ln in lines)
    assert len(lines) <= 60


def test_link_domain():
    assert _link_domain("https://www.google.com/search?q=site%3Afacebook.com+intext%3A123") == "facebook.com"
    assert _link_domain("https://vk.com/foo") == "vk.com"
    assert _link_domain("https://www.google.com/search?q=intitle%3Ax") == "google.com"