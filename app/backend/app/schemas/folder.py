import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class FolderCreate(BaseModel):
    space_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    icon: str | None = Field(default=None, max_length=16)


class FolderUpdate(BaseModel):
    """parent_id/name трогаются, только если явно присутствуют в теле запроса
    (см. model_fields_set в роутере) — иначе не отличить «не менять» от
    «переместить в корень» (parent_id=null)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: uuid.UUID | None = None
    # Как parent_id: icon=null в теле — «убрать значок», отсутствие — «не трогать».
    icon: str | None = Field(default=None, max_length=16)


class FolderMoveSpace(BaseModel):
    space_id: uuid.UUID


class FolderOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    space_id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    icon: str | None = None
    created_at: datetime
