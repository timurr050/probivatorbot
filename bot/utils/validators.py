"""
Валидация пользовательского ввода.

Каждая функция возвращает нормализованное значение или бросает
`ValitationError` с человекочитаемым описанием ожидаемого формата.
"""
from __future__ import annotations

import re

import phonenumbers

from bot.exceptions import ValidationError

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
_TG_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")

PHONE_FORMAT_HINT = (
    "Международный формат: <code>+375291234567</code>\n"
    "или без плюса: <code>79261234567</code>, <code>80291234567</code>\n"
    "или вольный: <code>8 029 123-45-67</code>, <code>+7 900 123-45-67</code>"
)
USERNAME_FORMAT_HINT = (
    "Только латинские буквы, цифры и символ <code>_</code> (без <code>@</code>)"
)
TG_USERNAME_FORMAT_HINT = (
    "Telegram-юзернейм без <code>@</code> (5–32 символа: буквы/цифры/нижнее подчёркивание)"
)
EMAIL_FORMAT_HINT = "Формат: <code>name@domain.com</code>"


def normalize_phone(raw: str) -> str:
    """Приводит телефон к E.164 формату (+7..., +375...)."""
    text = raw.strip()
    if not text:
        raise ValidationError("Пустой номер", PHONE_FORMAT_HINT)

    cleaned = re.sub(r"[^\d+]", "", text)
    raw_digits = cleaned  # исходный вид для уточнения регионом

    # Если нет «+», подставляем подходящий код страны:
    #   «8…» / «7…» (11 цифр) — РФ, «375…» (12 цифр) — Беларусь
    if not cleaned.startswith("+"):
        if len(cleaned) == 11 and cleaned[0] in "78":
            cleaned = "+7" + cleaned[1:]
        elif len(cleaned) == 12 and cleaned.startswith("375"):
            cleaned = "+375" + cleaned[3:]

    try:
        number = phonenumbers.parse(cleaned, None)
    except phonenumbers.NumberParseException as exc:
        raise ValidationError(f"Не получилось разобрать номер: {exc}", PHONE_FORMAT_HINT) from exc

    # Локальные формы типа «8 029 123-45-67» — уточняем регионом СНГ.
    if not phonenumbers.is_valid_number(number):
        for region in ("RU", "BY", "KZ", "UA"):
            try:
                candidate = phonenumbers.parse(raw_digits, region)
            except phonenumbers.NumberParseException:
                continue
            if phonenumbers.is_valid_number(candidate):
                number = candidate
                break

    if not phonenumbers.is_possible_number(number):
        raise ValidationError("Номер технически невозможен", PHONE_FORMAT_HINT)
    if not phonenumbers.is_valid_number(number):
        raise ValidationError("Номер не валиден (не существует)", PHONE_FORMAT_HINT)

    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def normalize_username(raw: str) -> str:
    """Нормализует никнейм (без @, в нижнем регистре)."""
    text = raw.strip().lstrip("@")
    if not text:
        raise ValidationError("Пустой никнейм", USERNAME_FORMAT_HINT)
    if "\n" in text or " " in text:
        raise ValidationError("Никнейм не должен содержать пробелы/переводы строк", USERNAME_FORMAT_HINT)
    if not _USERNAME_RE.match(text):
        raise ValidationError(
            f"«{text[:20]}» не похож на никнейм",
            USERNAME_FORMAT_HINT,
        )
    return text.lower()


def normalize_tg_username(raw: str) -> str:
    """Нормализует Telegram-юзернейм (без @)."""
    text = raw.strip().lstrip("@")
    if not _TG_USERNAME_RE.match(text):
        raise ValidationError(f"«{text[:20]}» не похож на Telegram-юзернейм", TG_USERNAME_FORMAT_HINT)
    return text.lower()


def normalize_email(raw: str) -> str:
    """Валидирует email, приводит к нижнему регистру."""
    text = raw.strip().lower()
    if not _EMAIL_RE.match(text):
        raise ValidationError(f"«{raw.strip()[:30]}» не похож на email", EMAIL_FORMAT_HINT)
    return text