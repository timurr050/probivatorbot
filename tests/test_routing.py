"""Реальные роутинговые тесты: dispatch через Dispatcher.feed_update.

Ловят баг «общий обработчик перехватывает события раньше FSM-хендлеров»,
из-за которого бот молчал на фото и отвечал «Используйте меню» на телефон.
Сеть и Telegram API не трогаем: Bot работает на фейковой сессии.
"""
from __future__ import annotations

import datetime
from collections.abc import AsyncGenerator

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import DeleteMessage, EditMessageText, GetFile, GetMe, SendMessage, TelegramMethod
from aiogram.types import Chat, Document, File, Message, Update, User

from bot.handlers import register
from bot.states import ProbivStates

CHAT_ID = 42


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []

    async def close(self) -> None:
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.calls.append(method)
        name = type(method).__name__
        if name in {"SendMessage", "EditMessageText"}:
            return Message.model_validate(
                {
                    "message_id": 1,
                    "date": datetime.datetime.now(),
                    "chat": {"id": CHAT_ID, "type": "private"},
                    "text": getattr(method, "text", None),
                },
                context={"bot": bot},
            )
        if name == "GetMe":
            return User(id=bot.id, is_bot=True, first_name="TestBot")
        if name == "GetFile":
            return File(file_id="f", file_unique_id="u", file_path="fake.bin")
        if name == "DeleteMessage":
            return True
        return True

    async def stream_content(
        self,
        url: str,
        headers: dict | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        yield b"not-a-real-media-file"


BOT: Bot = Bot(token="1234567890:AA-test-token", session=FakeSession())
STORAGE = MemoryStorage()
DP: Dispatcher = Dispatcher(storage=STORAGE)
register(DP)


def _msg(**fields) -> Message:
    return Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=Chat(id=CHAT_ID, type="private"),
        from_user=User(id=CHAT_ID, is_bot=False, first_name="Test"),
        **fields,
    )


def _doc_movie(name: str) -> Message:
    return _msg(
        document=Document(file_id="f2", file_unique_id="u2", file_name=name, mime_type="video/mp4"),
    )


def _sent_texts(session: FakeSession) -> list[str]:
    return [
        getattr(m, "text", "") or ""
        for m in session.calls
        if isinstance(m, (SendMessage, EditMessageText)) and getattr(m, "text", None)
    ]


async def _reset_fsm() -> None:
    key = StorageKey(bot_id=BOT.id, chat_id=CHAT_ID, user_id=CHAT_ID)
    await STORAGE.set_state(key, None)
    await STORAGE.update_data(key, {})


async def _dispatch(state, msg: Message) -> FakeSession:
    await _reset_fsm()
    key = StorageKey(bot_id=BOT.id, chat_id=CHAT_ID, user_id=CHAT_ID)
    await STORAGE.set_state(key, state)
    await STORAGE.update_data(key, {"tool": "all", "category": "phone"})

    session: FakeSession = BOT.session
    session.calls.clear()
    await DP.feed_update(BOT, Update(update_id=1, message=msg))
    return session


@pytest.mark.asyncio
async def test_phone_input_not_stolen_by_fallback():
    """Текст в состоянии PHONE должен уйти в phone_input, а не в on_unexpected_text."""
    session = await _dispatch(ProbivStates.PHONE, _msg(text="+999bad"))
    joined = "\n".join(_sent_texts(session))
    assert joined, "бот вообще ничего не отправил"
    assert "Используйте меню" not in joined, "fallback перехватил ввод телефона!"
    assert "Ищем" in joined or "❌" in joined, "phone_input не обработал номер"


@pytest.mark.asyncio
async def test_photo_document_reaches_photo_handler():
    """Документ-фото в состоянии PHOTO должен дойти до photo_input."""
    session = await _dispatch(
        ProbivStates.PHOTO,
        _msg(document=Document(file_id="f1", file_unique_id="u1", file_name="pic.jpg", mime_type="image/jpeg")),
    )
    joined = "\n".join(_sent_texts(session))
    assert "ОТЧЁТ ПО ИЗОБРАЖЕНИЮ" in joined, "обработчик фото не запустился"


@pytest.mark.asyncio
async def test_video_document_reaches_photo_handler():
    """Видео-документ в состоянии PHOTO должен уйти в video_service, а не в fallback."""
    session = await _dispatch(ProbivStates.PHOTO, _doc_movie("clip.mp4"))
    joined = "\n".join(_sent_texts(session))
    assert "Используйте меню" not in joined
    assert "ОТЧЁТ ПО ВИДЕО" in joined or "MP4" in joined, "обработчик видео не запустился"


@pytest.mark.asyncio
async def test_photo_outside_state_gets_hint():
    """Фото без состояния PHOTO раньше молчало — теперь должен быть ответ-подсказка."""
    await _reset_fsm()
    session: FakeSession = BOT.session
    session.calls.clear()
    await DP.feed_update(
        BOT,
        Update(
            update_id=1,
            message=_msg(document=Document(file_id="f9", file_unique_id="u9", file_name="x.jpg", mime_type="image/jpeg")),
        ),
    )
    joined = "\n".join(_sent_texts(session))
    assert joined, "бот проигнорировал фото вне состояния PHOTO"
    assert "просканировать" in joined or "Извлечь" in joined


@pytest.mark.asyncio
async def test_unexpected_text_in_menu_gets_hint():
    """Вне FSM-состояния обычный текст должен получать подсказку меню."""
    await _reset_fsm()
    session: FakeSession = BOT.session
    session.calls.clear()
    await DP.feed_update(BOT, Update(update_id=1, message=_msg(text="привет")))
    joined = "\n".join(_sent_texts(session))
    assert "Используйте меню" in joined, "fallback-подсказка не сработала"


@pytest.mark.asyncio
async def test_handler_error_replies_instead_of_silence():
    """Упавший хендлер должен отвечать сообщением об ошибке, а не молчать.

    Раньше aiogram молча логировал исключение — пользователь видел тишину.
    Глобальный errors-хендлер обязан отправлять текст с ошибкой.
    """
    from bot.handlers import errors as errors_module

    async def _boom(message: Message) -> None:
        raise RuntimeError("boom")

    dp = Dispatcher(storage=MemoryStorage())
    boom_router = Router(name="boom")
    boom_router.message()(_boom)
    dp.include_router(boom_router)
    dp.errors.register(errors_module.on_error)

    bot = Bot(token="1234567890:AA-test-token", session=FakeSession())
    dp.startup.register(lambda: None)

    try:
        session: FakeSession = bot.session
        session.calls.clear()
        await dp.feed_update(bot, Update(update_id=1, message=_msg(text="x")))
        joined = "\n".join(_sent_texts(session))
        assert joined, "бот проигнорировал упавший хендлер (молчание)"
        assert "Что-то пошло не так" in joined
        assert "RuntimeError" in joined
    finally:
        await bot.session.close()