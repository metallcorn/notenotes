# Собирается с контекстом = корень репозитория (см. docker-compose.yml.j2),
# чтобы эта стадия могла увидеть app/frontend.
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY app/frontend/package.json app/frontend/package-lock.json* ./
# npm ci потребовал бы закоммиченный package-lock.json — его пока нет
# (нет локального Node, чтобы его сгенерировать). Как появится — переключить.
RUN npm install
COPY app/frontend/ ./
# Лимит памяти: vite build рядом с Postgres на 4 ГБ RAM — точка риска (CLAUDE.md).
ENV NODE_OPTIONS=--max-old-space-size=1024
RUN npm run build

FROM python:3.12-slim AS backend
WORKDIR /app
# Непривилегированный юзер для тула run_python (app/tools/python_sandbox.py) —
# сам backend-процесс остаётся root (нужно, чтобы уметь дропнуть привилегии
# в форкнутом ребёнке через setuid/setgid), а код модели выполняется под ним.
RUN useradd --no-create-home --uid 10001 --shell /usr/sbin/nologin sandbox
# ffmpeg — извлечь звук из видео перед распознаванием речи (app/transcription.py).
# Только бинарь, без демона — память ест лишь пока реально идёт транскод,
# а очередь обрабатывает видео по одному, так что пиковая память предсказуема.
# QR/штрихкод-декодирование (app/tickets.py) — zxing-cpp, у него
# самодостаточное wheel-колесо (без внешней .so, в отличие от pyzbar/zbar,
# который был здесь раньше и не умел Aztec — формат, в который почти все
# авиабилеты кодируют посадочный талон), системный пакет не нужен вовсе.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY app/backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app/backend/app ./app
COPY app/backend/alembic ./alembic
COPY app/backend/alembic.ini ./
COPY --from=frontend-builder /app/frontend/dist ./app/static

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
