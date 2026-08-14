# ===== ProbivBot: образ для деплоя =====
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/Moscow

WORKDIR /app

# PhoneInfoga (Linux amd64) — глубокий поиск по телефону должен работать на сервере.
# Официальный релиз: https://github.com/sundowndev/phoneinfoga/releases
ARG PHONEINFOGA_VERSION=v2.11.0
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates tzdata \
    && curl -fsSL \
       "https://github.com/sundowndev/phoneinfoga/releases/download/${PHONEINFOGA_VERSION}/phoneinfoga_Linux_x86_64.tar.gz" \
       -o /tmp/phoneinfoga.tar.gz \
    && mkdir -p /tmp/pinf \
    && tar -xzf /tmp/phoneinfoga.tar.gz -C /tmp/pinf \
    && find /tmp/pinf -type f -name 'phoneinfoga' -exec mv {} /usr/local/bin/phoneinfoga \; \
    && chmod +x /usr/local/bin/phoneinfoga \
    && /usr/local/bin/phoneinfoga version \
    && rm -rf /tmp/phoneinfoga.tar.gz /tmp/pinf \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY bot ./bot
COPY tests ./tests
COPY main.py .
COPY entrypoint.sh .

RUN chmod +x entrypoint.sh

EXPOSE 8080

CMD ["./entrypoint.sh"]