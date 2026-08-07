"""video transcription status/text on uploads

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-07

Расшифровка речи из видео (Deepgram, с диаризацией) — по просьбе
пользователя: "до 10 МБ на распознавание, статус обработки нужен".
status: none (по умолчанию, не видео/аудио) | pending | processing |
done | failed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "uploads", sa.Column("transcription_status", sa.String(length=20), nullable=False, server_default="none")
    )
    op.add_column("uploads", sa.Column("transcript", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("uploads", "transcript")
    op.drop_column("uploads", "transcription_status")
