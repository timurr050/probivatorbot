"""
Создание Telegram-сессий (Telethon) для поиска по нескольким аккаунтам.

Как пользоваться:
  1) В .env заполните TG_API_ID и TG_API_HASH (https://my.telegram.org/apps);
  2) Запустите:  python session_maker.py
  3) Введите номер (+7916...) и имя файла сессии (sess_1, sess_2, ...);
  4) Сессия сохранится в data/telegram_sessions/;
  5) Добавьте пару в .env:  TG_ACCOUNTS={"номер":"имя_файла"} (через запятую несколько).

Можно создать сколько угодно сессий — бот перебирает их по очереди.
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

API_ID = os.getenv("TG_API_ID", "").strip()
API_HASH = os.getenv("TG_API_HASH", "").strip()


def main() -> None:
    if not API_ID.isdigit() or not API_HASH:
        print("Ошибка: в .env заполните TG_API_ID (цифры) и TG_API_HASH.")
        print("Получить: https://my.telegram.org/apps")
        sys.exit(1)

    from bot.services.base import SESSIONS_DIR

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Папка сессий: {SESSIONS_DIR}")
    phone = input("Номер телефона (в формате +79161234567): ").strip()
    if not phone:
        print("Номер не введён.")
        sys.exit(1)

    existing = [p.stem for p in SESSIONS_DIR.glob("*.session")]
    default_name = f"sess_{len(existing) + 1}"
    name = input(f"Имя файла сессии (Enter = {default_name}): ").strip() or default_name

    from telethon import TelegramClient

    import asyncio

    async def make() -> None:
        client = TelegramClient(str(SESSIONS_DIR / name), int(API_ID), API_HASH)
        await client.start(phone=phone)  # запросит код подтверждения в Telegram
        me = await client.get_me()
        print(f"\nOK! Сессия «{name}» для @{me.username} сохранена.")
        print(f'Добавьте в .env:\nTG_ACCOUNTS={{{phone!r}: {name!r}}}')
        await client.disconnect()

    asyncio.run(make())


if __name__ == "__main__":
    main()
