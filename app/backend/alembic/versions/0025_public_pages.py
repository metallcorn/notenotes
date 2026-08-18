"""public pages — spaces.is_public_pages + items share duration/single-use

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-18

is_public/share_token/share_password_hash уже существовали с миграции
0001, но были мертвы (ничто их не читало/не писало) — этой миграцией
добавляются недостающие поля (срок действия, однократность) и признак
спейса-контейнера публикуемых заметок, оживляющие всю фичу целиком.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "spaces", sa.Column("is_public_pages", sa.Boolean(), nullable=False, server_default="false")
    )
    op.add_column("items", sa.Column("share_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "items", sa.Column("share_single_use", sa.Boolean(), nullable=False, server_default="false")
    )
    op.add_column("items", sa.Column("share_used_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("items", "share_used_at")
    op.drop_column("items", "share_single_use")
    op.drop_column("items", "share_expires_at")
    op.drop_column("spaces", "is_public_pages")
