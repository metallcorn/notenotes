import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.tag import ItemTagOut


class ItemCreate(BaseModel):
    space_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    title: str = Field(default="", max_length=500)
    content: str = ""
    # Сейф (ТЗ §16.2): title/content для сейфовых заметок — уже заглушка
    # "🔒 Зашифровано", реальный шифротекст (IV+ciphertext на поле) кладётся
    # сюда клиентом. Сервер не заглядывает внутрь — просто хранит blob в
    # properties.vault (см. _serialize/create_item ниже).
    vault: dict | None = None


class ItemUpdate(BaseModel):
    """Как и FolderUpdate — поля применяются, только если явно присутствуют
    в теле запроса (model_fields_set), иначе folder_id=null нельзя было бы
    отличить от «не менять»."""

    title: str | None = Field(default=None, max_length=500)
    content: str | None = None
    folder_id: uuid.UUID | None = None
    icon: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=32)
    pinned: bool | None = None
    vault: dict | None = None


class ItemMoveSpace(BaseModel):
    space_id: uuid.UUID


class ItemOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    space_id: uuid.UUID
    folder_id: uuid.UUID | None
    author_id: uuid.UUID
    material_type: str
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
    tags: list[ItemTagOut] = []
    icon: str | None = None
    color: str | None = None
    pinned: bool = False
    deleted_at: datetime | None = None
    vault: dict | None = None


class ItemVersionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    content: str
    author_id: uuid.UUID | None
    created_at: datetime
