"""Форматирование вывода в HTML (Bot API) + санитизация строк."""
from __future__ import annotations

from html import escape

MAX_MSG_LEN = 4096


def esc(text: object) -> str:
    """Экранирует текст для HTML-разметки Telegram."""
    return escape(str(text), quote=False)


def h(text: object) -> str:
    """Короткий алиас для esc()."""
    return esc(text)


def block(text: str, emoji: str | None = None) -> str:
    """Оборачивает текст в pre-блок (моноширинный, как цитата кода)."""
    body = esc(text)
    return f"<pre>{body}</pre>" if not emoji else f"{emoji}\n<pre>{body}</pre>"


def split_message(text: str, max_len: int = MAX_MSG_LEN) -> list[str]:
    """Режет длинный текст на части.

    Разрез всегда по пробелу/переносу строки ВНЕ HTML-тега, поэтому части
    валидны по отдельности (каждая ≤ max_len символов).
    """
    if len(text) <= max_len:
        return [text]

    parts: list[str] = []
    start = 0
    n = len(text)
    i = 0
    in_tag = False
    while i < n:
        ch = text[i]
        if ch == "<":
            in_tag = True
        elif ch == ">":
            in_tag = False

        if (i - start) >= max_len and not in_tag:
            # отступаем до последнего пробела/переноса (не внутри тега)
            j = i
            while j > start + 1 and text[j] not in (" ", "\n"):
                j -= 1
            if j <= start:
                j = i
            parts.append(text[start:j])
            start = j
            i = j
            continue
        i += 1

    if start < n:
        parts.append(text[start:])
    return parts


def section(title: str, body: str, collapse: bool = True) -> str:
    """Секция для многострочного отчёта."""
    return f"<b>▫ {esc(title)}</b>\n{body}"


def kv(key: str, value: object, codeValue: bool = True) -> str:
    """Строка «ключ: значение» для отчёта."""
    val = esc(value)
    if codeValue:
        val = f"<code>{val}</code>"
    return f"<b>{esc(key)}:</b> {val}"