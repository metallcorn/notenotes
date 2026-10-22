"""значок спейса и ручной порядок спейсов у участника

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-22

Замечание владельца после редизайна: спейсу нужен свой значок (как у папок
в 0039), а порядок спейсов — свой у каждого участника, чтобы редкий сейф
можно было утащить вниз. Оба поля nullable: старые данные без изменений.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("spaces", sa.Column("icon", sa.String(length=16), nullable=True))
    op.add_column("space_members", sa.Column("position", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("space_members", "position")
    op.drop_column("spaces", "icon")
