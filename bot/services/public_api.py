"""
Проверка никнеймов на публичных API БЕЗ ключей.

Что проверяется:
  * GitHub / GitLab / Reddit — официальные публичные API (JSON);
  * остальное — HTTP-страницы профилей (200 = профиль существует,
    404 = нет, прочие статусы = антибот/блок — честно помечаем «не удалось»).

Запросы идут через `curl_cffi` (подмена TLS-отпечатка Chrome), чтобы обходить
базовые антибот-экраны. API-ключи для этих проверок НЕ нужны.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json

from bot.exceptions import ToolNotConfigured
from bot.utils.formatting import esc

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_KW = {"impersonate": "chrome", "timeout": 12, "allow_redirects": False}


def _available() -> bool:
    try:
        return importlib.util.find_spec("curl_cffi") is not None
    except (ImportError, ValueError):
        return False


# ----------------------------------------------------------------------------
# Пробники: каждая check(session, username) → (found: bool|None, detail: str)
# ----------------------------------------------------------------------------

async def _github(session, username: str):
    resp = await session.get(
        f"https://api.github.com/users/{username}",
        headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"},
        **_KW,
    )
    if resp.status_code == 404:
        return False, ""
    if resp.status_code != 200:
        return None, f"код {resp.status_code}"
    try:
        data = json.loads(resp.text or "{}")
    except (json.JSONDecodeError, TypeError):
        return True, ""
    parts = []
    if data.get("name"):
        parts.append(f"имя: {data['name']}")
    if data.get("location"):
        parts.append(f"город: {data['location']}")
    if data.get("bio"):
        parts.append(f"био: {str(data['bio'])[:60]}")
    if data.get("followers") is not None:
        parts.append(f"фолловеров: {data['followers']}")
    if data.get("public_repos") is not None:
        parts.append(f"репозиториев: {data['public_repos']}")
    if data.get("created_at"):
        parts.append(f"создан: {str(data['created_at'])[:10]}")
    return True, "; ".join(parts)


async def _gitlab(session, username: str):
    resp = await session.get(
        f"https://gitlab.com/api/v4/users?username={username}",
        headers={"User-Agent": _UA},
        **_KW,
    )
    if resp.status_code == 404:
        return False, ""
    if resp.status_code != 200:
        return None, f"код {resp.status_code}"
    try:
        data = json.loads(resp.text or "[]")
    except (json.JSONDecodeError, TypeError):
        return None, ""
    if isinstance(data, list) and data:
        return True, f"id: {data[0].get('id')}"
    return False, ""


async def _reddit(session, username: str):
    resp = await session.get(
        f"https://www.reddit.com/user/{username}/about.json",
        headers={"User-Agent": _UA},
        **_KW,
    )
    if resp.status_code == 404:
        return False, ""
    if resp.status_code != 200:
        return None, f"код {resp.status_code}"
    try:
        data = json.loads(resp.text or "{}")
    except (json.JSONDecodeError, TypeError):
        return None, ""
    payload = data.get("data") if isinstance(data, dict) else None
    if payload and payload.get("name"):
        detail = ""
        if payload.get("total_karma") is not None:
            detail = f"карма: {payload['total_karma']}"
        return True, detail
    return None, ""


def _page(url: str, ok=(200, 302), not_found=(404,)):
    async def check(session, username: str):
        try:
            resp = await session.get(
                url.format(u=username),
                headers={"User-Agent": _UA},
                **_KW,
            )
        except Exception:  # noqa: BLE001
            return None, "нет соединения"
        st = resp.status_code
        if st in ok:
            return True, ""
        if st in not_found:
            return False, ""
        return None, f"код {st}"
    return check


_PROBES = [
    {"label": "GitHub", "emoji": "🐙", "check": _github, "url": "https://github.com/{u}"},
    {"label": "GitLab", "emoji": "🦊", "check": _gitlab, "url": "https://gitlab.com/{u}"},
    {"label": "Reddit", "emoji": "🔺", "check": _reddit, "url": "https://www.reddit.com/user/{u}"},
    {"label": "Telegram", "emoji": "✈️", "check": _page("https://t.me/{u}"), "url": "https://t.me/{u}"},
    {"label": "YouTube", "emoji": "▶️", "check": _page("https://www.youtube.com/@{u}"), "url": "https://www.youtube.com/@{u}"},
    {"label": "Twitch", "emoji": "🎮", "check": _page("https://www.twitch.tv/{u}"), "url": "https://www.twitch.tv/{u}"},
    {"label": "Steam", "emoji": "🔥", "check": _page("https://steamcommunity.com/id/{u}"), "url": "https://steamcommunity.com/id/{u}"},
    {"label": "Instagram", "emoji": "📸", "check": _page("https://www.instagram.com/{u}/"), "url": "https://www.instagram.com/{u}/"},
    {"label": "TikTok", "emoji": "🎵", "check": _page("https://www.tiktok.com/@{u}"), "url": "https://www.tiktok.com/@{u}"},
    {"label": "Pinterest", "emoji": "📌", "check": _page("https://www.pinterest.com/{u}/"), "url": "https://www.pinterest.com/{u}/"},
    {"label": "Tumblr", "emoji": "🌙", "check": _page("https://{u}.tumblr.com"), "url": "https://{u}.tumblr.com"},
    {"label": "Mastodon", "emoji": "🐘", "check": _page("https://mastodon.social/@{u}"), "url": "https://mastodon.social/@{u}"},
    {"label": "ВКонтакте", "emoji": "🔵", "check": _page("https://m.vk.com/{u}"), "url": "https://vk.com/{u}"},
    {"label": "Spotify", "emoji": "🎧", "check": _page("https://open.spotify.com/user/{u}"), "url": "https://open.spotify.com/user/{u}"},
]


# ----------------------------------------------------------------------------
# Публичный API
# ----------------------------------------------------------------------------

async def check_public_profiles(username: str, session=None) -> list[dict]:
    """Проверяет ник на публичных API без ключей.

    Возвращает список: [{label, emoji, found: bool|None, url, detail}].
    """
    if not _available():
        raise ToolNotConfigured(
            "curl_cffi не установлен:\n<code>pip install curl-cffi</code>\n"
            "Нужен для проверки профилей по публичным API."
        )
    from curl_cffi import requests as crequests

    async def run_one(probe):
        try:
            found, detail = await probe["check"](session, username)
        except Exception as exc:  # noqa: BLE001
            found, detail = None, type(exc).__name__
        return {
            "label": probe["label"], "emoji": probe["emoji"],
            "url": probe["url"].format(u=username),
            "found": bool(found) if found is not None else None,
            "detail": str(detail or ""),
        }

    async def _all(session):
        return await asyncio.gather(*(run_one(p) for p in _PROBES))

    if session is not None:
        return list(await _all(session))
    async with crequests.AsyncSession() as session:
        return list(await _all(session))


def format_public_profiles_section(results: list[dict]) -> list[str]:
    """Секция «🌐 Профили по публичным API» для отчёта."""
    if not results:
        return []
    found_n = sum(1 for r in results if r.get("found") is True)
    lines: list[str] = []
    add = lines.append
    add(f"<b>🌐 Профили по публичным API — найдено {found_n} из {len(results)}</b>")
    add("│ (без API-ключей: GitHub/GitLab/Reddit API и страницы профилей)")
    for r in results:
        found = r.get("found")
        if found is True:
            mark = "✅ <b>найден</b>"
        elif found is False:
            mark = "❌ не найден"
        else:
            mark = "⚠️ не удалось"
        line = f"│ {r.get('emoji', '')} {r.get('label', '')}: {mark}"
        if r.get("url") and found is True:
            line += f" — <a href='{r['url']}'>профиль</a>"
        if r.get("detail"):
            line += f" <i>({esc(r['detail'])})</i>"
        add(line)
    add("│ Если много «⚠️ не удалось» — сайты защищены от ботов, повторите позже.")
    return lines
