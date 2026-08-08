"""link previews cache

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-08

Кэш метаданных сайта для карточек ссылок в редакторе (Slack-style unfurl).
Не items — служебный кэш, не пользовательский контент.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "link_previews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("favicon_url", sa.Text(), nullable=True),
        sa.Column("fetch_failed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_link_previews_url", "link_previews", ["url"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_link_previews_url", table_name="link_previews")
    op.drop_table("link_previews")
