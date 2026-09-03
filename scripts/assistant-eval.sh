#!/usr/bin/env bash
# Ролплей-оценка ассистента: одна LLM играет живого пользователя, вторая
# судит transcript вместе с вызовами инструментов.
#
# НЕ в гейте деплоя — как и e2e-test.sh: стоит реальных денег (десятки
# вызовов LLM) и минут. Запускается руками, когда надо померить, а не
# перед каждой выкладкой.
#
# Изоляция — тот же приём, что у e2e-test.sh, но БД СВОЯ:
#   - одноразовый контейнер того же образа, БД notenotes_eval (не боевая и
#     не notenotes_test). Отдельная база не прихоть: pytest в conftest.py
#     пересоздаёт таблицы в notenotes_test на старте, и параллельный запуск
#     build-and-test.sh посреди прогона оценки убивает обоих — поймано
#     живьём при первом же запуске ("relation items does not exist" в
#     оценке и упавший тест в pytest);
#   - LLM_API_KEY ОСТАВЛЕН намеренно (без него мерить нечего), но
#     TELEGRAM_* обнулён — иначе старт мог бы перерегистрировать боевой
#     вебхук на этот контейнер; TAVILY тоже обнулён, потому что web_search
#     внутри всё равно застаблен (у пользователя 1000 запросов в месяц);
#   - контейнер не подключается к сети edge и не получает alias
#     notenotes-backend — иначе коллизия по DNS с живым бэкендом;
#   - код оценки монтируется read-only, как tests/ в build-and-test.sh, и
#     не попадает в прод-образ.
# Боевой контейнер и боевая БД этим скриптом не трогаются.
#
# Примеры:
#   scripts/assistant-eval.sh                                  # базовый замер
#   scripts/assistant-eval.sh --variant plan_prompt             # вариант B
#   scripts/assistant-eval.sh --variant magistral --runs 5      # вариант A
#   scripts/assistant-eval.sh --scenario newbie_onboarding      # один сценарий
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_ENV="/srv/encrypted/notenotes/secrets/app.env"
STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT_DIR="$REPO_ROOT/.eval-reports"
REPORT_NAME="eval-${STAMP}.md"

echo "==> Синхронизация кода в /srv/notenotes/app"
sudo rsync -a --delete \
  --exclude=node_modules --exclude=dist --exclude=__pycache__ --exclude=.venv --exclude='*.pyc' \
  "$REPO_ROOT/app/" /srv/notenotes/app/

echo "==> Сборка образа backend (переиспользует кэш, если код не менялся)"
(cd /srv/notenotes/compose && sudo docker compose build backend)

# DATABASE_URL из реального app.env с подменённым именем БД — тот же приём,
# что в tests/conftest.py и e2e-test.sh. Значение никуда не печатается.
EVAL_DB_URL="$(sudo sh -c "grep '^DATABASE_URL=' '$SECRETS_ENV' | cut -d= -f2-" | sed -E 's#(.*)/[^/]+$#\1/notenotes_eval#')"

echo "==> Проверяем БД notenotes_eval (создаём при первом запуске)"
(
  cd /srv/notenotes/compose
  # CREATE DATABASE не умеет IF NOT EXISTS — проверяем наличие отдельно.
  if ! sudo docker compose exec -T postgres \
      psql -U notenotes -d postgres -tAc \
      "select 1 from pg_database where datname='notenotes_eval'" | grep -q 1; then
    sudo docker compose exec -T postgres \
      psql -U notenotes -d postgres -c "create database notenotes_eval" >/dev/null
    echo "    создана"
  fi
  # Расширения ставятся в КАЖДУЮ базу отдельно, не на инстанс: свежая база
  # получает только plpgsql, а миграция 0001 сразу падает на
  # 'text search dictionary "public.unaccent" does not exist' (поймано
  # живьём). Набор — тот же, что в боевой БД.
  sudo docker compose exec -T postgres psql -U notenotes -d notenotes_eval -q \
    -c "create extension if not exists unaccent" \
    -c "create extension if not exists pg_trgm" \
    -c "create extension if not exists vector" >/dev/null
)

mkdir -p "$REPORT_DIR"

echo "==> Прогон (БД notenotes_eval, боевая и notenotes_test не трогаются)"
sudo docker run --rm \
  --network notenotes_internal \
  --env-file "$SECRETS_ENV" \
  -e DATABASE_URL="$EVAL_DB_URL" \
  -e TAVILY_API_KEY= \
  -e TELEGRAM_BOT_TOKEN= -e TELEGRAM_BOT_USERNAME= -e TELEGRAM_WEBHOOK_SECRET= \
  -e DEEPGRAM_API_KEY= -e PALABRA_API_KEY= \
  -e VAPID_PRIVATE_KEY= -e VAPID_PUBLIC_KEY= \
  -v "$REPO_ROOT/app/backend/eval:/app/eval:ro" \
  -v "$REPORT_DIR:/reports" \
  --memory 768m \
  --entrypoint sh \
  notenotes-backend \
  -c "alembic upgrade head >/dev/null && python3 -m eval.runner --out /reports/${REPORT_NAME} $*"

echo "==> Отчёт: $REPORT_DIR/$REPORT_NAME"
