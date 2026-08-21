from pydantic import BaseModel


class UrlCheckFetchIn(BaseModel):
    url: str
    headers: dict[str, str] | None = None


class UrlCheckFetchOut(BaseModel):
    status_code: int | None = None
    body: str | None = None
    error: str | None = None
