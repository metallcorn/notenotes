"""Распознанный текст вложений: где он живёт и как его читать.

С 18.10 правило такое: в тексте заметки — только то, что пишет человек.
Распознанный текст файла (OCR картинки, текстовый слой PDF, содержимое
docx, расшифровка речи) живёт в uploads.transcript, а блок вложения в
заметке — это ссылка на файл, без копии текста.

Раньше копия лежала в атрибуте data-text прямо в Markdown заметки. ЗАМЕР
перед переездом: 184 таких блока в 94 заметках, в 155 текст побайтово
совпадал с transcript — хранился дважды. И почти каждый баг недели рос
оттуда: дата внутри атрибута не прокручивалась (3 случая из 4), мусор
&#10; в напоминаниях о сроках, сроки документов находились дважды, сырой
Markdown-режим превращался в простыню экранированной каши, а get_note
отдавал модели эти блобы целиком.

Старый формат читается по-прежнему: блок, в котором data-text остался
(откат к старой версии заметки, или 21 блок, чьих загрузок уже нет —
там текст в заметке единственная копия), показывается и ищется как
раньше. Поэтому каждый читатель здесь — «текст из атрибута, если он
есть, иначе из загрузки».
"""
from __future__ import annotations

import html
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Upload, UploadTranscriptVersion

# Три узла редактора с распознанным текстом: DocumentAttachment.ts,
# ImageOcrResult.ts, TicketAttachment.ts. Все три — один самодостаточный
# тег на одной строке.
#
# Атрибуты разбираются по кавычкам, а не «до первого >»: экранирование
# data-text никогда не трогало символ >, и в распознанном тексте он есть
# («->», «<br>» из таблиц). ЗАМЕР 18.10: разбор «до первого >» пропускал
# 44 блока из 228 — ровно те, где внутри текста встречается >.
BLOCK_RE = re.compile(
    r'<div (data-doc-attachment|data-image-ocr-result|data-ticket-attachment)'
    r'((?:\s+[\w-]+(?:="[^"]*")?)*)\s*></div>'
)
_UPLOAD_ID_RE = re.compile(r'(?:data-upload-id="|/api/uploads/)([0-9a-fA-F-]{36})')
_UPLOAD_REF_RE = re.compile(r"/api/uploads/([0-9a-fA-F-]{36})")
DATA_TEXT_RE = re.compile(r'\sdata-text="[^"]*"')
_DATA_TEXT_VALUE_RE = re.compile(r'\sdata-text="([^"]*)"')
_FILENAME_RE = re.compile(r'data-filename="([^"]*)"')


@dataclass
class Attachment:
    kind: str
    upload_id: uuid.UUID | None
    filename: str
    # Текст из data-text — только у блоков старого формата.
    inline_text: str
    start: int
    end: int


