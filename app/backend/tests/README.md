# Тесты

pytest, реальная БД (не моки) — отдельная `notenotes_test` в ТОМ ЖЕ
Postgres-инстансе (второй инстанс на 4 ГБ VPS не влезает, см. CLAUDE.md),
роль `notenotes` переиспользована. Изоляция между тестами — не
пересозданием схемы, а откатом транзакции после каждого теста
(`tests/conftest.py::db_session`).

Тесты сознательно НЕ входят в production-образ (Dockerfile копирует
только `app/`, `alembic/`, `alembic.ini`) — не нужны в проде, лишний вес.

## Разовая настройка (один раз на инстанс Postgres)

```bash
sudo docker exec notenotes-postgres-1 psql -U notenotes -d postgres \
  -c "CREATE DATABASE notenotes_test OWNER notenotes;"
sudo docker exec notenotes-postgres-1 psql -U notenotes -d notenotes_test -c "
  CREATE EXTENSION IF NOT EXISTS vector;
  CREATE EXTENSION IF NOT EXISTS pg_trgm;
  CREATE EXTENSION IF NOT EXISTS unaccent;
"
```

Расширения — не через alembic-миграции (0001_initial.py на них
полагается, но САМИ их не создаёт): в проде их ставит Ansible
(`infra/roles/notenotes_stack/files/01-extensions.sql`), для тестовой БД
это нужно повторить руками один раз.

## Запуск

Тестовые файлы и зависимости не в образе — перед прогоном скопировать в
уже запущенный контейнер и поставить `requirements-dev.txt` (pytest,
pytest-asyncio поверх обычных зависимостей):

```bash
sudo docker cp app/backend/tests notenotes-backend-1:/app/tests
sudo docker cp app/backend/pytest.ini notenotes-backend-1:/app/pytest.ini
sudo docker cp app/backend/requirements-dev.txt notenotes-backend-1:/app/requirements-dev.txt
sudo docker exec notenotes-backend-1 pip install --quiet -r /app/requirements-dev.txt
sudo docker exec -w /app notenotes-backend-1 python3 -m pytest -q
```

Прогон безопасен для прод-данных: `conftest.py` подменяет `DATABASE_URL`
на `notenotes_test` ДО импорта любых `app.*`-модулей (движок в `app/db.py`
создаётся при импорте) — реальная БД `notenotes` вообще не открывается
тестовым процессом.

## Что покрыто (v1)

Auth (регистрация/логин/сессия), spaces (создание, сейф, публичные
страницы, участники, инвайты), items (CRUD, версии, перенос между
спейсами, публикация/снятие с публикации), uploads (лимиты 20 МБ/файл,
100 МБ суммарно на заметку), public.py (весь анонимный флоу — пароль,
однократность, доступ к вложениям).

**Не покрыто пока:** WebSocket-эндпоинты (совместное редактирование,
списки, уведомления) — `httpx.ASGITransport` не тестировался под
WebSocket в этом раунде, живая проверка (см. историю сессии) остаётся
основным способом; AI-ассистент и прочие LLM-зависимые пути (дорого и
недетерминированно гонять в обычном прогоне).
