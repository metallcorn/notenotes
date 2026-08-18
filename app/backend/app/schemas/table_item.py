import uuid
from datetime import datetime

from pydantic import BaseModel


class TableColumnOut(BaseModel):
    id: str
    name: str
    type: str


class TableColumnCreate(BaseModel):
    name: str
    type: str = "text"


class TableRowOut(BaseModel):
    id: str
    cells: dict[str, str]
    created_at: str


class TableRowCreate(BaseModel):
    cells: dict[str, str] = {}


class TableRowUpdate(BaseModel):
    """Как ListEntryUpdate — переданные ключи cells заменяют, остальные ячейки строки не трогает."""

    cells: dict[str, str] = {}


class TableCreate(BaseModel):
    space_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    title: str = ""
    columns: list[TableColumnCreate] = []


class TableOut(BaseModel):
    id: uuid.UUID
    space_id: uuid.UUID
    folder_id: uuid.UUID | None
    title: str
    columns: list[TableColumnOut]
    rows: list[TableRowOut]
    created_at: datetime
    updated_at: datetime
