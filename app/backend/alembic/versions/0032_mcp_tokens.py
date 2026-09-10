"""личные токены для доступа к базе по MCP

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-10

Попасть в свою базу можно было только через веб и Telegram-бота. MCP
открывает её внешним ассистентам (Claude Code, claude.ai) — слой
инструментов для этого давно готов и вынесен (app/tools/registry.py: 40
инструментов, JSON Schema, единый dispatch), не хватало только протокола
и способа аутентифицировать машину.

Сессионной куки для машины мало: у неё нет браузера, нет срока жизни под
контролем пользователя и нет отзыва по одной штуке. Отсюда отдельная
таблица.

Храним ХЭШ токена, не сам токен — по образцу пароля. Утечка дампа БД не
должна открывать доступ к заметкам, а восстанавливать плейнтекст нам
незачем: он показывается один раз при создании.

space_id nullable и обычно пуст: пусто = писать в «домашний» спейс, тот
же, что выбирает Telegram-бот (_default_space_id в routers/dialogs.py —
самый старый не-сейф спейс). Заводить выбор при создании токена значило
бы требовать решения на пустом месте; поле оставлено на случай, когда
дефолт окажется не тем местом.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        # Чтобы человек отличал «ноутбук» от «телефона» в списке и понимал,
        # какой именно отзывать.
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("token_hash", sa.String(255), nullable=False),
        # ondelete=SET NULL, не CASCADE: удаление спейса не должно молча
        # отзывать токен — он вернётся к поведению по умолчанию.
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Единственный способ заметить забытый или утёкший токен: если им
        # никто не пользовался месяц, пора отзывать.
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        # Отзыв, а не удаление строки: по last_used_at видно, ходил ли
        # кто-то этим токеном уже ПОСЛЕ отзыва.
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    # unique, а не просто index: коллизия хэшей означала бы, что один токен
    # открывает чужую базу. Вероятность ничтожна, цена — нет.
    op.create_index("ix_mcp_tokens_token_hash", "mcp_tokens", ["token_hash"], unique=True)
    op.create_index("ix_mcp_tokens_user_id", "mcp_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_tokens_user_id", table_name="mcp_tokens")
    op.drop_index("ix_mcp_tokens_token_hash", table_name="mcp_tokens")
    op.drop_table("mcp_tokens")
