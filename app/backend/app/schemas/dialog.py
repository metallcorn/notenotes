import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class DialogCreate(BaseModel):
    space_id: uuid.UUID
    title: str = ""


class MessageCreate(BaseModel):
    content: str


class ToolCallOut(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class DialogMessageOut(BaseModel):
    id: str
    role: str
    content: str
    tool_calls: list[ToolCallOut] = []
    tool_call_id: str | None = None
    name: str | None = None
    suggested_replies: list[str] = []
    created_at: str


class DialogSummaryOut(BaseModel):
    id: uuid.UUID
    space_id: uuid.UUID
    # По умолчанию пусто — заполняется только в списке диалогов (список
    # теперь общий на все спейсы сразу, нужно подписывать откуда каждый).
    # _serialize() для одиночного диалога (DialogOut) это поле не трогает —
    # там уже понятно, в каком спейсе открыт диалог, по контексту экрана.
    space_name: str = ""
    title: str
    created_at: datetime
    updated_at: datetime


class DialogOut(DialogSummaryOut):
    messages: list[DialogMessageOut] = []
