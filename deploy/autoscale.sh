#!/usr/bin/env bash
#
# Авто-масштабирование ProbivBot по нагрузке.
#
# Следит за потреблением CPU контейнера(ов) через `docker stats` и меняет
# количество реплик через `docker compose up -d --scale probivbot=N`.
#
# ВАЖНО: реплики работают ТОЛЬКО в webhook-режиме (WEBHOOK_DOMAIN в .env),
# т.к. Telegram разрешает лишь один long-polling клиент на бота (409 Conflict).
# Обновления при webhook-режиме приходят на порт 8080 каждой реплики,
# а снаружи их раздаёт балансировщик/nginx (см. README → «Авто-масштабирование»).
#
# Запуск:  sudo bash deploy/autoscale.sh
#
set -euo pipefail

SERVICE="probivbot"
CPU_HIGH=${CPU_HIGH:-70}          # если CPU выше — поднимаем реплику
CPU_LOW=${CPU_LOW:-20}            # если CPU ниже — убираем лишнюю
MAX_REPLICAS=${MAX_REPLICAS:-3}
MIN_REPLICAS=${MIN_REPLICAS:-1}
CHECK_EVERY=${CHECK_EVERY:-30}    # секунд между проверками

get_cpu() {
  docker stats --no-stream --format "{{.CPUPerc}}" "$SERVICE" 2>/dev/null | tr -d '%' | cut -d. -f1
}

current_replicas() {
  docker compose ps -q "$SERVICE" 2>/dev/null | wc -l
}

scale() {
  local n="$1"
  echo ">> $(date '+%H:%M:%S') CPU=${cpu}% -> scale=$n"
  docker compose up -d --scale "$SERVICE=$n"
}

echo ">> Авто-масштабирование: пороги CPU ${CPU_LOW}%/${CPU_HIGH}%,"
echo "   реплики ${MIN_REPLICAS}..${MAX_REPLICAS}, проверка каждые ${CHECK_EVERY}с."

while true; do
  cpu=$(get_cpu)
  n=$(current_replicas)

  if [ -z "$cpu" ]; then
    echo ">> Контейнер ещё не поднялся, жду..."
  elif [ "$cpu" -ge "$CPU_HIGH" ] && [ "$n" -lt "$MAX_REPLICAS" ]; then
    scale "$((n + 1))"
  elif [ "$cpu" -le "$CPU_LOW" ] && [ "$n" -gt "$MIN_REPLICAS" ]; then
    scale "$((n - 1))"
  fi

  sleep "$CHECK_EVERY"
done
