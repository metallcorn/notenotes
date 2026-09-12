"""утренняя сводка: время и отметка отправки

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-12

Запрос владельца: в установленное время (по умолчанию 9 утра) получать в
Telegram «что у меня сегодня» — напоминания и события, распознанные в
заметках, с кнопками «сделано» / «не актуально» прямо в сообщении.

digest_time — локальное время в поясе User.timezone, строкой «HH:MM».
NULL = выключено. Одно поле вместо bool + time: «включено, но без времени»
состояния не имеет смысла.

digest_sent_on — локальная дата последней отправки. Воркер проверяет
каждую минуту; без отметки слал бы в 09:00, 09:01, 09:02 и ещё раз после
перезапуска.

По умолчанию 09:00 для всех: сводка приходит только если есть что
показать и есть куда (Telegram или push), так что для тех, у кого пусто,
это ноль сообщений.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("digest_time", sa.String(5), nullable=True, server_default="09:00"))
    op.add_column("users", sa.Column("digest_sent_on", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "digest_sent_on")
    op.drop_column("users", "digest_time")
