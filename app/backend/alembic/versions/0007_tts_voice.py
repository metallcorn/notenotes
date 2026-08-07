"""per-user TTS voice preference

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-07

"default_low"/"default_high" — единственные два built-in голоса Palabra
(мужской/женский по факту, не "стили" — уточнено по документации).
Значение — просто voice_id как есть: тот же формат для built-in пресетов
и для собственного id голоса с Palabra Platform, разбирать строку не
нужно.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("tts_voice", sa.String(length=128), nullable=False, server_default="default_low"),
    )


def downgrade() -> None:
    op.drop_column("users", "tts_voice")
