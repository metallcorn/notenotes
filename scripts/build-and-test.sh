#!/usr/bin/env bash
# Синхронизация + сборка нового образа + прогон pytest ПРОТИВ ЭТОГО НОВОГО
# образа (не против уже запущенного контейнера — тестируем код, который
# вот-вот пойдёт в прод, а не тот, что уже там). Общая для двух точек
# входа: scripts/git-hooks/pre-push (тестирует то, что собираешься
# запушить) и scripts/deploy.sh (тестирует то, что вот-вот задеплоишь) —
# намеренно одна и та же логика, чтобы не разъезжались.
#
# Живой прод-контейнер этим скриптом не трогается вообще — docker compose
# build не перезапускает уже работающий сервис (это делает отдельно
# `docker compose up`, только в deploy.sh, только после успешных тестов).
set -euo pipefail

# Уборка кэша сборки — ВСЕГДА, даже если тесты упали. Раньше кэш чистил
# только deploy.sh, а до него при красных тестах дело не доходило: каждая
# неудачная сборка оставляла слои навсегда. Именно buildx и именно -af —
# см. deploy.sh, почему (там же про то, как `docker builder prune` и
# размерные флаги молча не чистили ничего).
trap 'sudo docker buildx prune -af >/dev/null 2>&1 || true' EXIT

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Какой коммит проверяем — только если рабочее дерево чистое: тесты гоняют
# то, что лежит на диске, и отметка «коммит X проверен» при незакоммиченных
# правках была бы враньём. Отметку читает pre-push (см. там, зачем).
TESTED_SHA=""
if [ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
  TESTED_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
fi

echo "==> Синхронизация кода в /srv/notenotes/app"
sudo rsync -a --delete \
  --exclude=node_modules --exclude=dist --exclude=__pycache__ --exclude=.venv --exclude='*.pyc' \
  "$REPO_ROOT/app/" /srv/notenotes/app/

# Тестовые контейнеры — с жёстким потолком по памяти и CPU. Они идут на
# том же хосте, где работает приложение, а на 4 ГБ каждый лишний гигабайт
# уходит в своп. Дважды (19 августа и 11 сентября) сервер зависал ровно
# под этим скриптом.
#
# Почему именно лимиты контейнеров, а не nice/ionice на команде: nice
# ограничил бы docker-КЛИЕНТ, а работу делает демон — это другой процесс,
# и приоритет ему не передаётся. Первая правка была ровно такой и не
# делала ничего.
#
# Сборку образа (docker compose build) так ограничить нельзя — она идёт
# внутри buildkit. Для неё настоящая защита другая: своп не на loop-файле
# в LUKS (см. инцидент 2026-09-11 и роль platform).
TEST_LIMITS="--memory 768m --memory-swap 768m --cpus 1.5"

echo "==> Frontend-тесты (vitest) — до сборки образа, чтобы не ждать зря при падении"
sudo docker run --rm $TEST_LIMITS \
  -v "$REPO_ROOT/app/frontend:/app/frontend" \
  -w /app/frontend \
  node:20-alpine sh -c "npm install --silent && npm run test"
echo "==> Frontend-тесты прошли"

echo "==> Сборка образа backend (не трогает работающий контейнер)"
# --pull обязателен. Без него docker берёт закэшированный базовый образ и
# держит его месяцами: 12.10 внутри собранного образа ждали 16 обновлений,
# среди них OpenSSL из stable-security. Цена — изредка перекачать 190 МБ
# базового образа, и это дешевле, чем жить с непропатченным OpenSSL.
(cd /srv/notenotes/compose && sudo docker compose build --pull backend)

echo "==> Тесты на СОБРАННОМ образе, изолированная notenotes_test БД"
(
  cd /srv/notenotes/compose
  # Лимиты сюда передавать не надо: compose run наследует mem_limit: 768m
  # из описания сервиса backend в docker-compose.yml.
  sudo docker compose run --rm \
    -v "$REPO_ROOT/app/backend/tests:/app/tests:ro" \
    -v "$REPO_ROOT/app/backend/pytest.ini:/app/pytest.ini:ro" \
    -v "$REPO_ROOT/app/backend/requirements-dev.txt:/app/requirements-dev.txt:ro" \
    --entrypoint sh \
    backend -c "pip install --quiet -r requirements-dev.txt && python3 -m pytest -q"
)
echo "==> Тесты прошли"
if [ -n "$TESTED_SHA" ]; then
  touch "$(git -C "$REPO_ROOT" rev-parse --git-dir)/notenotes-tested-$TESTED_SHA"
fi
