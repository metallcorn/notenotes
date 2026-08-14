import uuid
from datetime import datetime

from pydantic import BaseModel


class NotificationOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    type: str
    title: str
    body: str
    payload: dict
    read_at: datetime | None
    created_at: datetime
    trigger_at: datetime | None = None
    resolved_at: datetime | None = None


class NotificationCreateIn(BaseModel):
    title: str
    body: str = ""
    trigger_at: datetime
    # Реальный найденный баг: без этого у напоминаний, созданных кнопкой
    # "Напомнить" на карточке билета, не было привязки к заметке вообще —
    # клик по такому уведомлению не открывал ничего (NotificationBell.tsx/
    # ActivityView.tsx решают кликабельность именно по payload.item_id).
    # tools/reminders.py's create_reminder для ассистента эту привязку уже
    # умеет — этот путь просто не переиспользовал её.
    item_id: str | None = None
