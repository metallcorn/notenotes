#!/usr/bin/env bash
# Единая точка деплоя — заменяет ручную последовательность rsync/build/up,
# которую раньше гоняли по шагам вручную. Тесты — обязательный гейт:
# если pytest падает, до `docker compose up` дело не доходит, живой
# контейнер не трогается вообще.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Реальный найденный инцидент: этот скрипт делает `docker compose up -d`
# НАПРЯМУЮ, в обход notenotes.service (systemd) — а именно там живёт
# единственная защита от главной ловушки инфраструктуры (infra/README.md):
# если /srv/encrypted не смонтирован после ребута/зависания хоста, Postgres
# в контейнере тихо инициализирует ПУСТОЙ кластер поверх точки монтирования
# на обычном (незашифрованном) диске — реальные данные при этом не
# трогаются, просто становятся недоступны, а прод работает на пустой базе,
# пока кто-то не заметит. systemd-юнит перед стартом гоняет
# encrypted-preflight ИМЕННО за этим — деплой-скрипт этого не делал никогда.
if ! mountpoint -q /srv/encrypted; then
  echo "==> /srv/encrypted не смонтирован — том закрыт после ребута/зависания хоста."
  echo "    Разворачивать сейчас значит поднять Postgres поверх пустого каталога."
  echo "    Сначала: cd infra && make unlock (или sudo encrypted-unlock), потом деплой заново."
  exit 1
fi

"$REPO_ROOT/scripts/build-and-test.sh"

echo "==> Разворачиваем"
(cd /srv/notenotes/compose && sudo docker compose up -d --wait)

# Build-кэш BuildKit растёт без ограничения с каждым деплоем (реальный
# найденный случай: 9+ ГБ за один рабочий вечер, диск дошёл до 85%) —
# оставляем только кэш младше суток, этого достаточно, чтобы повторный
# деплой в тот же день собирался быстро, но не копится неделями.
# Кэш сборки — ПО ОБЪЁМУ, а не по возрасту. Раньше стояло --filter
# until=24h, и это не работало: в день с пятнадцатью сборками весь кэш
# «свежий», и не удалялось ничего — накопилось 10 ГБ на диске, где живёт
# и loop-файл LUKS (инцидент 2026-09-11). Один гигабайт хватает, чтобы
# повторная сборка шла быстро; всё сверх — мусор.
docker builder prune -f --keep-storage 1G >/dev/null 2>&1 || true
docker image prune -f >/dev/null 2>&1 || true

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
