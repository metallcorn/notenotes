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

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Синхронизация кода в /srv/notenotes/app"
sudo rsync -a --delete \
  --exclude=node_modules --exclude=dist --exclude=__pycache__ --exclude=.venv --exclude='*.pyc' \
  "$REPO_ROOT/app/" /srv/notenotes/app/

echo "==> Сборка образа backend (не трогает работающий контейнер)"
(cd /srv/notenotes/compose && sudo docker compose build backend)

echo "==> Тесты на СОБРАННОМ образе, изолированная notenotes_test БД"
(
  cd /srv/notenotes/compose
  sudo docker compose run --rm \
    -v "$REPO_ROOT/app/backend/tests:/app/tests:ro" \
    -v "$REPO_ROOT/app/backend/pytest.ini:/app/pytest.ini:ro" \
    -v "$REPO_ROOT/app/backend/requirements-dev.txt:/app/requirements-dev.txt:ro" \
    --entrypoint sh \
    backend -c "pip install --quiet -r requirements-dev.txt && python3 -m pytest -q"
)
echo "==> Тесты прошли"
