"""auto-tag flag on item_tags

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-07

Авто-теги (ТЗ §8.2, CLAUDE.md): предлагают, а не молча перекладывают —
визуально отличаются от пользовательских тегов и пользователь может их
удалить. auto=false для тегов, добавленных вручную (человеком или по
явной просьбе через ассистента) — только LLM-классификатор
(app/autotag.py) ставит true.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("item_tags", sa.Column("auto", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("item_tags", "auto")
