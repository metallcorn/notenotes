"""per-user disabled assistant skills

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-07

Настройка «Умения ассистента» — список имён тулов, которые пользователь
выключил в настройках (см. app/tools/registry.py). Пустой список — всё
включено по умолчанию, ничего не ломает для существующих пользователей.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("disabled_tools", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("users", "disabled_tools")
