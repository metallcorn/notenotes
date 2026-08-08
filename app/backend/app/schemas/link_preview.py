from pydantic import BaseModel


class LinkPreviewOut(BaseModel):
    model_config = {"from_attributes": True}

    url: str
    title: str | None
    description: str | None
    image_url: str | None
    favicon_url: str | None
    fetch_failed: bool
