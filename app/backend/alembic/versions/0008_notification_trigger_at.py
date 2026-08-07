"""scheduled reminders via notifications.trigger_at

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-07

Напоминания ассистента (по просьбе — как /remind в Slack) переиспользуют
существующий центр уведомлений (ТЗ §13), а не заводят отдельную таблицу.
trigger_at NULL — обычное немедленное уведомление, как раньше; трэи с
будущей датой просто не отдаются списком, пока время не наступит (см.
routers/notifications.py) — планировщика/воркера для этого не требуется,
достаточно фильтра в выборке.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("trigger_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_notifications_trigger_at", "notifications", ["trigger_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_trigger_at", table_name="notifications")
    op.drop_column("notifications", "trigger_at")
