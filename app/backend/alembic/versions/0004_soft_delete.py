"""soft delete for items

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-07

Мягкое удаление items. Повод: AI-ассистент (ТЗ §10a/§10b) получает право
на delete_note — цена ошибки модели резко выше, чем у случайного клика
человека. deleted_at IS NULL = не удалена; списки/поиск по умолчанию его
фильтруют, корзина показывает обратное, безвозвратное удаление — отдельное
явное действие.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("items", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_items_deleted_at", "items", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_items_deleted_at", table_name="items")
    op.drop_column("items", "deleted_at")
