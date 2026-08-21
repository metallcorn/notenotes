from datetime import datetime

from pydantic import BaseModel


class DeliveryWidgetOut(BaseModel):
    carrier: str
    tracking_number: str
    # Нормализованный результат delivery.track (уже распарсенный в dict) —
    # та же форма, что рисует карточка в чате (DeliveryCard). None, если
    # последний опрос не удался.
    result: dict | None = None
    last_fetched_at: datetime | None = None
