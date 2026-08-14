"""Тесты SQLite-БД (временная БД, оффлайн)."""
from __future__ import annotations

from bot.db import ProbivDB


def _fresh_db(tmp_path):
    return ProbivDB(tmp_path / "test.db")


def test_upsert_user_and_count(tmp_path):
    db = _fresh_db(tmp_path)
    db.upsert_user(111, "alex", "Alex", "Petrov")
    db.upsert_user(111, "alex", "Alex", "Petrov")  # повтор — не дубликат
    db.upsert_user(222, "bob")
    assert db.stats()["users"] == 2


def test_log_search_and_history(tmp_path):
    db = _fresh_db(tmp_path)
    db.upsert_user(111, "alex")
    db.log_search(111, "phone", "all", "+375291234567", "ok", report="<b>report</b>")
    db.log_search(111, "username", "sherlock", "alex", "partial")
    db.log_search(111, "email", "holehe", "a@b.co", "error", error="timeout")

    rows = db.history(111, limit=10)
    assert len(rows) == 3
    assert rows[0].category == "email"   # сортировка DESC
    assert rows[0].status == "error"
    assert rows[-1].target == "+375291234567"

    # отчёт сохранён
    assert db.get_report(rows[-1].id) == "<b>report</b>"

    s = db.stats()
    assert s["searches"] == 3
    assert s["by_category"]["phone"] == 1
    assert s["by_status"]["ok"] == 1


def test_history_limit(tmp_path):
    db = _fresh_db(tmp_path)
    db.upsert_user(1)
    for i in range(15):
        db.log_search(1, "phone", "all", f"+3752912345{i:02d}", "ok")
    assert len(db.history(1, limit=5)) == 5


def test_empty_history(tmp_path):
    db = _fresh_db(tmp_path)
    assert db.history(999, limit=10) == []