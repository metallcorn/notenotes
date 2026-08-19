"""email_inboxes — персональный адрес для приёма почты

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-19

Приём писем на уникальный непубличный адрес как заметки (см.
routers/mail.py, routers/mail_webhook.py) — по образцу telegram_links.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_inboxes",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("local_part", sa.String(length=32), nullable=False),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index("ix_email_inboxes_local_part", "email_inboxes", ["local_part"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_email_inboxes_local_part", table_name="email_inboxes")
    op.drop_table("email_inboxes")
