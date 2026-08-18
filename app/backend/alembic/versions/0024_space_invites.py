"""space_invites table — link-based invites into a shared space

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-18

Отдельно от invite_codes (та — про регистрацию нового пользователя вообще,
эта — про вступление уже зарегистрированного в конкретный спейс). Часть
фичи "шареные спейсы": равные права на редактирование уже есть у
участников (ensure_space_access), не хватало только способа кого-то
добавить.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "space_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_space_invites_space_id", "space_invites", ["space_id"])
    op.create_index("ix_space_invites_token", "space_invites", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_space_invites_token", table_name="space_invites")
    op.drop_index("ix_space_invites_space_id", table_name="space_invites")
    op.drop_table("space_invites")
