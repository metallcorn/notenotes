#!/usr/bin/env bash
# Единая точка деплоя — заменяет ручную последовательность rsync/build/up,
# которую раньше гоняли по шагам вручную. Тесты — обязательный гейт:
# если pytest падает, до `docker compose up` дело не доходит, живой
# контейнер не трогается вообще.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$REPO_ROOT/scripts/build-and-test.sh"

echo "==> Разворачиваем"
(cd /srv/notenotes/compose && sudo docker compose up -d --wait)

# Транзиентный 502 сразу после up -d — норма (contain er swap), не сразу
# считаем провалом (см. reference_deploy_workflow в памяти сессий).
sleep 3
code=$(curl -s -o /dev/null -w "%{http_code}" https://notenotes.metallcorn.online/api/health || echo "000")
if [ "$code" != "200" ]; then
  sleep 3
  code=$(curl -s -o /dev/null -w "%{http_code}" https://notenotes.metallcorn.online/api/health || echo "000")
fi
echo "==> health: $code"
[ "$code" = "200" ]
