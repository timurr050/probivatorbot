"""
Базовые помощники для сервисов: безопасный запуск CLI-инструментов.

Все CLI-вызовы выполняются в отдельном процессе с таймаутом,
декодируются с нужной кодировкой и оборачивают ошибки в типизированные исключения.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from bot.config import SETTINGS
from bot.exceptions import ExternalToolError, ServiceError, ToolNotConfigured, ToolTimeout

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
SESSIONS_DIR = DATA_DIR / "telegram_sessions"


def session_path(name: str) -> str:
    """Возвращает путь к файлу сессии Telethon внутри data/."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSIONS_DIR / name
    if not path.suffix:
        path = path.with_suffix(".session")
    return str(path)


def avatar_path() -> str:
    return str(DATA_DIR / "tg_avatar.jpg")


def which(tool: str) -> Path:
    """Ищет исполняемый файл в PATH или в Scripts активного venv."""
    path = shutil.which(tool)
    if path:
        return Path(path)

    # pip-консольные скрипты (sherlock, holehe, ...) лежат в .venv/Scripts
    venv_scripts = Path(sys.executable).resolve().parent
    candidate = venv_scripts / (tool + (".exe" if os.name == "nt" else ""))
    if candidate.exists():
        return candidate

    raise ToolNotConfigured(
        f"Инструмент «{tool}» не найден в PATH.\n"
        f"Установите его и попробуйте ещё раз."
    )


def ensure_binary(path: str | None, name: str) -> Path:
    """Проверяет, что бинарник существует (абсолютный путь или в PATH)."""
    if path:
        p = Path(path)
        if p.exists():
            return p
        raise ToolNotConfigured(
            f"Бинарник «{name}» не найден по пути: <code>{p}</code>\n"
            f"Проверьте PHONEINFOGA_PATH в .env"
        )
    return which(name)


def run_cli(args: Sequence[str], timeout: int | None = None) -> str:
    """Запускает CLI-команду, возвращает stdout+stderr.

    Бросает ToolTimeout / ExternalToolError / ServiceError.
    """
    timeout = timeout or SETTINGS.cli_timeout
    encoding = SETTINGS.cli_encoding
    try:
        proc = subprocess.run(  # noqa: S603
            list(args),
            capture_output=True,
            text=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ToolNotConfigured(f"Не удалось запустить: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolTimeout(
            f"Инструмент «{_name(args)}» не уложился в {timeout} сек"
        ) from exc

    out = (proc.stdout or b"") + (proc.stderr or b"")
    text = out.decode(encoding, errors="replace")

    if proc.returncode != 0:
        # некоторые инструменты пишут прогресс в stderr и падают на сайте,
        # но всё равно полезно вернуть то, что успели напечатать
        if not text.strip():
            raise ExternalToolError(
                f"«{_name(args)}» завершился с кодом {proc.returncode} без вывода"
            )
    return text


async def run_cli_async(args: Sequence[str], timeout: int | None = None,
                        env: dict | None = None) -> str:
    """Запускает CLI-команду асинхронно, гарантированно убивая процесс по таймауту.

    В отличие от `run_cli`, процесс при превышении таймаута завершается
    принудительно (`proc.kill()`), поэтому не оставляет «зомби» в системе
    и не блокирует событийный цикл после отмены. stdin закрыт (DEVNULL),
    чтобы интерактивные инструменты не висели в ожидании ввода.
    """
    timeout = timeout or SETTINGS.cli_timeout
    try:
        proc = await asyncio.create_subprocess_exec(
            *[str(a) for a in args],
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
    except FileNotFoundError as exc:
        raise ToolNotConfigured(f"Не удалось запустить: {args[0]}") from exc

    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass  # процесс не умер — не блокируемся дальше
        raise ToolTimeout(f"Инструмент «{_name(args)}» не уложился в {timeout} сек")

    text = raw.decode(SETTINGS.cli_encoding, errors="replace")
    if proc.returncode != 0 and not text.strip():
        raise ExternalToolError(
            f"«{_name(args)}» завершился с кодом {proc.returncode} без вывода"
        )
    return text


def _name(args: Sequence[str]) -> str:
    return args[0] if args else "?"