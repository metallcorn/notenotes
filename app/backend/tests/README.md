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

Проще всего — `scripts/build-and-test.sh` из корня репозитория (собирает
свежий образ и гоняет тесты против НЕГО, не против уже работающего
контейнера): используется и `scripts/deploy.sh`, и git-хуком
`scripts/git-hooks/pre-push` (`git config core.hooksPath scripts/git-hooks`
включает его). Тестовые файлы монтируются как read-only volume через
`docker compose run`, requirements-dev.txt ставится внутри одноразового
контейнера — сам prod-образ ими не раздувается.

Вручную, против уже запущенного контейнера (быстрее при итерации на
одном и том же тесте):

```bash
sudo docker exec notenotes-backend-1 rm -rf /app/tests   # если уже копировали раньше
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

## Что покрыто

108 тестов, весь HTTP- и WS-роутинг, кроме явно перечисленного ниже как
непокрытое: auth (включая rate-limit на login, инвайт-коды, PATCH /me),
spaces (сейф, публичные страницы, участники, инвайты — включая истёкшие,
ротация пароля сейфа, переименование), items (CRUD, список по space/
folder/tag, /recent, версии + откат, detected-events, публикация), uploads
(лимиты 20 МБ/100 МБ, превью, диктофонная запись start/chunk, staged
только для сейфа), folders, tags (включая слияние), lists (CRUD +
записи), notifications, push, memories, skills, feedback, debug-log
(включая rate-limit), calendar, search (включая транслитерацию и
исключение сейфа), link-preview/url-checks (SSRF-блокировка — без
единого реального сетевого запроса), telegram (link-code), public.py
(весь анонимный флоу). WebSocket: space/list/notifications/collab —
через `live_server` (настоящий uvicorn в процессе теста, в общем event
loop'е с остальными async-фикстурами; `httpx.ASGITransport` WS не
поддерживает, а `TestClient` поднимает WS в своём отдельном потоке/loop'е
и на практике конфликтует с общей транзакционной db_session).

**Отдельно — граница доступа между спейсами** (`test_access_control.py`):
участник ОДНОГО спейса не может читать/писать заметки, папки, списки и
файлы в спейсе, где он не состоит (items/folders/lists/uploads/spaces) —
самая важная граница безопасности во всём API, раньше не была явно
проверена ни одним тестом.

dialogs.py — только детерминированная часть (создание/список/чтение/
удаление сообщений, без LLM). ai_text.py/voice.py — только авторизация и
валидация до вызова провайдера.

**Сознательно не покрыто:** сама отправка сообщения ассистенту
(`POST /dialogs/{id}/messages`) и любой путь, который реально дёргает
LLM/ASR/TTS-провайдера (Mistral/Gemini/Groq/Deepgram/Palabra) — платно и
недетерминированно гонять в обычном прогоне тестов; потребовало бы
мокать HTTP-клиенты провайдеров, отдельная задача на будущее, если
понадобится.
