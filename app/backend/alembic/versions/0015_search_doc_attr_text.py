"""include data-text attribute content in full-text search

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-08

DocumentAttachment (см. extensions/DocumentAttachment.ts) хранит распознанный
текст PDF в HTML-атрибуте data-text — обнаружено (ts_debug), что PostgreSQL
распознаёт <div ...> как единый XML-тег и полностью исключает его из
to_tsvector (категория "tag", без словаря) — весь текст внутри атрибута был
невидим для поиска, хотя визуально хранился как обычный текст в content.
notenotes_extract_attr_text вытаскивает значения data-text="..." отдельно и
добавляет их в индексируемый документ.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION notenotes_extract_attr_text(input text)
        RETURNS text AS $$
            SELECT coalesce(string_agg(m[1], ' '), '')
            FROM regexp_matches(input, 'data-text="([^"]*)"', 'g') AS m
        $$ LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_items_search")
    op.execute(
        """
        CREATE INDEX ix_items_search ON items
        USING gin (to_tsvector('simple', notenotes_immutable_unaccent(
            coalesce(title, '') || ' ' || coalesce(content, '') || ' ' || notenotes_extract_attr_text(coalesce(content, ''))
        )))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_items_search")
    op.execute(
        """
        CREATE INDEX ix_items_search ON items
        USING gin (to_tsvector('simple', notenotes_immutable_unaccent(coalesce(title, '') || ' ' || coalesce(content, ''))))
        """
    )
    op.execute("DROP FUNCTION IF EXISTS notenotes_extract_attr_text(text)")
