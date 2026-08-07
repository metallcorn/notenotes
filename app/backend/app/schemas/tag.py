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
