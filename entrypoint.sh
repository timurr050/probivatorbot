#!/bin/sh
set -e

mkdir -p data/telegram_sessions

if [ "${RUN_TESTS_ON_START:-false}" = "true" ]; then
  echo ">> Запускаю тесты..."
  python -m pytest tests -q || { echo "Тесты не прошли, бот не запускается."; exit 1; }
  echo ">> Тесты пройдены."
fi

echo ">> ProbivBot стартует..."
exec python -u main.py