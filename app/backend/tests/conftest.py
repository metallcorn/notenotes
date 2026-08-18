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
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    # https://, не http:// — сессионная кука выставляется с Secure (см.
    # routers/auth.py::_set_session_cookie, осознанно, для прода). httpx
    # честно соблюдает флаг Secure и молча не пришлёт такую куку обратно
    # на http://-origin — без этого /auth/me после регистрации/логина
    # ловил бы 401 из-за самого тестового клиента, не из-за бага в коде.
    async with AsyncClient(transport=transport, base_url="https://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def test_user(db_session) -> User:
    user = User(username=f"test_{uuid.uuid4().hex[:8]}", password_hash=hash_password("testpass123"), name="Test User")
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient, test_user: User) -> AsyncClient:
    token = create_session_token(test_user.id)
    client.cookies.set("notenotes_session", token)
    return client


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


