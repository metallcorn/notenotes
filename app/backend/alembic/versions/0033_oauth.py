"""OAuth 2.1 для MCP — чтобы заработал claude.ai

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-10

Личного токена (миграция 0032) хватает Claude Code: там его можно вписать
заголовком. claude.ai так не умеет — кастомные коннекторы там подключаются
либо без авторизации вовсе, либо по OAuth. Отсюда эти таблицы.

Мы одновременно и resource server, и authorization server: база
пользователей одна, своя, отдельному серверу авторизации взяться неоткуда.

Access-токенов в базе НЕТ намеренно: это JWT, подпись самодостаточна, а
короткий срок жизни заменяет отзыв. В таблице лежит только refresh — он
живёт долго, поэтому его и нужно уметь отзывать.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Смена схемы хэширования токенов, попутно к OAuth.
    #
    # В 0032 токены хэшировались bcrypt, как пароли. Это было ошибкой:
    # bcrypt намеренно медленный и с индивидуальной солью, поэтому искать
    # по нему нельзя — приходилось тянуть ВСЕ активные строки и проверять
    # по очереди, ~100 мс на строку. Двадцать токенов превратили бы каждый
    # запрос в две секунды и дали бы дешёвый способ положить сервер.
    #
    # Для случайного 256-битного токена медленный хэш и не нужен:
    # перебирать нечего, радужную таблицу не построить. sha256
    # детерминирован, ищется одним индексированным запросом.
    #
    # Старые строки удаляем: их bcrypt-хэши в новой схеме бессмысленны, а
    # сверить нечего — плейнтекста у нас нет. На момент миграции все
    # существующие токены отозваны (единственный был тестовым), так что
    # никого не выкидываем.
    op.execute("delete from mcp_tokens")

    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("client_name", sa.String(255), nullable=False, server_default=""),
        # Фиксируются при регистрации и дальше сверяются побуквенно.
        # Регистрация открытая (иначе claude.ai не подключится), и без
        # этой сверки она превратилась бы в открытый редиректор.
        sa.Column("redirect_uris", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "oauth_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code_hash", sa.String(255), nullable=False),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("oauth_clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        # PKCE обязателен: код проезжает через адресную строку браузера и
        # его историю, перехватить проще, чем кажется.
        sa.Column("code_challenge", sa.String(255), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # Не удаляем строку при обмене: по used_at видно ПОВТОРНУЮ попытку,
        # а она означает кражу.
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_oauth_codes_code_hash", "oauth_codes", ["code_hash"], unique=True)

    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("token_hash", sa.String(255), nullable=False),
        # Цепочка ротаций. Повторное использование потраченного refresh
        # означает копию — тогда убиваем всю семью, а не одну строку.
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("oauth_clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_oauth_refresh_token_hash", "oauth_refresh_tokens", ["token_hash"], unique=True)
    op.create_index("ix_oauth_refresh_family", "oauth_refresh_tokens", ["family_id"])
    op.create_index("ix_oauth_refresh_user", "oauth_refresh_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_oauth_refresh_user", table_name="oauth_refresh_tokens")
    op.drop_index("ix_oauth_refresh_family", table_name="oauth_refresh_tokens")
    op.drop_index("ix_oauth_refresh_token_hash", table_name="oauth_refresh_tokens")
    op.drop_table("oauth_refresh_tokens")
    op.drop_index("ix_oauth_codes_code_hash", table_name="oauth_codes")
    op.drop_table("oauth_codes")
    op.drop_table("oauth_clients")
