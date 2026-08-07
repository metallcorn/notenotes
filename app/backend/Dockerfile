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
