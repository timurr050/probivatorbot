"""Единые точки входа: бот, диспетчер, FSM-хранилище."""
from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import SETTINGS

STORAGE = MemoryStorage()

BOT: Bot = Bot(
    token=SETTINGS.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

DP: Dispatcher = Dispatcher(storage=STORAGE)