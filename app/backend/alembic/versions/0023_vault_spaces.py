"""vault spaces — client-side E2E-encrypted space type

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-14

Сейф (ТЗ §16.2, Фаза 4 раньше срока): is_vault + соль/verifier для
клиентского E2E-шифрования. Сервер хранит только непрозрачные значения —
vault_salt не секрет (нужна для передеривации ключа), vault_verifier —
известная строка, зашифрованная ключом сейфа (для проверки пароля на
клиенте без обращения к серверу).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "spaces", sa.Column("is_vault", sa.Boolean(), nullable=False, server_default="false")
    )
    op.add_column("spaces", sa.Column("vault_salt", sa.String(64), nullable=True))
    op.add_column("spaces", sa.Column("vault_verifier", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("spaces", "vault_verifier")
    op.drop_column("spaces", "vault_salt")
    op.drop_column("spaces", "is_vault")
