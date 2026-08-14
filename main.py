"""Точка входа ProbivBot.

Режимы запуска:
    python main.py                        # long-polling (по умолчанию)
    WEBHOOK_DOMAIN=https://bot.example.com python main.py   # webhook (для реплик/авто-масштабирования)

Запуск:
    python main.py
"""
from __future__ import annotations

import logging
from pathlib import Path

from bot.config import SETTINGS
from bot.db import DB
from bot.handlers import register
from bot.loader import BOT, DP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("probivbot")

# папка для сессий Telethon и временных файлов
DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)
(DATA_DIR / "telegram_sessions").mkdir(exist_ok=True)


def main() -> None:
    register(DP)

    async def _startup() -> None:
        me = await BOT.get_me()
        logger.info("ProbivBot запущен как @%s (id=%s)", me.username, me.id)

    DP.startup.register(_startup)

    async def _shutdown() -> None:
        DB.close()
        await BOT.session.close()

    DP.shutdown.register(_shutdown)

    try:
        if SETTINGS.webhook_domain:
            _run_webhook()
        else:
            _start_health_thread(SETTINGS.webhook_port)
            DP.run_polling(BOT, skip_updates=True, allowed_updates=["message", "callback_query"])
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановка бота…")


def _start_health_thread(port: int) -> None:
    """Фоновый HTTP-сервер /health в polling-режиме (для docker healthcheck).

    В webhook-режиме /health отдаёт сам webhook-сервер, здесь поднимаем его отдельно.
    """
    from threading import Thread

    def _run() -> None:
        import asyncio

        from aiohttp import web

        app = web.Application()
        app.router.add_get("/health", _health_handler)
        asyncio.run(web._run_app(app, host="0.0.0.0", port=port, print=lambda *_: None))

    thread = Thread(target=_run, name="health", daemon=True)
    thread.start()
    logger.info("Health-сервер: http://0.0.0.0:%s/health", port)


def _run_webhook() -> None:
    """Webhook-режим: принимает обновления по HTTP вместо long-polling.

    Нужен для запуска нескольких реплик (`docker compose up --scale`) — Telegram
    позволяет только одному long-polling клиенту одновременно слушать бота (409).
    """
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    path = SETTINGS.webhook_path or f"/webhook/{BOT.id}"

    app = web.Application()
    app.router.add_get("/health", _health_handler)

    webhook_handler = SimpleRequestHandler(
        dispatcher=DP,
        bot=BOT,
        secret_token=SETTINGS.webhook_secret,
    )
    webhook_handler.register(app, path=path)
    setup_application(app, DP, bot=BOT)

    async def _set_webhook(_app: web.Application) -> None:
        url = f"{SETTINGS.webhook_domain}{path}"
        await BOT.set_webhook(
            url=url,
            allowed_updates=["message", "callback_query"],
            secret_token=SETTINGS.webhook_secret,
        )
        logger.info("Webhook установлен на %s", url)

    app.on_startup.append(_set_webhook)

    logger.info(
        "Webhook-режим: http://0.0.0.0:%s%s",
        SETTINGS.webhook_port,
        path,
    )
    web.run_app(app, host="0.0.0.0", port=SETTINGS.webhook_port)


async def _health_handler(_request) -> "web.Response":
    """GET /health — проверка живости для docker healthcheck."""
    from aiohttp import web

    return web.json_response({"status": "ok"})


if __name__ == "__main__":
    main()