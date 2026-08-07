"""telegram bot link tables

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-07

Привязка Telegram-аккаунта к notenotes-пользователю через простой Bot API
(не MTProto) — ТЗ, Фаза 2 «Каналы». telegram_links: одна запись на
пользователя, chat_id уникален. telegram_link_codes: одноразовые
короткоживущие коды для /start в боте.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_links",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index("ix_telegram_links_chat_id", "telegram_links", ["chat_id"], unique=True)

    op.create_table(
        "telegram_link_codes",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_index("ix_telegram_link_codes_user_id", "telegram_link_codes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_telegram_link_codes_user_id", table_name="telegram_link_codes")
    op.drop_table("telegram_link_codes")
    op.drop_index("ix_telegram_links_chat_id", table_name="telegram_links")
    op.drop_table("telegram_links")
