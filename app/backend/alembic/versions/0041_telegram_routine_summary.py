"""дневная сводка приёмов в Telegram: где она лежит у пользователя

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-30

Жалоба владельца 30.10: рутины работают отлично, но Telegram-чат с ботом
забит закрытыми пингами «✓ дал в 22:09», и полезное среди них не найти.
Теперь закрытый пинг удаляется, а в чате живёт одно сообщение на день —
сводка приёмов, которая перерисовывается при каждой отметке. Чтобы
перерисовать, надо помнить, какое сообщение и за какой день: это поле.
JSONB {"date": "2026-10-30", "message_id": 123}, nullable — у кого сводки
ещё не было, там NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("telegram_links", sa.Column("routine_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("telegram_links", "routine_summary")
