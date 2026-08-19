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
    # Опционально — сразу разложить в папку целевого спейса одним
    # действием, а не переносить заметку "в корень" и потом отдельно
    # искать её там, чтобы разложить (реальная жалоба на неудобство).
    folder_id: uuid.UUID | None = None


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
    # Найденные LLM физические адреса (app/autotag.py) — для клика-на-карту
    # прямо в тексте заметки (extensions/DetectedAddressLinks.ts). Только для
    # ТЕКУЩЕЙ открытой заметки, не кросс-спейсовый список — в отличие от
    # detected_events (своя лента в ActivityView), сюда отдельный эндпоинт
    # не нужен.
    detected_addresses: list[dict] = []


class ShareItemIn(BaseModel):
    password: str | None = Field(default=None, min_length=1, max_length=200)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
    single_use: bool = False


class ShareItemOut(BaseModel):
    is_public: bool
    share_token: str | None
    has_password: bool
    share_expires_at: datetime | None
    share_single_use: bool
    share_used_at: datetime | None


class PublicItemOut(BaseModel):
    """Публичные страницы (routers/public.py) — намеренно узкая схема:
    никаких space_id/author_id/folder_id/vault/tags/detected_addresses,
    это внутренние поля, которым нечего делать в ответе анонимному
    посетителю."""

    title: str
    content: str
    updated_at: datetime


class DetectedEventDismissIn(BaseModel):
    event_at: str
    event_title: str


class DetectedEventOut(BaseModel):
    """Одно найденное событие (app/autotag.py, properties.detected_events)
    — плоская пара "заметка + дата", а не сам Item: у одной заметки может
    быть несколько дат, ActivityView должен уметь показать их отдельными
    строками."""

    item_id: uuid.UUID
    space_id: uuid.UUID
    item_title: str
    event_title: str
    event_at: str


class ItemVersionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    content: str
    author_id: uuid.UUID | None
    created_at: datetime
