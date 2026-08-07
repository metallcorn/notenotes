import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SpaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class SpaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class SpaceOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    owner_id: uuid.UUID
    created_at: datetime
