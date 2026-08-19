#!/usr/bin/env bash
# Playwright E2E против настоящего запущенного бэкенда — НЕ против прода.
# Поднимает ОДНОРАЗОВЫЙ контейнер того же образа notenotes-backend, но:
#   - DATABASE_URL указывает на notenotes_test (та же изолированная БД,
#     которой уже пользуется pytest — см. tests/conftest.py), не на
#     боевую notenotes;
#   - все внешние ключи (LLM/Tavily/Deepgram/Palabra/Telegram/VAPID)
#     обнулены явно, даже если реальный app.env их даёт — иначе
#     lifespan-старт настоящего uvicorn (в отличие от pytest, тут он
#     реально запускается) вызвал бы register_webhook() и перерегистрировал
#     БОЕВОЙ Telegram-вебхук на этот одноразовый контейнер;
#   - контейнер НЕ подключается к сети edge и не получает alias
#     notenotes-backend — коллизия с живым бэкендом по DNS (см. CLAUDE.md
#     про общую сеть edge), порт наружу торчит только на 127.0.0.1.
# Прод-контейнер этим скриптом не трогается вообще: другое имя контейнера,
# другая БД, никакой сети edge.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER_NAME="notenotes-e2e-backend"
HOST_PORT=8811
SECRETS_ENV="/srv/encrypted/notenotes/secrets/app.env"

cleanup() {
  sudo docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Синхронизация кода в /srv/notenotes/app (сборка идёт оттуда, не отсюда)"
sudo rsync -a --delete \
  --exclude=node_modules --exclude=dist --exclude=__pycache__ --exclude=.venv --exclude='*.pyc' \
  "$REPO_ROOT/app/" /srv/notenotes/app/

echo "==> Сборка образа backend (переиспользует кэш, если код не менялся)"
(cd /srv/notenotes/compose && sudo docker compose build backend)

echo "==> Поднимаем изолированный e2e-бэкенд на notenotes_test, без внешних ключей"
cleanup
# DATABASE_URL из реального app.env, но с подменённым именем БД — тот же
# приём, что tests/conftest.py делает для pytest (rsplit по последнему "/").
# Значение не печатается никуда, только передаётся дальше в docker run.
TEST_DB_URL="$(sudo sh -c "grep '^DATABASE_URL=' '$SECRETS_ENV' | cut -d= -f2-" | sed -E 's#(.*)/[^/]+$#\1/notenotes_test#')"

sudo docker run -d \
  --name "$CONTAINER_NAME" \
  --network notenotes_internal \
  -p "127.0.0.1:${HOST_PORT}:8000" \
  --env-file "$SECRETS_ENV" \
  -e DATABASE_URL="$TEST_DB_URL" \
  -e PUBLIC_BASE_URL="http://127.0.0.1:${HOST_PORT}" \
  -e LLM_API_KEY= -e GEMINI_API_KEY= -e GROQ_API_KEY= -e TAVILY_API_KEY= \
  -e DEEPGRAM_API_KEY= -e PALABRA_API_KEY= \
  -e TELEGRAM_BOT_TOKEN= -e TELEGRAM_BOT_USERNAME= -e TELEGRAM_WEBHOOK_SECRET= \
  -e VAPID_PRIVATE_KEY= -e VAPID_PUBLIC_KEY= \
  -e SESSION_COOKIE_SECURE=false \
  --memory 768m \
  notenotes-backend >/dev/null

echo "==> Ждём готовности (alembic upgrade head внутри контейнера может занять время)"
for _ in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${HOST_PORT}/api/health" || echo 000)
  [ "$code" = "200" ] && break
  sleep 1
done
if [ "$code" != "200" ]; then
  echo "==> e2e-бэкенд не поднялся, логи:"
  sudo docker logs "$CONTAINER_NAME" | tail -60
  exit 1
fi

echo "==> Сеем/чистим фиксированного тестового пользователя в notenotes_test"
sudo docker exec -i "$CONTAINER_NAME" python3 - <<'PY'
import asyncio
from sqlalchemy import delete, select
from app.db import async_session
from app.models import Folder, Item, Space, SpaceMember, User
from app.security import hash_password

USERNAME = "e2e_test"
PASSWORD = "e2e_test_password_123"


async def main():
    async with async_session() as db:
        existing = (await db.execute(select(User).where(User.username == USERNAME))).scalar_one_or_none()
        if existing is None:
            user = User(username=USERNAME, password_hash=hash_password(PASSWORD), name="E2E Test")
            db.add(user)
            await db.flush()
            space = Space(name="Личное", owner_id=user.id)
            db.add(space)
            await db.flush()
            db.add(SpaceMember(space_id=space.id, user_id=user.id))
            await db.commit()
            print(f"created user={user.id}")
            return

        # Пользователь/спейс с прошлого прогона остаются (id стабилен для
        # storageState в Playwright) — чистим только контент, чтобы каждый
        # прогон стартовал с чистого листа.
        spaces = (await db.execute(select(Space).where(Space.owner_id == existing.id))).scalars().all()
        space_ids = [s.id for s in spaces]
        if space_ids:
            await db.execute(delete(Item).where(Item.space_id.in_(space_ids)))
            await db.execute(delete(Folder).where(Folder.space_id.in_(space_ids)))
            await db.commit()
        print(f"reused user={existing.id}")


asyncio.run(main())
PY

echo "==> Прогоняем Playwright"
# Версия образа ДОЛЖНА совпадать с версией @playwright/test в package.json
# (закреплена там без ^ ровно поэтому) — иначе браузер внутри образа не
# совпадает с версией, под которую собран тестовый раннер, и всё падает
# с "Executable doesn't exist".
sudo docker run --rm \
  --network notenotes_internal \
  -v "$REPO_ROOT/app/frontend:/work" \
  -w /work \
  -e BASE_URL="http://${CONTAINER_NAME}:8000" \
  -e CI=1 \
  mcr.microsoft.com/playwright:v1.62.1-noble \
  sh -c "npm install --silent && npx playwright test"

echo "==> Playwright прошёл"
