"""Все пользовательские тексты бота в одном месте."""
from __future__ import annotations

from bot.utils.validators import EMAIL_FORMAT_HINT, PHONE_FORMAT_HINT, USERNAME_FORMAT_HINT

START_TEXT = (
    "Добро пожаловать в <b>ProbivBot</b> — агрегатор OSINT-инструментов. "
    "Бот работает только с данными из <i>открытых</i> источников.\n\n"
    "Выберите тип цели 👇"
)

HELP_TEXT = (
    "<b>ℹ️ Как пользоваться</b>\n"
    "1. Выберите категорию в меню.\n"
    "2. Выберите движок (или «Всё сразу»).\n"
    "3. Отправьте цель в правильном формате (см. «Форматы ввода»).\n"
    "4. Результат придёт ответом на ваше сообщение-запрос.\n\n"
    "Чем больше настроено в <code>.env</code> (Telethon, PhoneInfoga, GHunt), тем больше данных."
)

FORMATS_TEXT = (
    "📐 <b>Формат ввода</b>\n\n"
    f"<b>📱 Телефон</b>\n{PHONE_FORMAT_HINT}\n\n"
    f"<b>🧑‍💻 Никнейм</b>\n{USERNAME_FORMAT_HINT}\n\n"
    f"<b>📧 Email</b>\n{EMAIL_FORMAT_HINT}\n\n"
    "<b>🖼 Фото</b>\n"
    "— как <b>Документ</b> (файл) → EXIF сохраняется целиком (рекомендуется);\n"
    "— как <b>Фото</b> → Telegram сожмёт и вырежет EXIF.\n"
    "Поддерживаются: JPG/PNG/TIFF/BMP/HEIC/WebP/GIF.\n\n"
    "<b>✈️ Telegram-ник</b>\n"
    "Без «@», 5–32 символа, латиница/цифры/подчёркивание."
)

ABOUT_TEXT = (
    "🔎 <b>О боте</b>\n"
    "Движки: phonenumbers, PhoneInfoga, Telethon, socialscan, snscrape, "
    "exifread, sherlock, ignorant, holehe, h8mail, GHunt.\n\n"
    "⚠️ Используйте только в законных целях и только по вашим/разрешённым данным. "
    "Сбор данных о людях без согласия может нарушать закон (152-ФЗ и аналоги)."
)

NOT_ADMIN_TEXT = "⛔️ Доступ только для администраторов бота."

PROMPT_TEXT = "Отправьте цель в <b>{label}</b> формате:\n\n{hint}"

STATUS_TEXT = "🔍 Ищем по «{target}» через {tool}…"

DONE_MARK = "✅ Готово"
ERR_MARK = "❌ Ошибка"


def error_text(msg: str) -> str:
    return f"{ERR_MARK} <b>Что-то пошло не так</b>\n\n{str(msg)}"


def unknown_text() -> str:
    return "ℹ️ Нажми <b>«Меню»</b> и выберите категорию, либо /formats для подсказки."