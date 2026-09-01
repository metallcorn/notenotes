"""per-user home timezone

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-01

Домашний (стабильный) часовой пояс пользователя — отдельно от живого
пояса браузера (заголовок X-Client-Timezone). См. app/user_timezone.py.
Дефолт совпадает с прежним хардкодом (Europe/Warsaw) — для существующих
пользователей поведение не меняется, пока они не поменяют пояс в
Настройках.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/Warsaw"),
    )


def downgrade() -> None:
    op.drop_column("users", "timezone")
