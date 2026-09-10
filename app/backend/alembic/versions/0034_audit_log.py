"""аудит действий с доступом к базе

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-10

События про доступ (выдача и отзыв токенов, подключения по OAuth, вызовы
инструментов через MCP) писались только в stdout. Docker крутит логи по
10 МБ × 3 — след живёт дни, а вопрос «кто и когда подключался к моей
базе» задают через месяцы. Плюс в логе всё вперемешку с access-строками и
ищется только grep'ом по тексту.

Неудачные попытки входа не писались ВООБЩЕ: перебор токенов не оставлял
никакого следа.

Здесь только имя события и идентификаторы — ни содержимого заметок, ни
аргументов инструментов, ни токенов. Иначе аудит стал бы вторым местом,
где лежат личные данные, и защищать пришлось бы уже его (CLAUDE.md: PII
не должна расползаться).

Срок хранения — 180 дней, чистится тем же периодическим уборщиком, что и
корзина. Это и есть ротация, только с понятным сроком, а не «сколько
влезло в 30 МБ».
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # nullable: у неудачной попытки входа пользователя нет, а записать
        # её надо именно ради этого случая.
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False, server_default=""),
        sa.Column("source", sa.String(64), nullable=False, server_default=""),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # По пользователю и времени — так его читают в настройках; по событию —
    # так его читают, когда что-то случилось.
    op.create_index("ix_audit_user_time", "audit_log", ["user_id", "created_at"])
    op.create_index("ix_audit_event", "audit_log", ["event"])
    op.create_index("ix_audit_created", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_created", table_name="audit_log")
    op.drop_index("ix_audit_event", table_name="audit_log")
    op.drop_index("ix_audit_user_time", table_name="audit_log")
    op.drop_table("audit_log")
