"""распознанный текст файлов живёт в загрузке, а не в заметке

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-18

ЗАМЕР 18.10: в 94 заметках 184 блока вложений несли распознанный текст
файла в HTML-атрибуте data-text — экранированный (&#10;, &quot;),
невидимый для обычного полнотекста (отсюда notenotes_extract_attr_text в
0015), с датами, до которых не докручивается прокрутка, и с мусором в
напоминаниях. В 155 из них текст побайтово совпадал с uploads.transcript —
то есть хранился дважды.

Эта миграция — только схема:
  * upload_transcript_versions — история распознанного текста (раньше её
    давала история заметки, где лежала копия);
  * ix_uploads_search — полнотекст по имени и тексту файла: заметка теперь
    находится через свои вложения (routers/search.py);
  * ix_items_search — плюс properties.search_keywords: обиходные слова
    билета («авиабилет»), которые раньше приклеивались к OCR-тексту в
    data-text карточки (tickets.py::_SEARCH_SYNONYMS).

Сами заметки чистит отдельный проход app/attachment_text_migration.py:
это правка пользовательских данных, ей нужна версия заметки на каждую
запись и проверка «текст не потерян», а не DDL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upload_transcript_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("upload_id", sa.Uuid(), sa.ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_upload_transcript_versions_upload_id", "upload_transcript_versions", ["upload_id"])
    # Выражение обязано совпадать с routers/search.py::_upload_document байт
    # в байт — иначе postgres не воспользуется индексом.
    op.execute(
        """
        CREATE INDEX ix_uploads_search ON uploads
        USING gin (to_tsvector('simple', notenotes_immutable_unaccent(
            coalesce(filename, '') || ' ' || coalesce(transcript, '')
        )))
        """
    )
    # Ровно то же выражение, что routers/search.py::_document.
    op.execute("DROP INDEX IF EXISTS ix_items_search")
    op.execute(
        """
        CREATE INDEX ix_items_search ON items
        USING gin (to_tsvector('simple', notenotes_immutable_unaccent(
            coalesce(title, '') || ' ' || coalesce(content, '') || ' '
            || notenotes_extract_attr_text(coalesce(content, '')) || ' '
            || notenotes_urlsplit(coalesce(title, '') || ' ' || coalesce(content, '')) || ' '
            || coalesce(properties ->> 'search_keywords', '')
        )))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_items_search")
    op.execute(
        """
        CREATE INDEX ix_items_search ON items
        USING gin (to_tsvector('simple', notenotes_immutable_unaccent(
            coalesce(title, '') || ' ' || coalesce(content, '') || ' '
            || notenotes_extract_attr_text(coalesce(content, '')) || ' '
            || notenotes_urlsplit(coalesce(title, '') || ' ' || coalesce(content, ''))
        )))
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_uploads_search")
    op.drop_index("ix_upload_transcript_versions_upload_id", table_name="upload_transcript_versions")
    op.drop_table("upload_transcript_versions")
