"""add llm_provider to users — per-user LLM provider override for live A/B comparison

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-10

Живой переключатель провайдера ассистента (Mistral/Gemini) в настройках,
без передеплоя — пустая строка означает "использовать глобальный дефолт
из LLM_PROVIDER" (см. app/llm/factory.py).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("llm_provider", sa.String(length=32), nullable=False, server_default="")
    )


def downgrade() -> None:
    op.drop_column("users", "llm_provider")
