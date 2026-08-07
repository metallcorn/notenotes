import uuid

from pydantic import BaseModel


class UploadOut(BaseModel):
    id: uuid.UUID
    url: str
    filename: str
    content_type: str
