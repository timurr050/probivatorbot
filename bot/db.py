"""
Локальная SQLite-БД для логирования активности.

Хранит:
  * users     — телеграм-пользователей (кто пользовался ботом);
  * searches  — каждый прогон: категория, движок, цель, статус, ошибка, отчёт, время.

БД лежит в data/probivbot.db. Работа синхронная (быстрые операции) с блокировкой,
чтобы не конфликтовать между обработчиками одного event-loop.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "probivbot.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY,
    username       TEXT,
    first_name     TEXT,
    last_name      TEXT,
    is_premium     INTEGER DEFAULT 0,
    first_seen     TEXT DEFAULT (datetime('now','localtime')),
    last_seen      TEXT DEFAULT (datetime('now','localtime')),
    searches_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS searches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    category    TEXT,
    tool        TEXT,
    target      TEXT,
    status      TEXT,            -- ok | partial | error
    error       TEXT,
    report      TEXT,            -- полный HTML-отчёт
    summary     TEXT,            -- доп. структура (JSON), например число найденных
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_searches_user ON searches(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_searches_category ON searches(category);
"""


@dataclass
class SearchRow:
    """Строка из таблицы searches."""

    id: int
    user_id: int
    category: str
    tool: str
    target: str
    status: str
    error: Optional[str]
    created_at: str


class ProbivDB:
    def __init__(self, path: Path = DB_PATH):
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ users

    def upsert_user(self, user_id: int, username: str = "",
                    first_name: str = "", last_name: str = "",
                    is_premium: bool = False) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO users(id, username, first_name, last_name, is_premium,
                                  first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, datetime('now','localtime'), datetime('now','localtime'))
                ON CONFLICT(id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    last_name=excluded.last_name,
                    is_premium=excluded.is_premium,
                    last_seen=datetime('now','localtime')
                """,
                (user_id, username, first_name, last_name, int(is_premium)),
            )
            self._conn.commit()

    # ---------------------------------------------------------------- searches

    def log_search(self, user_id: int, category: str, tool: str, target: str,
                   status: str, error: Optional[str] = None,
                   report: Optional[str] = None, summary: Optional[dict] = None) -> None:
        """Записывает прогон поиска. summary — доп. структура (например, число найденных)."""
        payload = None
        if summary:
            payload = json.dumps(summary, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO searches(user_id, category, tool, target, status, error, report, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, category, tool, target, status, error, report, payload),
            )
            self._conn.execute(
                "UPDATE users SET searches_count = searches_count + 1 WHERE id = ?",
                (user_id,),
            )
            self._conn.commit()

    def history(self, user_id: int, limit: int = 10) -> list[SearchRow]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, user_id, category, tool, target, status, error, created_at
                FROM searches WHERE user_id = ? ORDER BY id DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [
            SearchRow(
                id=r["id"], user_id=r["user_id"], category=r["category"],
                tool=r["tool"], target=r["target"], status=r["status"],
                error=r["error"], created_at=r["created_at"],
            )
            for r in rows
        ]

    def get_report(self, search_id: int) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT report FROM searches WHERE id = ?", (search_id,)
            ).fetchone()
        return row["report"] if row else None

    # ------------------------------------------------------------------- stats

    def stats(self) -> dict:
        with self._lock:
            users = self._conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            searches = self._conn.execute("SELECT COUNT(*) c FROM searches").fetchone()["c"]
            by_category = dict(
                self._conn.execute(
                    "SELECT category, COUNT(*) c FROM searches GROUP BY category"
                ).fetchall()
            )
            by_status = dict(
                self._conn.execute(
                    "SELECT status, COUNT(*) c FROM searches GROUP BY status"
                ).fetchall()
            )
        return {
            "users": users,
            "searches": searches,
            "by_category": by_category,
            "by_status": by_status,
        }


# Единый инстанс для всего процесса
DB = ProbivDB()