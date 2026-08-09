"""index individual words inside URLs for full-text search

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-09

Два реальных случая, оба обнаружены живьём при проверке поиска:

1. Заметки, чей title — голая ссылка (обычная заметка из Telegram, см.
   _derive_title в telegram_bot.py, "https://www.zalando.pl/zarko...html")
   индексируются PostgreSQL как ОДИН compound-токен ('www.zalando.pl',
   весь путь и т.д.) — не отдельные слова. Поиск "zalando" не находит
   такую заметку: ':*'-префикс ищет токен, НАЧИНАЮЩИЙСЯ на "zalando", а
   токен целиком "www.zalando.pl".
2. Хуже: ссылка внутри <a href="..." data-linkpreview></a> (карточка сайта,
   LinkPreview.ts/_linkify_bare_urls в telegram_bot.py) вообще НЕВИДИМА
   для to_tsvector — PostgreSQL распознаёт <a ...></a> как HTML-тег
   (категория "tag", без словаря) и полностью исключает содержимое, тот же
   механизм, что уже чинили для <div data-doc-attachment> в 0015.

notenotes_urlsplit достаёт все http(s)-ссылки из сырого текста (title||
content — regexp_matches работает на исходной строке ДО to_tsvector,
поэтому HTML-тегов вокруг ссылки для него не существует) и заменяет
URL-разделители на пробелы, чтобы каждое слово внутри ссылки стало
отдельным токеном. Добавляется В ДОПОЛНЕНИЕ к существующему тексту, не
вместо — обычная (не URL) индексация не меняется.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION notenotes_urlsplit(input text)
        RETURNS text AS $$
            SELECT coalesce(string_agg(regexp_replace(m[1], '[/:.\\-_?=&%#@]+', ' ', 'g'), ' '), '')
            FROM regexp_matches(input, 'https?://([^\\s"<>]+)', 'g') AS m
        $$ LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
        """
    )
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


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_items_search")
    op.execute(
        """
        CREATE INDEX ix_items_search ON items
        USING gin (to_tsvector('simple', notenotes_immutable_unaccent(
            coalesce(title, '') || ' ' || coalesce(content, '') || ' ' || notenotes_extract_attr_text(coalesce(content, ''))
        )))
        """
    )
    op.execute("DROP FUNCTION IF EXISTS notenotes_urlsplit(text)")
