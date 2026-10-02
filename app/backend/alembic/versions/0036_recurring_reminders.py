"""повторяющиеся напоминания

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-02

Запрос владельца: «каждый понедельник», «раз в месяц оплатить» —
приходилось заводить заново, все напоминания были одноразовыми.

Правило хранится на самом напоминании, а не отдельной таблицей
«расписаний»: активна всегда ровно одна будущая копия, и после отправки
она порождает следующую. Отдельная сущность потребовала бы держать две
записи в согласии там, где хватает одной, и расходилась бы ровно при
переносе и отмене.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("repeat_rule", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "repeat_rule")
