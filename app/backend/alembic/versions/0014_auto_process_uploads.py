"""auto_process_uploads setting on users

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-08

Гейтит авто-обработку загрузок (OCR картинок, расшифровка видео, авто-OCR
PDF-сканов) — по умолчанию включена.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auto_process_uploads", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("users", "auto_process_uploads")
