"""notifications.dispatched_at

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-09

Метка "уже отправлено во внешние каналы" (Telegram/Web Push) — диспетчер
(app/backend/app/notification_dispatch.py) ищет строки с dispatched_at IS
NULL и trigger_at наступившим, шлёт, проставляет. NULL — ещё не
отправлено (в т.ч. все существующие строки на момент миграции).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "dispatched_at")
