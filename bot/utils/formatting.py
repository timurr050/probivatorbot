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

    Фикс: раньше при отступах назад выбирался последний пробел БЕЗ проверки,
    что он не внутри тега, — разрез попадал в `<a href=...>` и Telegram
    отвечал "Unclosed start tag".
    """
    if len(text) <= max_len:
        return [text]

    def inside_tag(i: int) -> bool:
        last_open = text.rfind("<", 0, i + 1)
        if last_open == -1:
            return False
        close = text.find(">", last_open)
        return close == -1 or close >= i

    # безопасные точки разреза: сразу ПОСЛЕ пробела/переноса вне HTML-тега
    safe: list[int] = []
    in_tag = False
    for i, ch in enumerate(text):
        if ch == "<":
            in_tag = True
        elif ch == ">":
            in_tag = False
        elif not in_tag and ch in (" ", "\n"):
            safe.append(i + 1)

    parts: list[str] = []
    start = 0
    n = len(text)
    while n - start > max_len:
        limit = start + max_len
        cut = start
        for pos in safe:
            if start < pos <= limit:
                cut = pos
        if cut <= start:
            # безопасного разрыва нет — режем принудительно, но не внутри тега
            cut = limit
            while cut < n and inside_tag(cut):
                cut += 1
        parts.append(text[start:cut])
        start = cut
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