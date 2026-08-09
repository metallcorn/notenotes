"""debug_log table

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-09

Точечная диагностика бага "белый экран в standalone PWA на Android
Firefox" (не воспроизводится в песочнице) — клиент сам шлёт сюда
состояние экрана в момент перехода. Временная таблица под одно
расследование, не общий механизм логирования.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "debug_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event", sa.String(100), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_debug_log_created_at", "debug_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_debug_log_created_at", table_name="debug_log")
    op.drop_table("debug_log")
