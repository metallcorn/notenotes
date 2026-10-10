import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

# Alembic (в отличие от uvicorn) не добавляет рабочую директорию в sys.path
# сам — без этой строки `from app...` ниже падает с ModuleNotFoundError,
# как бы ни был вызван alembic (CLI, `python -m alembic`, `docker compose exec`).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db import Base
from app import models  # noqa: F401  — регистрирует модели в Base.metadata

config = context.config
# disable_existing_loggers=False — иначе fileConfig ВЫКЛЮЧАЕТ все уже
# созданные логгеры, а не просто настраивает свои. По умолчанию он делает
# именно это, и в alembic.ini флага нет.
#
# Чем это вышло наружу: в тестах миграции идут в том же процессе
# (conftest._migrate_test_db), поэтому после них logger.disabled == True у
# всего app.*, и ни одна проверка на запись в журнал не могла сработать —
# caplog.records оставался пустым при живом logger.error. Поймано 10.10
# на тесте, который проверял, что тело ошибки провайдера попадает в лог.
# В проде миграции идут отдельным процессом до uvicorn, поэтому там это не
# проявлялось — то есть ловушка была ровно в том месте, где её не видно.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
