"""векторный индекс для семантического поиска (ТЗ §10)

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-07

Полнотекстовый поиск работает на конфигурации 'simple' — без словаря, то
есть без морфологии: «купить», «покупка» и «закупка» для него три разных
слова. Выбрано это сознательно (в базе перемешаны русский, польский и
английский, и ни один словарь не подошёл бы всем), но цена — поиск не
находит по смыслу. Векторный поиск решает морфологию, синонимы и
разноязычность разом; pgvector 0.8.6 стоит в базе с самого начала и до
сих пор не использовался нигде.

ОТДЕЛЬНАЯ ТАБЛИЦА, а не колонка `embedding` в items, как предполагает
ТЗ §3.2. Причина: у mistral-embed лимит 8192 токена, а 26 заметок из 206
длиннее 8000 символов — их приходится резать на куски, и связь становится
1:N, в колонку не помещается. Правилу «одна универсальная таблица items,
не заводи отдельные таблицы под типы контента» это не противоречит:
таблица описывает не тип контента, а индекс над ним.

content_hash рядом с вектором — не оптимизация, а условие
работоспособности. Очередь на индексацию живёт в памяти процесса (тот же
приём, что у автотегов), и при перезапуске теряется. С хэшем одним
запросом находится всё, что не проиндексировано или устарело: это разом
закрывает первичное заполнение существующих записей, перезапуск и правку
заметки.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# mistral-embed. Размерность зашита в схему таблицы, поэтому смена модели
# на другую размерность потребует миграции и переиндексации — это
# осознанно: pgvector требует фиксированной размерности для индекса.
EMBEDDING_DIM = 1024


def upgrade() -> None:
    op.execute("create extension if not exists vector")
    op.create_table(
        "item_embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "item_id",
            sa.Uuid(),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Порядковый номер куска. Короткая заметка — единственный кусок с
        # номером 0; длинная режется на несколько.
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        # Текст куска хранится рядом: он нужен, чтобы показать пользователю
        # ИМЕННО ту часть длинной заметки, которая совпала по смыслу, а не
        # начало документа. Без него семантический результат по заметке на
        # 80 тысяч символов был бы бесполезен — непонятно, что там нашлось.
        sa.Column("chunk_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("embedding", sa.dialects.postgresql.ARRAY(sa.Float), nullable=True),
        # sha256 от текста, из которого считались векторы этого item'а.
        # Одинаков у всех кусков одной записи — сравнивается с хэшем
        # текущего содержимого, чтобы понять, устарел ли индекс.
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # Настоящий тип vector ставим отдельным ALTER: sa.dialects.postgresql
    # не знает про pgvector, а тянуть зависимость pgvector-python ради
    # одной колонки не хочется — запросы всё равно пишутся явным SQL.
    op.execute(f"alter table item_embeddings alter column embedding type vector({EMBEDDING_DIM}) using null")

    op.create_index("ix_item_embeddings_item_id", "item_embeddings", ["item_id"])
    op.create_unique_constraint(
        "uq_item_embeddings_item_chunk", "item_embeddings", ["item_id", "chunk_index"]
    )

    # HNSW, не IVFFlat: IVFFlat требует обучения на уже загруженных данных
    # (без них качество поиска падает), а база пустая на момент миграции и
    # наполняется постепенно. HNSW строится инкрементально и не требует
    # переобучения. vector_cosine_ops — mistral-embed нормализован, косинус
    # и есть штатная метрика.
    #
    # Размер индекса на нынешних объёмах пренебрежим (сотни векторов по
    # 1024 float = единицы мегабайт), что важно при потолке в 4 ГБ памяти.
    op.execute(
        "create index ix_item_embeddings_vector on item_embeddings "
        "using hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_item_embeddings_vector", table_name="item_embeddings")
    op.drop_constraint("uq_item_embeddings_item_chunk", "item_embeddings", type_="unique")
    op.drop_index("ix_item_embeddings_item_id", table_name="item_embeddings")
    op.drop_table("item_embeddings")
