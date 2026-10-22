"""эмодзи-значок у папки

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-22

Редизайн по макетам 21.10: папка в списке показывается с эмодзи-плиткой,
как заметка (items.icon). Nullable — у старых папок значка нет, в
интерфейсе вместо него нейтральная плитка.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("folders", sa.Column("icon", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("folders", "icon")
