from pydantic import BaseModel


class UrlCheckFetchIn(BaseModel):
    url: str


class UrlCheckFetchOut(BaseModel):
    status_code: int | None = None
    body: str | None = None
    error: str | None = None
