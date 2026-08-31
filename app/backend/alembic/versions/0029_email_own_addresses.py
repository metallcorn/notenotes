"""email_inboxes.own_addresses — свои внешние email-адреса пользователя

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-31

Реальная жалоба: пересылаешь себе письмо на notenotes-адрес — папка
называется по собственному имени пользователя (это ОН прислал письмо на
приёмный адрес), а не по реальному отправителю оригинала. Чтобы отличить
"это письмо переслал/скопировал себе я сам" от "это письмо от постороннего",
нужно явно знать, какие внешние адреса принадлежат пользователю — раньше
такого не было нигде (User email не хранит вовсе). Пустой список — ничего
не меняет для существующих пользователей, пока они не добавят адрес в
настройках.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "email_inboxes",
        sa.Column("own_addresses", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("email_inboxes", "own_addresses")
