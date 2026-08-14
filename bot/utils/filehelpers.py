"""Безопасная загрузка медиа из Telegram и работа с временными файлами.

Загрузка выполняется асинхронно (handlers работают в aioeventloop aiogram'а).
"""
from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional

from aiogram import Bot
from aiogram.types import Document, Message, PhotoSize

from bot.exceptions import ValidationError

_ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp", ".heic", ".heif"}
_ALLOWED_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".3gp", ".mts", ".m2ts", ".wmv"}


async def download_video(bot: Bot, message: Message) -> Path:
    """Скачивает видео из сообщения (сообщение типа video)."""
    video = message.video
    if video is None:
        raise ValidationError("В сообщении нет видео", "Пришлите видео файлом")
    suffix = f".{video.file_name.split('.')[-1]}" if video.file_name and "." in video.file_name else ".mp4"
    if suffix not in _ALLOWED_VIDEO_SUFFIXES:
        suffix = ".mp4"
    return await _download(bot, video.file_id, suffix=suffix)


async def download_photo(bot: Bot, message: Message) -> Path:
    """Скачивает самое большое фото из сообщения во временный файл."""
    if not message.photo:
        raise ValidationError("В сообщении нет фото", "Пришлите фото в сжатом виде")
    photo: PhotoSize = max(message.photo, key=lambda p: p.width * p.height)
    return await _download(bot, photo.file_id, suffix=".jpg")


async def download_document(bot: Bot, message: Message, allow_any: bool = False) -> Path:
    """Скачивает документ (оригинал файла) во временный файл.

    allow_any=False — проверяет, что расширение является известным форматом изображения.
    """
    doc: Optional[Document] = message.document
    if doc is None:
        raise ValidationError("В сообщении нет документа", "Отправьте файл в формате JPG/PNG/TIFF/HEIC")

    suffix = Path(doc.file_name or "file").suffix.lower()
    if not allow_any and suffix not in _ALLOWED_IMAGE_SUFFIXES and suffix not in _ALLOWED_VIDEO_SUFFIXES:
        raise ValidationError(
            f"Расширение «{suffix or 'нет'}» не похоже на изображение/видео",
            "Поддерживаются: "
            + ", ".join(sorted(_ALLOWED_IMAGE_SUFFIXES | _ALLOWED_VIDEO_SUFFIXES)),
        )

    return await _download(bot, doc.file_id, suffix=suffix or ".bin")


async def _download(bot: Bot, file_id: str, suffix: str) -> Path:
    tmp = NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()
    path = Path(tmp.name)
    try:
        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, destination=str(path))
    except Exception as exc:  # noqa: BLE001 — перехватываем любые сетевые ошибки
        safe_unlink(path)
        raise ValidationError(f"Не удалось скачать файл: {exc}") from exc
    return path


def safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass