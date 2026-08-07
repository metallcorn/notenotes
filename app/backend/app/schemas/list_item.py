import uuid
from datetime import datetime

from pydantic import BaseModel


class ListEntryOut(BaseModel):
    id: str
    text: str
    checked: bool
    created_at: str


class ListEntryCreate(BaseModel):
    text: str


class ListEntryUpdate(BaseModel):
    """Как ItemUpdate — поле применяется только если явно присутствует в теле."""

    text: str | None = None
    checked: bool | None = None


class ListCreate(BaseModel):
    space_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    title: str = ""


class ListOut(BaseModel):
    id: uuid.UUID
    space_id: uuid.UUID
    folder_id: uuid.UUID | None
    title: str
    entries: list[ListEntryOut]
    created_at: datetime
    updated_at: datetime
