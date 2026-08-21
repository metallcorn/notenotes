"""delivery_widgets — постоянный виджет отслеживания доставки в заметке

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-21

По образцу url_check_widgets (0027): в content заметки лежит только
data-delivery-id, а мутируемое состояние (перевозчик, трек-номер и
нормализованный результат последнего опроса) — здесь. «Обновить» пишет
только эту строку, не трогая content/Yjs/ItemVersion. CASCADE на item —
виджет умирает вместе с заметкой.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "delivery_widgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("carrier", sa.Text(), nullable=False),
        sa.Column("tracking_number", sa.Text(), nullable=False),
        # Нормализованный результат delivery.track (JSON-строка) — то же,
        # что рисует карточка в чате, чтобы виджет и чат показывали одно и то же.
        sa.Column("last_result", sa.Text(), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_widgets_item_id", "delivery_widgets", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_delivery_widgets_item_id", table_name="delivery_widgets")
    op.drop_table("delivery_widgets")
