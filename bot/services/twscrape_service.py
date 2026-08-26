"""
Twitter/X: профиль и последние твиты по нику через twscrape.

twscrape требует хотя бы один аккаунт Twitter в пуле (обход API/X).
Добавить: <code>python -m twscrape add_accounts</code> (интерактивно, логин/пароль
приложения-подопытного). Без аккаунта движок честно сообщает об этом и не роняет отчёт.
"""
from __future__ import annotations

import importlib.util

from bot.exceptions import ToolNotConfigured


def _available() -> bool:
    try:
        return importlib.util.find_spec("twscrape") is not None
    except Exception:  # noqa: BLE001
        return False


async def run_twscrape(username: str, limit: int = 10) -> dict:
    """Ищет профиль и последние твиты username в Twitter/X через twscrape."""
    if not _available():
        raise ToolNotConfigured(
            "twscrape не установлен:\n<code>pip install twscrape</code>"
        )

    from twscrape import API

    api = API()
    try:
        accounts = await api.pool.get_all()
    except Exception:  # noqa: BLE001
        accounts = []
    if not accounts:
        raise ToolNotConfigured(
            "twscrape: нет аккаунтов Twitter.\n"
            "Добавьте аккаунт: <code>python -m twscrape add_accounts</code>"
        )

    try:
        user = await api.user_by_login(username)
    except Exception as exc:  # noqa: BLE001
        raise ToolNotConfigured(f"twscrape: {type(exc).__name__}: {str(exc)[:120]}")

    if user is None:
        return {"found": False, "tweets": []}

    tweets: list[str] = []
    try:
        async for t in api.user_tweets(username, limit=limit):
            text = getattr(t, "text", None) or getattr(t, "rawContent", "")
            if text:
                tweets.append(str(text))
            if len(tweets) >= limit:
                break
    except Exception:  # noqa: BLE001 — твиты не критичны, профиль уже есть
        pass

    return {
        "found": True,
        "id": getattr(user, "id", None),
        "name": getattr(user, "displayname", None) or getattr(user, "name", None),
        "followers": getattr(user, "followers_count", None),
        "tweets": tweets[:limit],
    }


def format_twscrape_section(result: dict) -> list[str]:
    """Секция «🐦 Twitter/X» для отчёта."""
    if not result:
        return []
    lines: list[str] = []
    add = lines.append
    if result.get("found") is True:
        add("<b>🐦 Twitter/X (twscrape)</b>")
        if result.get("name"):
            add(f"│ Имя: <blockquote>{str(result['name'])}</blockquote>")
        if result.get("followers") is not None:
            add(f"│ Подписчиков: <code>{result['followers']}</code>")
        if result.get("id") is not None:
            add(f"│ ID: <code>{result['id']}</code>")
        for tw in result.get("tweets") or []:
            add(f"│ 💬 {str(tw)[:400]}")
    else:
        add("<b>🐦 Twitter/X (twscrape)</b>")
        add("│ Профиль не найден")
    return lines
