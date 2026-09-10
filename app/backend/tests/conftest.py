"""Инфраструктура тестов — общие фикстуры для всего пакета tests/.

Отдельная БД в ТОМ ЖЕ Postgres-инстансе (notenotes_test, роль notenotes
переиспользована) — не второй инстанс (CLAUDE.md: второй Postgres на 4 ГБ
VPS не влезет), тот же принцип, каким заводили бы базу для чужого
приложения. DATABASE_URL подменяется на тестовую БД ДО импорта любых
app.*-модулей — движок в app/db.py создаётся на уровне модуля при
импорте, поэтому переменную окружения нужно выставить первой же строкой,
раньше даже сбора тестов pytest'ом.
"""
import os
import tempfile

_test_db_url = os.environ["DATABASE_URL"].rsplit("/", 1)[0] + "/notenotes_test"
os.environ["DATABASE_URL"] = _test_db_url
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="notenotes-test-uploads-")

import asyncio  # noqa: E402
import uuid  # noqa: E402
from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.db import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import create_session_token, hash_password  # noqa: E402


def _alembic_config() -> Config:
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(backend_dir, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
    cfg.set_main_option("sqlalchemy.url", _test_db_url.replace("+asyncpg", ""))
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_db():
    """Настоящие alembic-миграции на тестовую БД — тот же принцип, что
    CLAUDE.md требует для миграций в проде ("тест на копии"): раз в
    сессию тестов, не на каждый тест (изоляция между тестами — через
    откат транзакции в db_session ниже, не пересоздание схемы)."""
    command.upgrade(_alembic_config(), "head")
    yield
    command.downgrade(_alembic_config(), "base")


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Счётчики частоты — модульные, то есть общие на весь прогон.

    Без сброса тесты мешают друг другу: проверка «лимит срабатывает»
    выжигает бюджет, и следующий тест, честно регистрирующий клиента,
    получает 429 вместо 201. Поймано ровно так — пятнадцатью красными
    тестами, ни один из которых не был про частоту.

    Не сам лимитер виноват: в проде счётчик и должен переживать запросы.
    Это цена того, что он в памяти процесса (см. app/rate_limit.py, почему
    не Redis).
    """
    from app.rate_limit import _hits

    _hits.clear()
    yield
    _hits.clear()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator:
    """Один тест — одна транзакция, которая всегда откатывается в конце.
    session.commit() внутри кода приложения создаёт SAVEPOINT
    (join_transaction_mode="create_savepoint", SQLAlchemy 2.0+), а не
    коммитит по-настоящему — реальный откат внешней транзакции в finally
    гарантированно возвращает БД в чистое состояние, даже если сам тест
    упал с исключением."""
    async with engine.connect() as conn:
        trans = await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with session_factory() as session:
            yield session
        await trans.rollback()


@pytest_asyncio.fixture
async def _client_factory(db_session) -> AsyncGenerator:
    """Реальный найденный баг первой версии этих фикстур: client и
    auth_client были буквально ОДНИМ И ТЕМ ЖЕ httpx.AsyncClient (auth_client
    просто дописывал куку поверх client) — тест, запросивший ОБА параметра
    сразу (например, "аноним видит X, авторизованный видит Y" в одной
    функции), на деле получал два имени для одного и того же уже
    авторизованного объекта: фикстуры pytest резолвятся до тела теста,
    порядок обращения внутри функции роли не играет. Фабрика ниже создаёт
    НЕЗАВИСИМЫЕ httpx-клиенты (свои cookie jar у каждого), которые делят
    только db_session — то есть одну и ту же транзакцию/видимость БД,
    что и нужно."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    created: list[AsyncClient] = []

    def make() -> AsyncClient:
        transport = ASGITransport(app=app)
        # https://, не http:// — сессионная кука выставляется с Secure (см.
        # routers/auth.py::_set_session_cookie, осознанно, для прода). httpx
        # честно соблюдает флаг Secure и молча не пришлёт такую куку обратно
        # на http://-origin — без этого /auth/me после регистрации/логина
        # ловил бы 401 из-за самого тестового клиента, не из-за бага в коде.
        c = AsyncClient(transport=transport, base_url="https://test")
        created.append(c)
        return c

    yield make

    for c in created:
        await c.aclose()
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def client(_client_factory) -> AsyncClient:
    return _client_factory()


@pytest_asyncio.fixture
async def test_user(db_session) -> User:
    user = User(username=f"test_{uuid.uuid4().hex[:8]}", password_hash=hash_password("testpass123"), name="Test User")
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def auth_client(_client_factory, test_user: User) -> AsyncClient:
    c = _client_factory()
    c.cookies.set("notenotes_session", create_session_token(test_user.id))
    return c


@pytest_asyncio.fixture
async def live_server(_client_factory) -> AsyncGenerator[str, None]:
    """Настоящий uvicorn на локальном порту, в ТОМ ЖЕ event loop'е, что и
    остальные async-фикстуры — только для WS-эндпоинтов. httpx/ASGITransport
    не тестировался под WebSocket в этом раунде; starlette.testclient.TestClient
    поддерживает WS, но поднимает соединение в СВОЁМ отдельном потоке со
    своим loop'ом — на практике это ровно тот же класс проблем ("different
    loop"/MissingGreenlet), что уже ловили сегодня при живой отладке
    коллаборации. Настоящий сервер в этом же процессе и loop'е избегает
    этого класса багов целиком: WS-хэндлеры видят тот же
    app.dependency_overrides[get_db], что и обычные HTTP-тесты (см.
    _client_factory), сессия/транзакция общая, как и везде."""
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.get_event_loop().create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"ws://127.0.0.1:{port}"
    server.should_exit = True
    await task


@pytest.fixture(scope="session")
def event_loop():
    # Реальный найденный при первом прогоне баг: без этого pytest-asyncio
    # создаёт НОВЫЙ event loop на каждую тест-функцию (scope по умолчанию —
    # function), а app.db.engine — модульный синглтон, созданный один раз
    # при импорте и намертво привязанный к ТОМУ event loop'у, что был
    # активен в момент импорта; переиспользование его пула соединений в
    # другом loop роняет asyncpg ("attached to a different loop"). Да,
    # pytest-asyncio считает переопределение этой фикстуры устаревшим —
    # альтернатива (asyncio_default_fixture_loop_scope в pytest.ini)
    # покрывает только фикстуры, не сами тест-функции, и не решает
    # проблему целиком; рабочий вариант важнее отсутствия warning'а.
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


