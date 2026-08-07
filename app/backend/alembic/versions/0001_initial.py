"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-06

Схема по ТЗ §3: универсальная таблица items + типизированные сущности
вокруг неё. user_identities, notifications, sources, embedding — сознательно
не заведены сейчас, см. план v0 (заводятся вместе с фичами, которые их
используют).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "spaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_spaces_owner_id", "spaces", ["owner_id"])

    op.create_table(
        "space_members",
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "folders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "space_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("folders.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_folders_space_id", "folders", ["space_id"])
    op.create_index("ix_folders_parent_id", "folders", ["parent_id"])

    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_tags_user_name"),
    )
    op.create_index("ix_tags_user_id", "tags", ["user_id"])

    op.create_table(
        "uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "space_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_uploads_space_id", "uploads", ["space_id"])

    op.create_table(
        "items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "space_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "folder_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("folders.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("material_type", sa.String(50), nullable=False, server_default="note"),
        sa.Column("title", sa.String(500), nullable=False, server_default=""),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("properties", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("is_public", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("share_token", sa.String(64), nullable=True),
        sa.Column("share_password_hash", sa.String(255), nullable=True),
        sa.Column("share_revoked", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_items_space_id", "items", ["space_id"])
    op.create_index("ix_items_folder_id", "items", ["folder_id"])
    op.create_index("ix_items_material_type", "items", ["material_type"])
    op.create_index("ix_items_share_token", "items", ["share_token"], unique=True)
    op.create_index("ix_items_properties", "items", ["properties"], postgresql_using="gin")
    # unaccent() штатно помечена STABLE, а не IMMUTABLE (зависит от словаря
    # text search), поэтому напрямую в индексном выражении postgres её не
    # пускает: "functions in index expression must be marked IMMUTABLE".
    # Обёртка ниже — стандартный обход из документации unaccent. Схема у
    # словаря обязательно должна быть указана явно (public.unaccent, а не
    # просто unaccent): при построении GIN-индекса planner инлайнит тело
    # этой SQL-функции и резолвит regdictionary заново в контексте, где
    # search_path на словарь уже не смотрит — без схемы там же падает
    # "text search dictionary unaccent does not exist".
    op.execute(
        """
        CREATE OR REPLACE FUNCTION notenotes_immutable_unaccent(text)
        RETURNS text AS $$
            SELECT public.unaccent('public.unaccent'::regdictionary, $1)
        $$ LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
        """
    )
    op.execute(
        """
        CREATE INDEX ix_items_search ON items
        USING gin (to_tsvector('simple', notenotes_immutable_unaccent(coalesce(title, '') || ' ' || coalesce(content, ''))))
        """
    )

    op.create_table(
        "item_tags",
        sa.Column(
            "item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "tag_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
    )
    op.create_index("ix_item_tags_tag_id", "item_tags", ["tag_id"])

    op.create_table(
        "item_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.String(500), nullable=False, server_default=""),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_item_versions_item_id", "item_versions", ["item_id"])
    op.create_index("ix_item_versions_created_at", "item_versions", ["created_at"])


def downgrade() -> None:
    op.drop_table("item_versions")
    op.drop_table("item_tags")
    op.execute("DROP INDEX IF EXISTS ix_items_search")
    op.execute("DROP FUNCTION IF EXISTS notenotes_immutable_unaccent(text)")
    op.drop_table("items")
    op.drop_table("uploads")
    op.drop_table("tags")
    op.drop_table("folders")
    op.drop_table("space_members")
    op.drop_table("spaces")
    op.drop_table("users")
