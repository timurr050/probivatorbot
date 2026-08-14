"""Проверка БД: запись, история, статистика."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.db import DB

DB.upsert_user(42, "demo", "Demo", "User")
DB.log_search(42, "phone", "all", "+12125654777", "ok", report="<b>phone report</b>")
DB.log_search(42, "phone", "tg", "+12125654777", "error", error="Telethon не настроен")
DB.log_search(42, "email", "holehe", "test@mail.ru", "ok", report="<b>email report</b>")

print("--- HISTORY (42) ---")
for r in DB.history(42, limit=5):
    print(f"#{r.id} {r.category}/{r.tool} {r.target} [{r.status}] {r.created_at}")

rep = DB.get_report(DB.history(42, limit=100)[0].id)
print("\nreport #last:", rep)

print("\n--- STATS ---")
print(DB.stats())
print("\nDB path:", DB_PATH)