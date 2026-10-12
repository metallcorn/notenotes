"""дедупликация файлов по содержимому

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-12

ЗАМЕР, из которого выросла правка: из 355 загруженных файлов 71 оказался
побайтовым дубликатом — 49 групп, каждый пятый файл. Почти всё это
месячные пакеты от бухгалтера, приходящие повторно: «ZUS DRA 07-2026.pdf»
лежал в пяти экземплярах с 19.08 по 01.10, в спейсах «Почта» и «Личное».

Сравнивать их было нечем: в таблице не было ни хэша, ни размера.

sha256 nullable и с индексом: у файлов, залитых до этой правки, хэша нет
(досчитывается отдельным проходом, не на миграции — 427 МБ на 4 ГБ VPS),
а индекс нужен на каждом приёме файла, то есть на горячем пути.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("uploads", sa.Column("sha256", sa.String(64), nullable=True))
    op.add_column("uploads", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.create_index("ix_uploads_sha256", "uploads", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_uploads_sha256", table_name="uploads")
    op.drop_column("uploads", "size_bytes")
    op.drop_column("uploads", "sha256")
