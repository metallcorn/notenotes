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
    # True — скан без текстового слоя поставлен в очередь на авто-OCR при
    # загрузке (файл ≤5МБ, настройка auto_process_uploads включена).
    # Фронт по этому флагу знает: не показывать кнопку «Распознать» сразу,
    # результат придёт сам через плейсхолдер-замену (как у картинок/видео).
    pdf_ocr_queued: bool = False
    # Превью первых символов для НЕ-PDF текстовых файлов (.txt/.md/.csv/
    # .json/.log и т.п.) — читается сразу при загрузке, тем же приёмом, что
    # pdf_text, но отдельное поле: pdf_text используют места, которые уже
    # предполагают именно PDF (isPdf-ветки на фронте), а текстовый файл —
    # не PDF, путать поля не стоит.
    preview_text: str | None = None
    has_thumbnail: bool = False
