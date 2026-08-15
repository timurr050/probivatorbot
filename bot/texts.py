"""Все пользовательские тексты бота в одном месте."""
from __future__ import annotations

from bot.utils.validators import EMAIL_FORMAT_HINT, PHONE_FORMAT_HINT, USERNAME_FORMAT_HINT

START_TEXT = (
    "Добро пожаловать в <b>ProbivBot</b> — агрегатор OSINT-инструментов. "
    "Бот работает только с данными из <i>открытых</i> источников.\n\n"
    "Выберите тип цели 👇"
)

HELP_TEXT = (
    "<b>ℹ️ Как пользоваться</b>\n"
    "1. Выберите категорию в меню.\n"
    "2. Бот сразу запустит <b>автопробив по всем движкам</b> "
    "(точечный выбор — кнопка «⚙️ Выбрать движок»).\n"
    "3. Отправьте цель в правильном формате (см. «Форматы ввода»).\n"
    "4. Результат придёт ответом на ваше сообщение-запрос одним отчётом.\n\n"
    "В автопробив входят: phonenumbers, PhoneInfoga, Telethon, ignorant, "
    "socialscan, sherlock, maigret (3000+ сайтов), snscrape, holehe, h8mail, "
    "GHunt и проверка аккаунтов в популярных сервисах (ВК, Instagram, TikTok, "
    "WhatsApp, Telegram, GitHub) через curl_cffi с подменой TLS-отпечатка.\n\n"
    "Чем больше настроено в <code>.env</code> (Telethon, PhoneInfoga, GHunt), тем больше данных.\n\n"
    "<b>🔮 GHunt (разведка Google)</b>\n"
    "1. Установите: <code>pip install ghunt</code>\n"
    "2. Авторизуйтесь один раз: <code>ghunt login</code> — войдите в Google "
    "в браузере; токен сохранится в <code>~/.pyconfig/ghunt/creds.data</code> "
    "(Windows: <code>C:\\Users\\Имя\\.pyconfig\\ghunt\\creds.data</code>).\n"
    "3. Бот в Docker — примонтируйте папку с токеном: "
    "<code>./ghunt:/root/.pyconfig/ghunt</code> (volume в docker-compose.yml), "
    "или укажите путь в <code>GHUNT_CONFIG_PATH</code> в <code>.env</code>.\n"
    "4. Проверка: <code>ghunt check</code>."
)

FORMATS_TEXT = (
    "📐 <b>Формат ввода</b>\n\n"
    f"<b>📱 Телефон</b>\n{PHONE_FORMAT_HINT}\n\n"
    f"<b>🧑‍💻 Никнейм</b>\n{USERNAME_FORMAT_HINT}\n\n"
    f"<b>📧 Email</b>\n{EMAIL_FORMAT_HINT}\n\n"
    "<b>🖼 Фото</b>\n"
    "— как <b>Документ</b> (файл) → EXIF сохраняется целиком (рекомендуется);\n"
    "— как <b>Фото</b> → Telegram сожмёт и вырежет EXIF.\n"
    "Поддерживаются: JPG/PNG/TIFF/BMP/HEIC/WebP/GIF.\n\n"
    "<b>✈️ Telegram-ник</b>\n"
    "Без «@», 5–32 символа, латиница/цифры/подчёркивание."
)

ABOUT_TEXT = (
    "🔎 <b>О боте</b>\n"
    "Движки: phonenumbers, PhoneInfoga, Telethon, socialscan, sherlock, "
    "maigret (3000+ сайтов), snscrape, exifread, ignorant, holehe, h8mail, GHunt, "
    "curl_cffi (проверка аккаунтов в популярных сервисах).\n\n"
    "⚠️ Используйте только в законных целях и только по вашим/разрешённым данным. "
    "Сбор данных о людях без согласия может нарушать закон (152-ФЗ и аналоги)."
)

KEYS_TEXT = (
    "🔑 <b>Ключи и доступы (всё в .env)</b>\n\n"
    "Большинство проверок работает <b>без ключей</b> (GitHub/GitLab/Reddit API, "
    "t.me, формы Instagram/TikTok/VK/WhatsApp через имитацию запросов curl_cffi).\n\n"
    "<b>Бесплатные ключи, которые можно добавить:</b>\n"
    "1️⃣ <b>Telegram API</b> (Telethon — поиск по номерам и никам, несколько сессий)\n"
    "   Регистрация: https://my.telegram.org/apps\n"
    "   В .env: <code>TG_API_ID</code>, <code>TG_API_HASH</code>, "
    "<code>TG_ACCOUNTS</code> (создать сессию: <code>python session_maker.py</code>)\n\n"
    "2️⃣ <b>GitHub</b> (бесплатно 60 запросов/час, без ключа)\n"
    "   Больше лимитов: https://github.com/settings/tokens → generate classic token\n"
    "   (бот пока работает без ключа — он опционален)\n\n"
    "3️⃣ <b>Google</b> (GHunt — разведка Google-аккаунта)\n"
    "   Достаточно обычного Google-аккаунта: <code>ghunt login</code> "
    "(см. /help → GHunt)\n\n"
    "4️⃣ <b>VK API</b> (продвинутый поиск по ВК)\n"
    "   Создайте приложение: https://vk.com/editapp?act=create\n"
    "   Токен: https://vk.com/dev/access_token (нужен после входа)\n\n"
    "5️⃣ <b>hunter.io</b> (h8mail — утечки, бесплатно ~25 поисков/мес)\n"
    "   Регистрация: https://hunter.io/users/sign_up\n"
    "   В .env: <code>H8MAIL_KEY</code> (в h8mail_config.ini)\n\n"
    "6️⃣ <b>Twitch / Steam / Reddit</b> — бесплатные ключи для проверки ников:\n"
    "   Twitch: https://dev.twitch.tv/console/apps\n"
    "   Steam: https://steamcommunity.com/dev/apikey\n"
    "   Reddit: https://www.reddit.com/prefs/apps\n\n"
    "<b>Важно про Instagram/TikTok/WhatsApp:</b> публичных API-ключей для проверки "
    "«есть ли аккаунт» у них НЕТ. Бот имитирует их формы регистрации через "
    "curl_cffi (подмена TLS-отпечатка Chrome). Если сайт блокирует — честно "
    "пишется «⚠️ не удалось проверить», это не баг, а защита от ботов."
)

NOT_ADMIN_TEXT = "⛔️ Доступ только для администраторов бота."

PROMPT_TEXT = "Отправьте цель в <b>{label}</b> формате:\n\n{hint}"

STATUS_TEXT = "🔍 Ищем по «{target}» через {tool}…"

DONE_MARK = "✅ Готово"
ERR_MARK = "❌ Ошибка"


def error_text(msg: str) -> str:
    return f"{ERR_MARK} <b>Что-то пошло не так</b>\n\n{str(msg)}"


def unknown_text() -> str:
    return "ℹ️ Нажми <b>«Меню»</b> и выберите категорию, либо /formats для подсказки."