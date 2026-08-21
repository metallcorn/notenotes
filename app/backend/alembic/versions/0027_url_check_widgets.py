"""url_check_widgets — состояние виджета «Проверить по ссылке» вне content

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-21

Раньше url/поля/заголовки авторизации/тело последнего ответа (до 512 КБ)
лежали прямо в content заметки — заголовки открытым текстом видны всем с
доступом к спейсу, а каждый "Обновить" раздувал ItemVersion этим же
блобом. Теперь в заметке только data-url-check-id, вся мутируемая
часть — здесь (см. models.py::UrlCheckWidget).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "url_check_widgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_result", sa.Text(), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_url_check_widgets_item_id", "url_check_widgets", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_url_check_widgets_item_id", table_name="url_check_widgets")
    op.drop_table("url_check_widgets")