def _parse_uuid(raw: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def find_attachments(content: str) -> list[Attachment]:
    """Блоки вложений заметки в порядке появления.

    У карточки распознанного текста картинки, вставленной до августа,
    нет data-upload-id — она стоит сразу после самой картинки
    (![](/api/uploads/...)). Для неё файл — ближайшая ссылка на загрузку
    выше по тексту. ЗАМЕР 18.10: у всех 64 таких карточек текст побайтово
    совпал с transcript этой ближайшей загрузки, то есть привязка верная.
    """
    found: list[Attachment] = []
    for m in BLOCK_RE.finditer(content):
        kind, attrs = m.group(1), m.group(2)
        id_match = _UPLOAD_ID_RE.search(attrs)
        upload_id = _parse_uuid(id_match.group(1)) if id_match else None
        if upload_id is None and kind == "data-image-ocr-result":
            previous = list(_UPLOAD_REF_RE.finditer(content, 0, m.start()))
            upload_id = _parse_uuid(previous[-1].group(1)) if previous else None
        text_match = _DATA_TEXT_VALUE_RE.search(attrs)
        name_match = _FILENAME_RE.search(attrs)
        found.append(Attachment(
            kind=kind,
            upload_id=upload_id,
            filename=html.unescape(name_match.group(1)) if name_match else "",
            inline_text=html.unescape(text_match.group(1)) if text_match else "",
            start=m.start(),
            end=m.end(),
        ))
    return found


async def load_transcripts(db: AsyncSession, upload_ids: set[uuid.UUID]) -> dict[uuid.UUID, Upload]:
    if not upload_ids:
        return {}
    rows = (await db.execute(select(Upload).where(Upload.id.in_(upload_ids)))).scalars().all()
    return {u.id: u for u in rows}


@dataclass
class AttachmentText:
    attachment: Attachment
    filename: str
    text: str


async def attachment_texts(db: AsyncSession, content: str) -> list[AttachmentText]:
    """Текст каждого вложения заметки: из атрибута (старый формат) или из
    загрузки. Вложения без текста не возвращаются."""
    attachments = find_attachments(content)
    uploads = await load_transcripts(db, {a.upload_id for a in attachments if a.upload_id and not a.inline_text})
    out: list[AttachmentText] = []
    for a in attachments:
        upload = uploads.get(a.upload_id) if a.upload_id else None
        text = a.inline_text or ((upload.transcript or "") if upload is not None else "")
        if not text.strip():
            continue
        out.append(AttachmentText(a, a.filename or (upload.filename if upload is not None else ""), text))
    return out


def _file_label(filename: str) -> str:
    return f"[Файл «{filename}»]" if filename else "[Распознанный текст файла]"


async def readable_content(db: AsyncSession, content: str, *, per_file_limit: int | None = None) -> str:
    """Заметка, какой её видит человек с раскрытыми карточками: блоки
    вложений заменены на подпись и распознанный текст.

    Для машинных читателей — эмбеддингов, авто-тегов, проверки номеров,
    поиска сроков. Не для записи обратно в заметку: в content должен
    остаться сам тег, иначе карточка файла исчезнет.
    """
    texts = {(t.attachment.start, t.attachment.end): t for t in await attachment_texts(db, content)}
    if not texts:
        return content
    parts: list[str] = []
    pos = 0
    for a in find_attachments(content):
        parts.append(content[pos:a.start])
        t = texts.get((a.start, a.end))
        if t is not None:
            body = t.text if per_file_limit is None else t.text[:per_file_limit]
            parts.append(f"{_file_label(t.filename)}\n{body}")
        pos = a.end
    parts.append(content[pos:])
    return "".join(parts)


def strip_inline_text(content: str) -> str:
    """Убирает data-text из всех блоков вложений — сами блоки остаются."""
    return BLOCK_RE.sub(lambda m: DATA_TEXT_RE.sub("", m.group(0)), content)


def remember_extracted_text(upload: Upload, text: str | None) -> None:
    """Текст, извлечённый при приёме файла (текстовый слой PDF при
    выключенной автообработке, содержимое docx/xlsx/pptx/txt), — в
    загрузку.

    Найденная дыра: этот текст уходил только в заметку, а transcript
    оставался пустым. ЗАМЕР 18.10: шесть таких файлов, среди них
    «Przedłużenie umowy najmu» — его срок искался по заметке, а
    list_files/get_file считали файл нечитаемым.

    Не перезаписывает уже распознанное: дубль файла приходит с текстом
    своего близнеца, и затирать его сырым слоем незачем.
    """
    if not text or not text.strip() or (upload.transcript or "").strip():
        return
    upload.transcript = text
    if upload.transcription_status in (None, "none"):
        upload.transcription_status = "done"


def set_transcript(db: AsyncSession, upload: Upload, text: str, author_id: uuid.UUID | None = None) -> None:
    """Единственный способ ПЕРЕзаписать распознанный текст файла: прежний
    сохраняется в upload_transcript_versions (см. её докстринг)."""
    previous = upload.transcript or ""
    if previous.strip() and previous != text:
        db.add(UploadTranscriptVersion(upload_id=upload.id, transcript=previous, author_id=author_id))
    upload.transcript = text
