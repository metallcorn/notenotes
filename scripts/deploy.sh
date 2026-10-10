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

# Кэш сборки: `docker buildx prune -af`, и это третья попытка — две
# предыдущие молча не работали.
#
#   1. --filter until=24h: в день с пятнадцатью сборками весь кэш
#      «свежий», не удалялось ничего.
#   2. `docker builder prune -f --keep-storage 1G`: флаг признан
#      устаревшим («keep-storage flag has been changed to
#      reserved-space»), а сама команда на этом движке НЕ ВИДИТ кэш
#      BuildKit: при 9.843 ГБ reclaimable по `docker buildx du` она
#      отвечает «Total: 0B» и не освобождает ничего. Так и накопилось
#      11 ГБ в /var/lib/containerd — на том же диске, где лежит
#      loop-файл LUKS (инцидент 2026-09-11). Проверено 10.10: диск был
#      на 75%.
#
# Размерных ограничений здесь не осталось вовсе: --reserved-space и
# --max-used-space на этом движке тоже отвечают «0B» (проверено). Зато
# `buildx prune -af` чистит ровно мусор и ничего кроме: записи, нужные
# текущему образу, помечены Shared и не удаляются — после полной чистки
# в кэше осталось 1.84 ГБ, и это слои живого notenotes-backend.
#
# Полная чистка ничего не стоит по времени, и это ЗАМЕРЕНО, а не
# предположено: прогон build-and-test сразу после `-af` занял 200.56 с
# против 196–204 с на прогретом кэше. Дорогие слои (pip install) лежат в
# самом образе, а не в кэше сборки.
docker buildx prune -af >/dev/null 2>&1 || true
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
