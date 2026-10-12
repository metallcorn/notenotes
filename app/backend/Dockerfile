# Собирается с контекстом = корень репозитория (см. docker-compose.yml.j2),
# чтобы эта стадия могла увидеть app/frontend.
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY app/frontend/package.json app/frontend/package-lock.json ./
# package-lock.json теперь закоммичен (появился при установке vitest/RTL для
# фронтенд-тестов, 2026-08-19) — npm ci быстрее и, в отличие от npm install,
# гарантированно ставит РОВНО то, что в лок-файле, не пересчитывая дерево
# зависимостей заново при каждой сборке.
RUN npm ci
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
# tesseract-ocr(-osd) — только для определения ориентации фото/скана перед
# OCR/vision-LLM (app/rotation.py) — механический анализ формы символов
# (Tesseract OSD), не полноценное распознавание текста, поэтому языковые
# пакеты (rus/eng) не нужны, хватает osd.traineddata. Реальный найденный
# случай: перевёрнутая на 90° страница скана — vision-модель читает текст
# криво и путает содержимое (например, регион в штампе), а Tesseract OSD
# определяет угол поворота локально и бесплатно ещё до отправки в LLM.
# apt-get upgrade, а не только install — и это не лишняя строка.
#
# Проверено 12.10: внутри собранного образа 16 пакетов ждали обновления, в
# том числе из stable-security — libssl3t64 (OpenSSL), libpcre2-8-0,
# liblzma5. Базовый образ python:3.12-slim собирают по расписанию, и между
# его сборками патчи Debian в него не попадают; `docker compose build` без
# --pull вообще брал закэшированный образ пятинедельной давности.
#
# Лечится двумя мерами вместе: --pull при сборке (scripts/build-and-test.sh)
# тянет свежий базовый образ, а upgrade здесь добирает то, что вышло после
# его сборки. По отдельности каждая оставляет щель.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr tesseract-ocr-osd \
    && rm -rf /var/lib/apt/lists/*
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
