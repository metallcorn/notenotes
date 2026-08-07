import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class TagUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class TagMerge(BaseModel):
    target_tag_id: uuid.UUID


class TagOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    created_at: datetime


class ItemTagOut(TagOut):
    """Тег в контексте конкретного item — с пометкой, авто это или ручной
    (ТЗ §8.2). auto=False по умолчанию для мест, где ItemTagOut собирается
    не из ItemTag (сейчас нигде, но на будущее — падать не должно)."""

    auto: bool = False
