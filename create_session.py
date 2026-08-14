"""
Разовый скрипт: создаёт авторизованную сессию Telethon для бота.

Как использовать:
    1) Впишите в .env:  TG_API_ID и TG_API_HASH (https://my.telegram.org)
    2) Запустите:      .venv\\Scripts\\python.exe create_session.py
    3) Введите номер телефона аккаунта и код подтверждения.
    4) Скрипт выведет готовую строку для TG_ACCOUNTS — вставьте её в .env.
"""
from __future__ import annotations

import asyncio
import json

from telethon import TelegramClient

from bot.config import SETTINGS
from bot.services.base import session_path


async def main() -> None:
    if not SETTINGS.is_telethon_ready:
        print("❌ Сначала задайте TG_API_ID и TG_API_HASH в .env (https://my.telegram.org/apps)")
        return

    phone = input("Телефон аккаунта в формате +375...: ").strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    session_name = "session_" + phone.strip("+")
    client = TelegramClient(
        session_path(session_name),
        api_id=SETTINGS.tg_api_id,
        api_hash=SETTINGS.tg_api_hash,
    )

    try:
        await client.start(phone=phone)
        me = await client.get_me()
        print("✅ Авторизован:", me.phone, "|", (me.first_name or ""))
        pair = json.dumps({phone: session_name}, ensure_ascii=False)
        print("→ Добавьте в .env строку:")
        print(f"TG_ACCOUNTS={pair}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())