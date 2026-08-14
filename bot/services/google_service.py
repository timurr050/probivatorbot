"""Сервис разведки по Google-аккаунту (GHunt) — отдельная кнопка в меню."""
from __future__ import annotations

from bot.services.email_service import format_email_report, parse_ghunt, run_ghunt

__all__ = ["analyze_google", "format_google_report"]


async def analyze_google(email: str) -> str:
    """Запускает GHunt по email и возвращает готовый текстовый отчёт."""
    raw = await run_ghunt(email)
    data = parse_ghunt(raw, email)

    lines: list[str] = []
    add = lines.append
    add("<b>🔮 GHUNT · РАЗВЕДКА GOOGLE</b>")
    add(f"└ <code>{str(email)}</code>")
    add("")

    if "raw" in data:
        add(str(data["raw"]))
    else:
        mapping = {
            "name": "Имя",
            "localized_personal_name": "Имя (лок.)",
            "given_name": "Имя",
            "family_name": "Фамилия",
            "email": "Email",
            "gender": "Пол",
            "picture": "Аватар",
        }
        for key, label in mapping.items():
            if data.get(key):
                add(f"│ {label}: <code>{str(data[key])}</code>")
        if data.get("gmail_background_uri"):
            add(f"│ Фон Gmail: <a href='{data['gmail_background_uri']}'>ссылка</a>")
        if data.get("uri"):
            add(f"│ Профиль: <a href='{data['uri']}'>открыть</a>")

    if "Запустите" not in raw and "ghunt" in raw.lower():
        add("")
        add("⚠️ GHunt может требовать авторизации:\n<code>ghunt check</code> (один раз)")

    add("")
    add("⚡ Данные из открытых источников. Используйте только в законных целях.")
    return "\n".join(lines)


# Экспорт для порядка
format_email_report = format_email_report  # noqa: F811