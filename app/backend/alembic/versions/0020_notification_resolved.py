"""add resolved_at to notifications — done/active is not the same as past/future

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-09

Реальная жалоба: напоминание с уже прошедшим trigger_at пользователь
мысленно всё равно считает "активным", пока не отметил сделанным явно —
центр активности путал "время сработало" с "решено". resolved_at — новая
независимая ось: NULL = активное (вне зависимости от trigger_at), с датой
= выполнено.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "resolved_at")
