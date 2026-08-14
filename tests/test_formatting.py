"""Тесты форматирования (HTML, split, экранирование)."""
from __future__ import annotations

from bot.utils import formatting
from bot.utils.formatting import block, esc, kv, section, split_message


def test_escapes_html():
    assert esc("<pre>") == "&lt;pre&gt;"
    assert esc("<b>x</b>") == "&lt;b&gt;x&lt;/b&gt;"


def test_block_wraps_code():
    text = block("a<b>&")
    assert text.startswith("<pre>")
    assert "&lt;b&gt;" in text


def test_kv_and_section():
    assert "<b>Ключ:</b> <code>значение</code>" == kv("Ключ", "значение")
    assert "<b>▫ Заголовок</b>" in section("Заголовок", "тело")


def test_split_short_message():
    text = "hello"
    assert split_message(text) == ["hello"]


def test_split_long_message_no_overflow():
    text = ("<b>Экран</b> " * 2000)  # длинный, ~13k символов
    parts = split_message(text)
    assert len(parts) > 1
    for part in parts:
        assert len(part) <= formatting.MAX_MSG_LEN
        # не разрываем начала тегов на стыках
        if part and part[-1:] in ("<",):
            assert False, "разрезали открывающий тег"


def test_split_html_tags_not_broken():
    # закрытые <code>…</code> должны остаться целыми в одном куске, если помещаются
    text = ("<code>" + "x" * 100 + "</code>")
    assert split_message(text) == [text]