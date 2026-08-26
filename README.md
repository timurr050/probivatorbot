# ProbivBot — OSINT-агрегатор на aiogram

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)](https://www.python.org)
[![aiogram 3](https://img.shields.io/badge/aiogram-3.x-2C8EBB)](https://docs.aiogram.pro)
[![Tests](https://img.shields.io/badge/tests-125%20passed-green)](tests/)
[![Docker](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white)](docker-compose.yml)
[![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)](.github/workflows/ci-cd.yml)

Телеграм-бот для сбора данных из **открытых** источников. Объединяет 15 OSINT-движков под
одним интерфейсом: ответы приходят **в виде ответа-цитирования** на ваше сообщение.

> ⚠️ **Юридический дисклеймер.** Бот работает только с публично доступными данными и
> предназначен для пентеста, журналистики и проверки **своих/разрешённых** данных.
> Использование против третьих лиц без согласия может нарушать законодательство
> (152-ФЗ «О персональных данных» и аналоги в других странах). Ответственность на операторе.

---

## 📑 Содержание

- [Архитектура](#-архитектура)
- [Принцип работы](#принцип-работы)
- [Установка (локально)](#-установка)
- [Конфигурация .env и где взять ключи](#-конфигурация-env)
- [Движки и их установка](#-движки-где-установить-и-что-будет-без-них)
- [Используемые библиотеки](#-используемые-библиотеки)
- [Docker: запуск, реплики, авто-масштабирование](#-docker-запуск-реплики-и-авто-масштабирование)
- [Деплой на сервер (CI/CD)](#-деплой-на-сервер-cicd-тесты--ssh-деплой)
- [Тесты](#-тесты)
- [Известные ограничения](#-известные-ограничения)

---

## 🧱 Архитектура

```
ProbivBot/
├── main.py                     # Точка входа (запуск polling)
├── requirements.txt            # Зависимости
├── create_session.py           # Генерация TG_ACCOUNTS-сессии для Telethon
├── .env.example                # Шаблон конфигурации (скопировать в .env)
├── .env                        # Ваши реальные настройки (не коммитить)
├── Dockerfile                  # Образ для деплоя (скачивает PhoneInfoga для Linux)
├── docker-compose.yml          # Запуск на сервере (env_file, volume, healthcheck)
├── entrypoint.sh               # Старт бота (RUN_TESTS_ON_START=true — прогнать тесты)
├── deploy/autoscale.sh         # Авто-масштабирование: реплики по CPU (--scale)
├── .github/workflows/ci-cd.yml # CI/CD: тесты → деплой на сервер по SSH
│
├── bot/
│   ├── config.py               # Чтение .env, dataclass Settings
│   ├── loader.py               # Bot, Dispatcher, FSM-хранилище (singleton)
│   ├── texts.py                # Все тексты бота (помощь, форматы, дисклеймер)
│   ├── keyboards.py            # Inline-клавиатуры (главное меню, меню движков)
│   ├── filters.py              # Фильтр IsAdmin (ограничение по ADMIN_IDS)
│   ├── states.py               # FSM-состояния (ожидание телефона/ника/email/фото)
│   ├── exceptions.py           # ProbivError, ValidationError, ServiceError и т.д.
│   ├── db.py                   # SQLite: пользователи, история, статистика
│   │
│   ├── handlers/               # Слой приёма сообщений
│   │   ├── common.py           # /start /help /menu /formats + навигация (callbacks)
│   │   ├── input_handlers.py   # Обработка телефон/ник/email (валидация → отчёт)
│   │   ├── photo.py            # Обработка фото (скачивание → EXIF) и видео (метаданные MP4)
│   │   ├── google.py           # Google-разведка (GHunt)
│   │   ├── fallback.py         # Ответ на нераспознанный текст (подключается последним)
│   │   └── __init__.py         # Сборка дерева роутеров (порядок критичен!)
│   │
│   ├── services/               # Слой движков (вся OSINT-логика)
│   │   ├── base.py             # run_cli(), ensure_binary(), пути сессий
│   │   ├── phone_service.py    # phonenumbers + PhoneInfoga + Telethon + ignorant
│   │   ├── username_service.py # sherlock + socialscan + snscrape + Telethon
│   │   ├── maigret_service.py  # maigret — никнейм на 3000+ сайтах (HTTP+регэкспы)
│   │   ├── registration_service.py # curl_cffi — есть ли аккаунт в ВК/IG/TikTok/WA/TG/GitHub
│   │   ├── email_service.py    # holehe + h8mail + socialscan + GHunt
│   │   ├── photo_service.py    # exifread + Pillow + GPS + геокодирование
│   │   ├── video_service.py    # парсер MP4/MOV: атомы, ilst, ©xyz-GPS, геокодирование
│   │   └── google_service.py   # GHunt (отдельная кнопка)
│   │
│   └── utils/
│       ├── validators.py       # Валидация: телефон/ник/email (с подсказками формата)
│       ├── formatting.py       # HTML-экранирование, split длинных сообщений
│       └── filehelpers.py      # Безопасное скачивание медиа во временные файлы
│
└── tests/                      # Pytest-тесты (125 шт., оффлайн)
    ├── test_validators.py
    ├── test_formatting.py
    ├── test_phone_service.py
    ├── test_photo_service.py
    ├── test_video_service.py
    ├── test_routing.py         # Реальная маршрутизация через Dispatcher.feed_update
    ├── test_handlers_smoke.py
    ├── test_db.py
    └── test_services_parsers.py
```

### Слои приложения (подробно)

```
┌──────────────────────────────────────────────────────────────┐
│                      main.py (точка входа)                    │
│   - polling-режим (по умолчанию)                              │
│   - webhook-режим (WEBHOOK_DOMAIN) — для реплик               │
│   - фоновый /health-сервер для Docker healthcheck             │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│              bot/loader.py — singleton: Bot + Dispatcher      │
│   DP — дерево роутеров, FSM-хранилище (MemoryStorage)         │
│   порядок роутеров критичен (fallback подключается последним) │
└───────┬──────────────────┬──────────────────┬────────────────┘
        │                  │                  │
   handlers/           services/          utils/
   ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
   │ ФСМ + меню       │ │ 15 OSINT-движков│ │ валидаторы      │
   │ common           │ │ phone_service   │ │ validators.py   │
   │ input_handlers   │ │ username_service│ │ formatting.py   │
   │ photo            │ │ email_service   │ │ filehelpers.py  │
   │ google           │ │ photo_service   │ └─────────────────┘
   │ fallback (LAST)  │ │ video_service   │
   └─────────────────┘ │ google_service   │
        │              └─────────────────┘
        │                        │
        │                 CLI-инструменты запускаются в
        │                 отдельных процессах (таймаут),
        │                 сетевые — через asyncio.wait_for
        ▼
┌──────────────────────────────────────────────────────────────┐
│            bot/db.py — SQLite (пользователи, история,        │
│            статистика). Логирование не роняет бота.          │
└──────────────────────────────────────────────────────────────┘
```

**Ключевые принципы:**

1. **Хендлеры ничего не знают о железе** — вся OSINT-логика в `services/`, хендлеры
   только принимают ввод, валидируют и собирают HTML-отчёт.
2. **Порядок роутеров = порядок приоритета.** В `handlers/__init__.py` fallback
   подключается **последним** — если поставить его первым, он перехватит ввод телефона
   и бот «замолчит». Этот порядок зафиксирован регрессионными тестами.
3. **Ошибки типизированы** (`bot/exceptions.py`): `ValidationError`, `ToolNotConfigured`,
   `ToolTimeout`, `ExternalToolError`, `ServiceError` — юзеру показывается причина,
   а не стектрейс.
4. **Частичный отказ не роняет отчёт**: в режиме «Всё сразу» упавшие движки помечаются
   строкой «⚠️ Частично не выполнено», остальные продолжают работать.

### Принцип работы

1. Пользователь нажимает категорию в главном меню → появляется меню движков.
2. Выбирает движок (или «🚀 Всё сразу») → бот переводит его в FSM-состояние и просит цель.
3. Пользователь присылает цель в нужном формате → `validators` валидируют и нормализуют.
4. Сервисы запускаются (CLI-инструменты — в отдельных процессах с таймаутом,
   сетевые — с `asyncio.wait_for`), ошибки типизированы в `bot/exceptions.py`.
5. Итог собирается в HTML-отчёт и отправляется **ответом** на сообщение пользователя
   (цитирование исходного запроса), длинные отчёты разбиваются на части.

### Обработка ошибок

- `ValidationError` — неверный формат ввода; пользователю показывается **что ожидалось**.
- `ToolNotConfigured` — инструмент не установлен / не настроен в `.env`; в ответе — как исправить.
- `ToolTimeout` / `ExternalToolError` — CLI упал; текст ошибки маскируется.
- Любое падение в сервисе не валит весь отчёт: в режиме «Всё сразу» проблемные движки
  помечаются строкой «⚠️ Частично не выполнено», остальные работают дальше.

---

## 🛠 Установка

```powershell
# 1. Виртуальное окружение (уже создано — .venv)
python -m venv .venv

# 2. Зависимости
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Конфигурация
Copy-Item .env.example .env
# отредактируйте .env: BOT_TOKEN и т.д.

# 4. Запуск
.venv\Scripts\python.exe main.py
```

---

## ⚙️ Конфигурация `.env`

Скопируйте `.env.example` в `.env` и заполните ключи.

### 🎫 Шпаргалка: где взять каждый ключ (все ссылки)

| Ключ | Где взять |
|---|---|
| `BOT_TOKEN` | Telegram → **@BotFather** → `/newbot` → токен. Ссылка: https://t.me/BotFather |
| `ADMIN_IDS` | Ваш Telegram ID: напишите **@userinfobot** (https://t.me/userinfobot) или **@getmyid_bot** |
| `TG_API_ID`, `TG_API_HASH` | https://my.telegram.org → «API development tools» → «Create application» → там `api_id` и `api_hash` |
| `TG_ACCOUNTS` | Генерируется автоматически: `python create_session.py` (см. ниже) |
| `PHONEINFOGA_PATH` | Готовый бинарник: https://github.com/ExpertAnonymous/PhoneInfoga/releases (в Docker качается сам, ключ не нужен) |
| `PHONEINFOGA_API_KEY` | https://www.numlookupapi.com (бесплатно) или https://veriphone.io |
| `GHUNT_CONFIG_PATH` | Авторизация один раз в консоли: `ghunt check` (https://github.com/mxrch/ghunt) |
| `WEBHOOK_DOMAIN` / `WEBHOOK_SECRET` | Только для реплик: ваш домен с HTTPS (например, через **Caddy** https://caddyserver.com) + любая случайная строка |
| `SHERLOCK_OFFICIALLY_VERIFIED` | без ключа (`true`/`false`) |

Ниже — подробно: зачем ключ и что будет, если его не указать.

### 🔑 Обязательный ключ

| Ключ | Зачем | Где взять | Если не указать |
|---|---|---|---|
| `BOT_TOKEN` | Токен, под которым бот общается с Telegram API | **@BotFather** → `/newbot` → скопируйте токен: https://t.me/BotFather | Бот не запустится (`RuntimeError: BOT_TOKEN не задан`) |

### 👥 Доступ

| Ключ | Зачем | Где взять | Если не указать |
|---|---|---|---|
| `ADMIN_IDS` | ID администраторов, которым разрешено пользоваться ботом (через запятую) | Ваш ID: напишите **@userinfobot**, **@getmyid_bot** или **@RawDataBot** в Telegram | Все пользователи могут пользоваться ботом |
| `RESTRICT_TO_ADMINS` | `true` — включить ограничение по `ADMIN_IDS`, `false` — выключить | — | По умолчанию `false` (бот открыт всем) |

### 🖥 Вывод CLI-инструментов

| Ключ | Зачем | Где взять | Если не указать |
|---|---|---|---|
| `CLI_ENCODING` | Кодировка вывода консольных инструментов (sherlock, holehe…) | Значение по умолчанию `utf-8`; на Windows с кириллицей попробуйте `cp866` | Кириллица в отчётах может быть «кракозябрами» |
| `CLI_TIMEOUT` | Сколько секунд ждать каждый инструмент до прерывания | По умолчанию `90` | Слишком мало — инструменты не успеют закончить |

### 📱 PhoneInfoga — глубокий анализ номера

| Ключ | Зачем | Где взять | Если не указать |
|---|---|---|---|
| `PHONEINFOGA_PATH` | Путь к бинарнику `phoneinfoga` (Windows: `C:\путь\phoneinfoga.exe`) | Скачать готовый бинарник с GitHub: https://github.com/ExpertAnonymous/PhoneInfoga/releases | Кнопка «PhoneInfoga» пропустится, в отчёте появится «⚠️ PhoneInfoga: бинарник не найден» |
| `PHONEINFOGA_API_KEY` | Ключ для сервисов PhoneInfoga (Numverify, Twilio и т.п.) | Зарегистрироваться на https://www.numlookupapi.com (бесплатно) или https://veriphone.io; или поднять свой инстанс https://phoneinfoga.cx | Работает без ключа, но часть источников будет недоступна |

### ✈️ Telethon — проверка Telegram (номер в TG, инфо по нику)

| Ключ | Зачем | Где взять | Если не указать |
|---|---|---|---|
| `TG_API_ID` | ID приложения для MTProto API Telegram | **https://my.telegram.org** → «API development tools» → создайте приложение → там `api_id` | Разделы «✈️ Telegram» в отчётах пропустятся («Telethon не настроен») |
| `TG_API_HASH` | Хеш того же приложения (рядом с `api_id`) | Там же, https://my.telegram.org/apps | То же, что выше |
| `TG_ACCOUNTS` | Какие аккаунты/сессии использовать для запросов в Telegram. Формат JSON: `{"+375291234567": "session_375291234567"}` | Сгенерировать автоматически скриптом `create_session.py` (см. ниже) | Без сессии запросы в Telegram недоступны |

**Как создать сессию для `TG_ACCOUNTS` (один раз):**
```powershell
# 1. Впишите в .env TG_API_ID и TG_API_HASH
# 2. Запустите скрипт, введите телефон аккаунта, затем код из Telegram:
.venv\Scripts\python.exe create_session.py
# 3. Скрипт выведет готовую строку — вставьте её в TG_ACCOUNTS
```

### 🔮 GHunt — разведка Google-аккаунта

| Ключ | Зачем | Где взять | Если не указать |
|---|---|---|---|
| `GHUNT_CONFIG_PATH` | Путь к конфигу GHunt (обычно пусто — хранится в `~/.pyconfig/ghunt/`) | Авторизация: в консоли один раз выполнить `ghunt check` → перейти по ссылке → вставить код. Инструкция: https://github.com/mxrch/ghunt#installation | GHunt будет просить авторизацию в каждом отчёте |

### 🕵️ Sherlock — поиск никнейма

| Ключ | Зачем | Где взять | Если не указать |
|---|---|---|---|
| `SHERLOCK_OFFICIALLY_VERIFIED` | `true` — искать только на проверенных официальных сайтах (быстрее, меньше ложных срабатываний), `false` — по всем 400+ | — | По умолчанию `false` (полный поиск) |

---

## 🔧 Движки: где установить и что будет без них

| Движок | Что делает | Установка (ссылка) | Если не установлен |
|---|---|---|---|
| `phonenumbers` | Разбор номера: страна, тип, оператор, гео, таймзоны | `pip install phonenumbers` (входит в requirements) | Секция «Разбор номера» пустая |
| `PhoneInfoga` | Глубокое сканирование номера | Бинарник: https://github.com/ExpertAnonymous/PhoneInfoga/releases | Кнопка пропускается с пометкой |
| `Telethon` | Номер в Telegram + инфо по username (аналог telegram-phone-number-checker) | `pip install telethon` + настройка `.env` | Секции «✈️ Telegram» нет |
| `ignorant` | Поиск номера по соцсетям | `pip install ignorant` (https://github.com/megadose/ignorant) | Кнопка пропускается с пометкой |
| `sherlock` | Никнейм на 400+ сайтах | `pip install sherlock-project` (https://github.com/sherlock-project/sherlock) | Кнопка пропускается с пометкой |
| `socialscan` | Проверка email/username/телефона на соцсетях | `pip install socialscan` (https://github.com/iojw/socialscan) | Кнопка пропускается с пометкой |
| `snscrape` | Последние посты username в X, Instagram, Reddit, Telegram | `pip install snscrape` (https://github.com/JustAnotherArchivist/snscrape) | Кнопка пропускается с пометкой |
| `maigret` | Никнейм на 3000+ сайтах (прямые HTTP-запросы + регулярки, без ключей) | `pip install maigret` (https://github.com/soxoj/maigret) | Кнопка пропускается с пометкой |
| `twscrape` | Профиль и твиты Twitter/X по нику (прямые запросы к API X) | `pip install twscrape` (https://github.com/vladkens/twscrape) + добавить аккаунт в пул (`python -m twscrape add_accounts`) | Кнопка «🐦 Twitter» пропускается с пометкой «нет аккаунтов Twitter» |
| `curl-cffi` | Проверка «есть ли аккаунт» по email/телефону в ВК/Instagram/TikTok/WhatsApp/Telegram/GitHub (подмена TLS-отпечатка JA3/JA4 — обход Cloudflare) | `pip install curl-cffi` (https://github.com/lexiforest/curl_cffi) | Секция «🪪 Аккаунты в популярных сервисах» пропускается |
| `exifread` + Pillow | Максимум метаданных фото: EXIF, GPS, MakerNote, DPI, ICC | `pip install exifread Pillow` | Фото-анализ недоступен |
| `video_service` (чистый Python) | Метаданные видео MP4/MOV: даты, длительность, дорожки, ilst (©mak/©mod/©day/©xyz), GPS → адрес (без ffprobe) | входит в проект | Видео-анализ недоступен |
| `holehe` | Регистрация email на 120+ сайтах | `pip install holehe` (https://github.com/megadose/holehe) | Кнопка пропускается с пометкой |
| `h8mail` | Поиск email в утечках | `pip install h8mail` (https://github.com/khast3x/h8mail) + `h8mail_config.ini` | Кнопка пропускается с пометкой |
| `GHunt` | Разведка Google-аккаунта | `pip install ghunt` + `ghunt check` (https://github.com/mxrch/ghunt) | Кнопка пропускается с пометкой |

> 💡 В режиме «🚀 Всё сразу» неработающие движки **не роняют весь отчёт** — они помечаются строкой
> «⚠️ Частично не выполнено: <движок>: <причина>», а остальные результаты приходят нормально.

> Примечание: `python-telegram-phone-number-checker` — не существует как PyPI-пакет
> (это инструмент-обёртка над Telethon). Проверка номера в Telegram реализована нативно
> через Telethon в `bot/services/phone_service.py::check_telegram`.

---

## 📦 Используемые библиотеки

Полный список зависимостей — в [`requirements.txt`](requirements.txt). Кратко по группам:

### Ядро бота
| Библиотека | Назначение |
|---|---|
| `aiogram` (3.x) | Telegram Bot API, асинхронный фреймворк, FSM, inline-клавиатуры |
| `python-dotenv` | Чтение конфигурации из `.env` |
| `aiohttp` | HTTP-клиент для aiogram / запросов к Telegram API |
| `pytest` + `pytest-asyncio` | Оффлайн-тесты (входят в образ, но не в runtime) |

### OSINT-движки (Python-пакеты)
| Библиотека | Что даёт |
|---|---|
| `phonenumbers` | Разбор/валидация номера: страна, оператор, гео, тип, таймзоны |
| `telethon` | MTProto-клиент Telegram: номер в TG, инфо по username |
| `exifread` + `Pillow` | Метаданные фото (EXIF, GPS, DPI, ICC) |
| `socialscan` | Проверка доступности email/username/телефона в соцсетях |
| `holehe` | Регистрация email на 120+ сайтах |
| `h8mail` | Поиск email в публичных утечках |
| `sherlock-project` | Поиск username по 400+ сайтам (CLI) |
| `ignorant` | Поиск телефона по соцсетям (CLI) |
| `ghunt` | Разведка по Google-аккаунту |
| `snscrape` | Посты X/Instagram/Reddit/Telegram (⚠️ несовместим с Python 3.12 — отключён) |
| `maigret` | Поиск username по 3000+ сайтам (HTTP + регулярки) |
| `twscrape` | Профиль и твиты Twitter/X по нику (нужен аккаунт Twitter в пуле) |
| `curl-cffi` | HTTP с подменой TLS-отпечатка (JA3/JA4) — обход Cloudflare/защиты |
| `geopy` | Обратное геокодирование GPS-координат в адрес |

### Внешние CLI-инструменты (не PyPI, качаются/ставятся отдельно)
| Инструмент | Назначение |
|---|---|
| `PhoneInfoga` | Глубокое сканирование номера (в Docker качается автоматически) |

---

## 🧯 Обработка ошибок (как это видит пользователь)

| Ситуация | Класс исключения | Что увидит пользователь |
|---|---|---|
| Пустой/битый токен | `ConfigError` | Бот не запускается, в консоли: `BOT_TOKEN не задан` |
| Неверный формат телефона/ника/email | `ValidationError` | ❌ + **что именно** не так + подсказка формата (с кнопкой «Форматы ввода») |
| Инструмент не установлен | `ToolNotConfigured` | ❌ + какая команда `pip install ...` нужна |
| Инструмент не настроен в `.env` | `ToolNotConfigured` | ❌ + какие ключи `.env` добавить |
| CLI завис | `ToolTimeout` | «превышен таймаут» |
| CLI упал с ошибкой | `ExternalToolError` | ❌ + код выхода |
| Сеть/парсинг/прочее | `ServiceError` | ❌ + краткое описание (без стектрейса) |
| Один движок упал в «Всё сразу» | любое из выше | Строка «⚠️ Частично не выполнено» в конце отчёта, остальные секции на месте |
| Очень длинный отчёт | — | Автоматически режется на несколько сообщений (не рвёт HTML) |

Все ответы бота — **ответом-цитированием** на ваше сообщение с запросом.

---

## 📐 Формат ввода (подсказки встроены в бота)

- **Телефон:** `+375291234567`, `+7 900 123-45-67`, `8 029 123-45-67`, `79123456789`.
- **Никнейм:** латиница/цифры/`_`, без `@`.
- **Email:** `name@domain.com`.
- **Фото:** лучше как **Документ (файл)** — так EXIF сохраняется полностью.
  Как «Фото» Telegram сжимает и вырезает метаданные. Поддержка: JPG/PNG/TIFF/BMP/HEIC/WebP/GIF.
- **Видео:** принимаются и сообщения-видео, и **Документы** MP4/MOV. Метаданные
  (©mak/©mod/©day/©xyz-GPS) читаются прямо из контейнера — ffprobe/FFmpeg не нужен.

---

## 📖 Документация по модулям

### `bot/services/phone_service.py`
- `phonenumbers_info(e164)` → словарь с типом, оператором, гео, таймзонами.
- `run_phoneinfoga(e164)` → запуск CLI, авто-фолбэк на legacy-режим `number`.
- `summarize_phoneinfoga(raw)` → чистые строки из лога (дедупликация).
- `check_telegram(e164)` → `registered / username / имя / bot / premium / photo`.
- `run_ignorant(e164)` → поиск по соцсетям; `parse_ignorant(raw)` → `{сайт: статус}`.
- `format_phone_report(...)` → итоговый HTML-отчёт.

### `bot/services/username_service.py`
- `run_sherlock(username)` → найденные URL; `run_socialscan`, `parse_socialscan`.
- `run_snscrape(username)` → последние посты X/Instagram/Reddit/Telegram.
- `telegram_user_lookup(username)` → данные TG-аккаунта (ID, флаги, телефон если виден).

### `bot/services/maigret_service.py`
- `run_maigret(username)` → CLI `python -m maigret` (utf-8, `--dns-resolver threaded`,
  запуск во временной папке); `parse_maigret(raw)` → `{found, count, tags}`;
  `format_maigret_section(...)` → секция «🕵️ Maigret».

### `bot/services/registration_service.py`
- `check_registrations(target, 'email'|'phone')` → есть ли аккаунт в популярных
  сервисах (ВК, Instagram, TikTok, WhatsApp, Telegram, GitHub) через curl_cffi
  (метод «восстановление пароля/форма регистрации», подмена TLS-отпечатка);
  `format_registrations_section(...)` → секция «🪪 Аккаунты в популярных сервисах».
  Результат честный: ✅ найден / ❌ не найден / ⚠️ не удалось проверить.

### `bot/services/email_service.py`
- `run_holehe / parse_holehe`, `run_h8mail / parse_h8mail`, `run_ghunt / parse_ghunt`.

### `bot/services/photo_service.py`
Извлекает максимум: файл (размер/дата), изображение (формат/DPI/ICC), все группы EXIF
(Image/EXIF/GPS/Thumbnail/MakerNote/Interop), GPS → десятичные градусы + ссылки на
Google Maps и Яндекс Карты + обратный геокодинг (Nominatim, OSM).

### `bot/services/video_service.py`
Парсер MP4/MOV без ffprobe (ISO BMFF/QuickTime): атомы ftyp/moov/udta/meta/ilst,
даты создания (mvhd/mdhd), длительность, дорожки, метаданные ©mak/©mod/©day/©xyz,
GPS-строка QuickTime → координаты → карты + адрес через `reverse_geocode`.

### `bot/utils/validators.py`
`normalize_phone` понимает местные форматы (8…/7…/375…) и уточняет регион;
`normalize_username/email` с человекочитаемыми подсказками формата.

### `bot/utils/formatting.py`
HTML-экранирование и `split_message` — режет длинные отчёты по пробелам **вне** HTML-тегов.

---

## 🧪 Тесты

```powershell
.venv\Scripts\python.exe -m pytest tests -q
# 125 passed
```

Все тесты оффлайн: валидация, парсеры, EXIF (генерируется через Pillow), GPS-математика,
MP4-атомы (MP4 собирается в тесте из атомов), составление адреса, сборка отчётов,
**реальная маршрутизация** через `Dispatcher.feed_update` с фейковой сессией Telegram.

---

## 🐳 Docker: запуск, реплики и авто-масштабирование

Образ сам скачивает Linux-бинарник **PhoneInfoga** (см. `Dockerfile`), поэтому на сервере
поиск по телефону работает без ручной сборки.

### ⚡ Быстрый старт (2 команды)

```bash
# 1. Подготовить конфиг (вписать BOT_TOKEN и т.д.)
cp .env.example .env && nano .env

# 2. Собрать и запустить контейнер
docker compose up -d --build
```

Готово — бот онлайн. Проверка:

```bash
docker compose ps          # STATUS должен быть Up (healthy)
docker compose logs -f     # «ProbivBot запущен как @...»
```

### Способ 2 — без compose, одним `docker run`

```bash
docker build -t probivbot .
docker run -d --name probivbot \
  -p 8080:8080 \
  --env-file .env \
  -e PHONEINFOGA_PATH=/usr/local/bin/phoneinfoga \
  -v "$(pwd)/data:/app/data" \
  --restart unless-stopped \
  probivbot
```

> Команда для Windows PowerShell: `-v "$((Get-Location).Path)/data:/app/data"`.

### Запуск (1 контейнер)

```bash
cd /opt/probivbot
cp .env.example .env   # заполнить BOT_TOKEN и т.д. (или в CI это делает APP_ENV)
docker compose up -d --build
docker compose ps      # статус
docker compose logs -f # логи
```

- `data/` (SQLite, Telethon-сессии) монтируется с хоста — сохраняется между рестартами.
- `PHONEINFOGA_PATH` в контейнере перекрывается на `/usr/local/bin/phoneinfoga` автоматически.
- Источник опций и управление: `docker compose start/stop/restart`.

### Нагрузка → реплики (несколько контейнеров)

Когда одного контейнера мало — поднимаем копии:

```bash
# 2 реплики (только внутри docker compose)
docker compose up -d --scale probivbot=3
```

> ⚠️ **Важно:** реплики работают **только в webhook-режиме** (`WEBHOOK_DOMAIN` в `.env`).
> Telegram позволяет один активный long-polling клиент на бота (иначе 409 Conflict),
> поэтому при 2+ репликах бот должен принимать обновления через HTTP.

Файл `deploy/autoscale.sh` следит за CPU через `docker stats` и сам поднимает/убирает
реплики по порогам (по умолчанию подтяжка при CPU ≥ 70%, сброс при ≤ 20%,
от 1 до 3 реплик, проверка каждые 30 секунд):

```bash
sudo bash deploy/autoscale.sh
# настройки через переменные окружения:
#   CPU_HIGH=85 MAX_REPLICAS=5 CHECK_EVERY=20 sudo bash deploy/autoscale.sh
```

Количество реплик — это **горизонтальное масштабирование** (несколько обработчиков
под балансировщиком). Конкретный набор движков в одной реплике ускорить так нельзя —
каждая реплика обрабатывает своё обновление.

### Webhook-режим (нужен для реплик)

В `.env` на сервере:

```env
WEBHOOK_DOMAIN=https://probivbot.example.com
WEBHOOK_PATH=/webhook/probivbot
WEBHOOK_PORT=8080
WEBHOOK_SECRET=случайная_строка
```

Как раздать HTTPS и балансировку на реплики — примерами (рекомендую Caddy):

```caddyfile
probivbot.example.com {
    reverse_proxy probivbot:8080  # Caddy сам отдаёт HTTPS-сертификат
}
```

Caddy из compose-сети видит реплики по имени сервиса `probivbot` и балансирует между ними.

### Проверка живости (healthcheck)

Контейнер слушает `GET /health` на порту `8080` и в композе объявлен `healthcheck`
(проверка каждые 30 с). Статус: `docker inspect --format '{{.State.Health.Status}}' <контейнер>`.

---

## 🚀 Деплой на сервер (CI/CD: тесты → SSH-деплой)

Всё автоматизировано через **GitHub Actions** (`.github/workflows/ci-cd.yml`):
на push в `main` — сначала прогоняются тесты, затем бот копируется на сервер
и поднимается через `docker compose up -d --build` по **SSH с паролем**.

### Шаг 1. Загрузите проект в GitHub

```bash
git add -A
git commit -m "ProbivBot"
git remote add origin https://github.com/<ВАШ_ЛОГИН>/<РЕПО>.git
git push -u origin main
```

### Шаг 2. Укажите IP и пароль сервера

GitHub → ваш репозиторий → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Что вставить | Пример |
|---|---|---|
| `SERVER_IP` | **IP сервера**, где будет деплой | `188.166.22.7` |
| `SERVER_USER` | SSH-пользователь | `root` |
| `SERVER_PASSWORD` | **SSH-пароль** от этого пользователя | `My-Pa$$w0rd` |
| `SERVER_PORT` | SSH-порт | `22` |
| `APP_ENV` | **Весь ваш `.env` целиком** — текст от `BOT_TOKEN` до последнего ключа (токен, `ADMIN_IDS` и т.д.) | многострочный текст |

> ⚠️ `APP_ENV` — это содержимое локального `.env` (скопируйте файл → вставьте как одну секрету).

### Шаг 3. Запустите деплой

- **Автоматически:** любой `git push` в ветку `main`.
- **Вручную:** вкладка **Actions → CI/CD → Run workflow**.

Джоба `test` (сборка образа + `pytest`) должна пройти — только потом начнётся `deploy`.

### Проверка на сервере

```bash
cd /opt/probivbot        # сюда CI копирует проект
docker compose ps        # статус контейнеров (и реплик)
docker compose logs -f   # логи бота
docker compose restart   # перезапуск
sudo bash deploy/autoscale.sh   # авто-масштабирование по CPU
```

### Если что-то не работает

- **Ошибка входа по SSH** → проверьте `SERVER_IP` / `SERVER_USER` / `SERVER_PASSWORD`.
- **Сервер без Docker** → джоба `deploy` сама установит `docker.io` + `docker-compose-plugin`
  на Debian/Ubuntu при первой деплойке (нужен интернет и `apt`).
- **Бот поднялся, но молчит** → загляните в `docker compose logs` (обычно пустой `BOT_TOKEN`
  или неверный токен); потом дайте Telegram **⏸ → Продолжить** в @BotFather при необходимости.
- **SSH-порт не 22** → укажите свой в секрете `SERVER_PORT`.
- **Реплики конфликтуют (409)** → вы запустили `--scale` без `WEBHOOK_DOMAIN`. В long-polling
  режиме может быть только 1 реплика. Либо верните 1 реплику, либо включите webhook.
- **Контейнер помечен unhealthy** → порт 8080 занят другим процессом или healthcheck
  не успел пройти за `start_period` (20 с). Проверьте: `docker compose logs`.

---

## ⚠️ Известные ограничения

- **snscrape** больше не поддерживается автором; X/Instagram активно бают скрейперы —
  результат может быть пустым. Это нормально.
- **h8mail** без конфига/ключей может ничего не найти — создайте `h8mail_config.ini`.
- **GHunt** требует разовой авторизации в консоли: `ghunt check`.
- **PhoneInfoga** v2 требует API-ключ для части данных.
- Telethon работает через аккаунт — будьте аккуратны с лимитами (флуд = бан на часы).
