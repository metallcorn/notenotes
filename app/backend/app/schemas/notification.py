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
