from datetime import datetime

from pydantic import BaseModel


class UrlCheckWidgetOut(BaseModel):
    url: str
    fields: list[dict]
    last_result: str | None = None
    last_fetched_at: datetime | None = None
    last_status: int | None = None
    # Заголовки авторизации никогда не отдаются клиенту — только сам факт
    # их наличия, для маленькой иконки-индикатора на карточке.
    has_credentials: bool = False
