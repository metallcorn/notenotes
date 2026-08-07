import uuid
from datetime import datetime

from pydantic import BaseModel


class MemoryOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    content: str
    created_at: datetime
