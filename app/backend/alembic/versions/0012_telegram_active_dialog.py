"""active dialog on telegram_links

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-08

Разговор с ассистентом через Telegram-бота: NULL значит следующее текстовое
сообщение начнёт новый диалог лениво, /new сбрасывает обратно в NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("telegram_links", sa.Column("active_dialog_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_telegram_links_active_dialog_id",
        "telegram_links",
        "items",
        ["active_dialog_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_telegram_links_active_dialog_id", "telegram_links", type_="foreignkey")
    op.drop_column("telegram_links", "active_dialog_id")
