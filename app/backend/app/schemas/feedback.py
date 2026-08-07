import uuid
from datetime import datetime

from pydantic import BaseModel


class FeedbackOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID | None
    message: str
    page_url: str
    screenshot_filename: str | None
    user_agent: str | None
    created_at: datetime
