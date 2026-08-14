"""
Центральная конфигурация бота.

Все значения читаются из переменных окружения / файла `.env`.
Файл `.env` создаётся из `.env.example` и НЕ коммитится в гит.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Путь к проекту (родитель папки bot/)
BASE_DIR = Path(__file__).resolve().parent.parent

# Загружаем .env если он есть
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    """Неизменяемая конфигурация бота."""

    bot_token: str
    admin_ids: tuple[int, ...] = ()
    restrict_to_admins: bool = False
    cli_encoding: str = "utf-8"
    cli_timeout: int = 90

    # PhoneInfoga
    phoneinfoga_path: Optional[str] = None
    phoneinfoga_api_key: Optional[str] = None

    # Telethon
    tg_api_id: Optional[int] = None
    tg_api_hash: Optional[str] = None
    tg_accounts: dict[str, str] = field(default_factory=dict)

    # GHunt
    ghunt_config_path: Optional[str] = None

    # Sherlock
    sherlock_officially_verified: bool = False

    # Webhook (вместо long-polling) — нужен для нескольких реплик
    webhook_domain: Optional[str] = None
    webhook_path: Optional[str] = None
    webhook_port: int = 8080
    webhook_secret: Optional[str] = None

    @property
    def is_telethon_ready(self) -> bool:
        return bool(self.tg_api_id and self.tg_api_hash)


def _parse_int_list(raw: str | None) -> tuple[int, ...]:
    if not raw:
        return ()
    result: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            result.append(int(part))
    return tuple(result)


def _parse_json_dict(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _env_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_settings() -> Settings:
    """Собирает конфигурацию из переменных окружения."""
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN не задан. Скопируйте .env.example в .env и вставьте токен от @BotFather."
        )

    return Settings(
        bot_token=token,
        admin_ids=_parse_int_list(os.getenv("ADMIN_IDS")),
        restrict_to_admins=_env_bool(os.getenv("RESTRICT_TO_ADMINS")),
        cli_encoding=os.getenv("CLI_ENCODING", "utf-8"),
        cli_timeout=_env_int(os.getenv("CLI_TIMEOUT"), 90),
        phoneinfoga_path=os.getenv("PHONEINFOGA_PATH") or None,
        phoneinfoga_api_key=os.getenv("PHONEINFOGA_API_KEY") or None,
        tg_api_id=_env_int(os.getenv("TG_API_ID"), 0) or None,
        tg_api_hash=os.getenv("TG_API_HASH") or None,
        tg_accounts=_parse_json_dict(os.getenv("TG_ACCOUNTS")),
        ghunt_config_path=os.getenv("GHUNT_CONFIG_PATH") or None,
        sherlock_officially_verified=_env_bool(
            os.getenv("SHERLOCK_OFFICIALLY_VERIFIED")
        ),
        webhook_domain=os.getenv("WEBHOOK_DOMAIN") or None,
        webhook_path=os.getenv("WEBHOOK_PATH") or None,
        webhook_port=_env_int(os.getenv("WEBHOOK_PORT"), 8080),
        webhook_secret=os.getenv("WEBHOOK_SECRET") or None,
    )


# Единая точка доступа к настройкам для всех модулей
SETTINGS: Settings = load_settings()