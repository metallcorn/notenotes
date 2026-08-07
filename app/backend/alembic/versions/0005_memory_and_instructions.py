"""assistant memory + custom instructions

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-07

Память ассистента между диалогами и пользовательские инструкции для него
(ТЗ §10a — расширение AI-ассистента, обсуждено с пользователем в сессии).
assistant_memories — отдельная таблица, а не items: это не пользовательский
контент базы (как заметки), а служебные факты о том, как ассистенту вести
себя с этим пользователем — та же логика, что уже применена к Feedback и
Notification.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assistant_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_assistant_memories_user_id", "assistant_memories", ["user_id"])
    op.create_index("ix_assistant_memories_created_at", "assistant_memories", ["created_at"])
    op.add_column("users", sa.Column("custom_instructions", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("users", "custom_instructions")
    op.drop_table("assistant_memories")
