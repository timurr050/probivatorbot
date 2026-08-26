"""Конструкторы клавиатур (inline-кнопки)."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.username_service import snscrape_supported
from bot.utils.validators import (
    EMAIL_FORMAT_HINT,
    PHONE_FORMAT_HINT,
    USERNAME_FORMAT_HINT,
)

CATEGORY_BUTTONS = {
    "phone": ("📱 Телефон", "cat:phone"),
    "username": ("🧑‍💻 Никнейм", "cat:username"),
    "email": ("📧 Email", "cat:email"),
    "photo": ("🖼 Фото и Видео", "cat:photo"),
    "google": ("🔮 Google (GHunt)", "cat:google"),
}

TOOLS = {
    "phone": [
        ("all", "🚀 Всё сразу (авто)"),
        ("reg", "🪪 Аккаунты в сервисах"),
        ("ph", "📇 phonenumbers"),
        ("pinf", "🔍 PhoneInfoga"),
        ("tg", "✈️ Telegram"),
        ("ig", "🌐 ignorant"),
    ],
    "username": [
        ("all", "🚀 Всё сразу (авто)"),
        ("maigret", "🕵️ Maigret (3000+ сайтов)"),
        ("sherlock", "🕵️ Sherlock"),
        ("ss", "🕸 socialscan"),
        ("snscrape", "📰 snscrape"),
        ("tw", "🐦 Twitter (twscrape)"),
        ("tg", "✈️ Telegram"),
    ],
    "email": [
        ("all", "🚀 Всё сразу (авто)"),
        ("reg", "🪪 Аккаунты в сервисах"),
        ("holehe", "🔎 holehe"),
        ("h8mail", "💥 h8mail"),
        ("ss", "🕸 socialscan"),
        ("ghunt", "🔮 GHunt"),
    ],
    "photo": [("all", "🖼 Извлечь EXIF и метаданные видео")],
    "google": [("all", "🔮 Проверить email")],
}

CATEGORY_PROMPT_HINTS = {
    "phone": "Отправьте телефонный номер",
    "username": "Отправьте никнейм",
    "email": "Отправьте email",
    "photo": "Отправьте изображение или видео",
    "google": "Отправьте email для Google-разведки",
}

CATEGORY_FORMATS = {
    "phone": PHONE_FORMAT_HINT,
    "username": USERNAME_FORMAT_HINT,
    "email": EMAIL_FORMAT_HINT,
    "photo": "Фото/видео (JPG/PNG/TIFF/HEIC/MP4/MOV)",
    "google": EMAIL_FORMAT_HINT,
}


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📱 Телефон", callback_data="cat:phone")
    kb.button(text="🧑‍💻 Никнейм", callback_data="cat:username")
    kb.button(text="📧 Email", callback_data="cat:email")
    kb.button(text="🖼 Фото / EXIF", callback_data="cat:photo")
    kb.button(text="🔮 Google (GHunt)", callback_data="cat:google")
    kb.button(text="🔑 Ключи API", callback_data="cmd:keys")
    kb.button(text="📐 Форматы ввода", callback_data="cmd:formats")
    kb.button(text="❓ Помощь", callback_data="cmd:help")
    kb.adjust(2, 2, 2, 2)
    return kb.as_markup()


def tools_menu(category: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for tool_key, label in TOOLS.get(category, [("all", "🚀 Всё сразу")]):
        if tool_key == "snscrape" and not snscrape_supported():
            label = f"{label} 🚫"
        kb.button(text=label, callback_data=f"tool:{category}:{tool_key}")
    kb.button(text="⬅️ Назад", callback_data="cmd:menu")
    kb.adjust(1)
    return kb.as_markup()


def engine_menu(category: str) -> InlineKeyboardMarkup:
    """Меню после выбора категории: автопробив по умолчанию + выбор движка."""
    kb = InlineKeyboardBuilder()
    kb.button(text="⚙️ Выбрать движок", callback_data=f"toolmenu:{category}")
    kb.button(text="🏠 Главное меню", callback_data="cmd:menu")
    kb.adjust(2)
    return kb.as_markup()


def after_result_menu(category: str, tool: str) -> InlineKeyboardMarkup:
    """Кнопки после отчёта: повторить (по той же цели, без ввода), ТГ-поиск, ключи."""
    kb = InlineKeyboardBuilder()
    if category in ("phone", "username", "email"):
        kb.button(text="🔄 Повторить (все движки)", callback_data=f"retool:{category}:all")
        if category == "username":
            kb.button(text="✈️ Искать аккаунт в ТГ", callback_data="retool:username:tg")
    kb.button(text="🔑 Ключи API", callback_data="cmd:keys")
    kb.button(text="⬅️ Меню движков", callback_data=f"cat:{category}")
    kb.button(text="🏠 Главное меню", callback_data="cmd:menu")
    kb.adjust(1, 1, 2)
    return kb.as_markup()


def simple_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Главное меню", callback_data="cmd:menu")
    kb.adjust(1)
    return kb.as_markup()