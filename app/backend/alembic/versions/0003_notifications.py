"""notifications

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-07

Центр уведомлений (ТЗ §13). Реальных событий-источников (приглашения в
спейсы, изменения в списках) пока нет — таблица заведена заранее, первый
потребитель — клиентское уведомление о новой версии фронтенда (само оно
не пишется в эту таблицу, синтетическое на клиенте, см. useVersionCheck).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade() -> None:
    op.drop_table("notifications")
