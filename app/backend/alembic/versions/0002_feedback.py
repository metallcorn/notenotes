"""feedback widget

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-06

Плавающая кнопка отзыва в UI: текст + скриншот текущей страницы. Отдельная
таблица, а не material_type в items — это данные о продукте, а не
пользовательский контент базы, и к спейсу не привязано.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("page_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("screenshot_filename", sa.String(255), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_feedback_created_at", "feedback", ["created_at"])


def downgrade() -> None:
    op.drop_table("feedback")
