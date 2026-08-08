import uuid

from pydantic import BaseModel


class UploadOut(BaseModel):
    id: uuid.UUID
    url: str
    filename: str
    content_type: str
    # Текстовый слой PDF, вытащенный сразу при загрузке (PyMuPDF, локально,
    # бесплатно) — тот же приём, что уже в telegram_bot.py, раньше был
    # только там. None — не PDF или текстового слоя нет (скан, распознаётся
    # только по кнопке «Распознать» в редакторе).
    pdf_text: str | None = None
