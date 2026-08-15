from __future__ import annotations

import io
import logging

import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)

# Ниже этого — почти нет текста/фон-шум, определение угла ненадёжно.
# Реальный живой тест: настоящий поворот на 90° дал confidence 0.80 —
# порог с запасом ниже, не режет реальные случаи, но отсекает угадывание
# на пустом/некачественном фото.
_MIN_CONFIDENCE = 0.5


def correct_orientation(image_bytes: bytes) -> bytes:
    """Определяет и исправляет поворот фото/скана ДО OCR/vision-LLM —
    механически, через Tesseract OSD (анализ формы символов по форме
    засечек и базовой линии), не через LLM: дёшево, детерминированно, не
    тратит вызов vision-модели. Реальный найденный случай: страница скана
    физически повёрнута на 90° (у PDF-страницы при этом флаг /Rotate был
    0 — поворот "зашит" в сами пиксели, не метаданные) — vision-модель
    пыталась читать текст как есть и спутала содержимое (перепутала регион
    в штампе). С коррекцией распознавание стало полным и точным.

    Никогда не бросает исключение и не ломает вызывающий код — это попытка
    УЛУЧШИТЬ вход, а не обязательный шаг; при любой неудаче (OSD не
    справился, низкая уверенность, не удалось повернуть) возвращает байты
    без изменений."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        osd = pytesseract.image_to_osd(image)
    except Exception:
        logger.info("Не удалось определить ориентацию изображения (OSD) — используем как есть")
        return image_bytes

    rotate_deg = 0
    confidence = 0.0
    for line in osd.splitlines():
        if line.startswith("Rotate:"):
            try:
                rotate_deg = int(line.split(":", 1)[1].strip())
            except ValueError:
                rotate_deg = 0
        elif line.startswith("Orientation confidence:"):
            try:
                confidence = float(line.split(":", 1)[1].strip())
            except ValueError:
                confidence = 0.0

    if rotate_deg == 0 or confidence < _MIN_CONFIDENCE:
        return image_bytes

    try:
        # Tesseract "Rotate" — на сколько градусов повернуть ПО часовой
        # стрелке, чтобы исправить; PIL Image.rotate() крутит против
        # часовой — отсюда минус.
        corrected = image.rotate(-rotate_deg, expand=True)
        buf = io.BytesIO()
        corrected.save(buf, format=image.format or "PNG")
        logger.info("Изображение повёрнуто на %d° по данным OSD (confidence=%.2f)", rotate_deg, confidence)
        return buf.getvalue()
    except Exception:
        logger.exception("Не удалось применить поворот по данным OSD")
        return image_bytes
