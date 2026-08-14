"""Обработка изображений (EXIF) и видео (метаданные MP4/MOV) в состоянии PHOTO."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.db import DB
from bot.exceptions import ProbivError
from bot.filters import IsAdmin
from bot.keyboards import after_result_menu
from bot.services.photo_service import extract_photo, format_photo_report
from bot.services.video_service import extract_video, format_video_report
from bot.states import ProbivStates
from bot.texts import STATUS_TEXT, error_text
from bot.utils.filehelpers import (
    _ALLOWED_VIDEO_SUFFIXES,
    download_document,
    download_photo,
    download_video,
    safe_unlink,
)
from bot.utils.formatting import split_message

router = Router(name="photo")

PHOTO_HINT = (
    "🖼 Отправьте изображение (фото или документ) или 🎬 видео.\n"
    "Рекомендуется <b>Документ/файл</b> — так сохраняется максимум метаданных."
)


@router.message(
    IsAdmin(),
    F.content_type.in_({"photo", "document", "video"}),
    ProbivStates.PHOTO,
)
async def photo_input(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id if message.from_user else 0
    data = await state.get_data()
    tool = data.get("tool", "all")
    target = "медиафайл"
    status = await message.reply(STATUS_TEXT.format(target=target, tool="EXIF/видео-анализ"))

    path = None
    try:
        kind, path = await _download_media(message)
        target = path.name if path else target

        if kind == "video":
            report = extract_video(path)
            text = format_video_report(report, path)
        else:
            report = extract_photo(path)
            text = format_photo_report(report, path)
    except ProbivError as exc:
        await status.edit_text(error_text(str(exc)))
        _log(user_id, "media", tool, target, "error", str(exc))
        if path:
            safe_unlink(path)
        return
    except Exception as exc:  # noqa: BLE001
        await status.edit_text(error_text(f"{type(exc).__name__}: {str(exc)}"))
        _log(user_id, "media", tool, target, "error", f"{type(exc).__name__}: {str(exc)}")
        if path:
            safe_unlink(path)
        return

    if path:
        safe_unlink(path)

    await status.delete()
    parts = split_message(text)
    for i, part in enumerate(parts):
        if i == 0:
            await message.reply(part)
        else:
            await message.answer(part)
    await message.answer(
        "✔️ Готово. Метаданные извлечены.",
        reply_markup=after_result_menu("photo", tool),
    )
    _log(user_id, "media", tool, target, "ok", report=text)


async def _download_media(message: Message) -> tuple[str, object]:
    """Скачивает медиа и возвращает (тип, путь). type: 'photo'|'video'."""
    if message.video:
        return "video", await download_video(message.bot, message)

    suffix = ""
    if message.document:
        name = message.document.file_name or ""
        suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""

    if suffix in _ALLOWED_VIDEO_SUFFIXES:
        return "video", await download_document(message.bot, message, allow_any=True)
    if message.document:
        return "photo", await download_document(message.bot, message, allow_any=True)
    return "photo", await download_photo(message.bot, message)


@router.message(IsAdmin(), F.content_type.not_in({"photo", "document", "video"}), ProbivStates.PHOTO)
async def photo_wrong_input(message: Message) -> None:
    await message.reply(PHOTO_HINT)


def _log(user_id: int, category: str, tool: str, target: str,
         status: str, error: str | None = None, report: str | None = None) -> None:
    try:
        DB.log_search(user_id, category, tool, target, status, error=error, report=report)
    except Exception:  # noqa: BLE001
        pass