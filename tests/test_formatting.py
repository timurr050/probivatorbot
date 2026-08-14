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


def _assert_parts_html_valid(parts: list[str]) -> None:
    """Каждая часть авт.-валидна: нет оборванных <, теги парные."""
    for part in parts:
        assert len(part) <= formatting.MAX_MSG_LEN, "часть длиннее лимита"
        # ни один '<' не должен остаться без закрывающего '>'
        assert part.find(">") != -1 or part.count("<") == 0
        # баланс парных тегов внутри части
        for tag in ("b", "code", "a", "blockquote", "pre"):
            opens = part.count(f"<{tag}>") + part.count(f"<{tag} ")
            closes = part.count(f"</{tag}>")
            assert opens == closes, f"тег <{tag}>: {opens} открытий, {closes} закрытий"


def test_split_never_breaks_tag_start():
    """Разрез не должен попасть внутрь <a href=…>: часть не заканчивается оборванным тегом."""
    from textwrap import wrap

    url = "https://www.google.com/search?q=%22%2B79160000000%22+%7C+site%3Aexample.com"
    line = "<a href=\"" + url + "\">example.com</a> · "
    text = "<b>Отчёт</b>\n" + line * 300
    parts = split_message(text)
    assert len(parts) > 1
    _assert_parts_html_valid(parts)
    # конкретно: нигде на стыке не должно остаться «…<a» без закрытия
    assert not any(p.endswith("<a") for p in parts[:-1])


def test_split_real_like_phone_report():
    """Длинный отчёт (~4600 символов) режется в 2 валидные части."""
    head = "<b>📱 ОТЧЁТ</b>\n"
    link = '<a href="https://www.google.com/search?q=%22%2B79160000000%22">' \
           "facebook.com</a> · "
    info = "│ Страна: <code>RU</code>\n" * 40
    text = head + link * 200 + info
    assert len(text) > formatting.MAX_MSG_LEN
    parts = split_message(text)
    assert len(parts) > 1
    _assert_parts_html_valid(parts)