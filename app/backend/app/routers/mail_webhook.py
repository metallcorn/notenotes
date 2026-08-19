import hashlib
import hmac
import logging
import uuid
from email.utils import parseaddr
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.models import EmailInbox, Folder, Upload, User
from app.pdf_processing import AUTO_OCR_MAX_PDF_BYTES
from app.pdf_processing import enqueue_ocr as enqueue_pdf_ocr
from app.pdf_processing import extract_text as extract_pdf_text
from app.pdf_processing import serialize_document_attachment
from app.routers.items import create_item_row
from app.routers.uploads import MAX_GENERIC_UPLOAD_BYTES, _extract_text_preview, _upload_path
from app.transcription import enqueue_transcription
from app.transcription import placeholder_text as video_placeholder_text
from app.vision import enqueue_vision
from app.vision import placeholder_text as image_placeholder_text

router = APIRouter(prefix="/api/mail", tags=["mail"])
logger = logging.getLogger(__name__)


def _verify_signature(timestamp: str, token: str, signature: str) -> bool:
    signing_key = get_settings().mailgun_webhook_signing_key
    if not signing_key:
        return False
    expected = hmac.new(signing_key.encode(), f"{timestamp}{token}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _sender_folder_name(from_header: str, sender: str) -> str:
    """Имя папки для писем от этого адресата — приоритет отображаемому
    имени ("Иван Иванов <ivan@example.com>"), иначе сам email. Та же
    логика, что у Telegram-форвардов (_forward_sender_name в
    telegram_bot.py): письма от одного человека группируются, не сыплются
    плоско в спейс."""
    display_name, email_addr = parseaddr(from_header)
    return (display_name or email_addr or sender or "Без отправителя").strip()[:255]


async def _get_or_create_folder(db: AsyncSession, space_id: uuid.UUID, name: str) -> uuid.UUID:
    existing = (
        await db.execute(select(Folder).where(Folder.space_id == space_id, Folder.parent_id.is_(None), Folder.name == name))
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    folder = Folder(space_id=space_id, parent_id=None, name=name)
    db.add(folder)
    await db.flush()
    return folder.id


async def _save_attachment(
    db: AsyncSession, space_id: uuid.UUID, author_id: uuid.UUID, content: bytes, filename: str, content_type: str
) -> Upload:
    upload = Upload(space_id=space_id, author_id=author_id, filename=filename, content_type=content_type)
    db.add(upload)
    await db.flush()
    upload_dir = Path(get_settings().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    _upload_path(upload.id).write_bytes(content)
    return upload


async def _attachment_block(upload: Upload, data: bytes, auto_process: bool) -> str:
    """Markdown-блок для одного вложения — та же логика по типам, что у
    Telegram-документов/фото/видео (telegram_bot.py::_handle_document/
    _handle_photo/_handle_video). Реальная жалоба: раньше вложения письма
    падали как голые markdown-ссылки [filename](url) — ни OCR PDF, ни
    распознавание фото/видео никогда не запускались, потому что ничего не
    ставило файл в очередь vision/pdf_processing/transcription."""
    content_type = upload.content_type
    url = f"/api/uploads/{upload.id}"

    if content_type.startswith("image/"):
        enqueue_vision(upload.id)
        return f"![]({url})\n\n{image_placeholder_text(upload.id)}\n"

    if content_type.startswith("video/") or content_type.startswith("audio/"):
        enqueue_transcription(upload.id)
        return (
            f'<video src="{url}" controls preload="metadata" style="max-width: 100%; max-height: 70vh;"></video>\n\n'
            f"{video_placeholder_text(upload.id)}\n"
        )

    is_pdf = content_type == "application/pdf" or upload.filename.lower().endswith(".pdf")
    if is_pdf:
        text_layer = extract_pdf_text(data)
        if auto_process and (text_layer or len(data) <= AUTO_OCR_MAX_PDF_BYTES):
            upload.transcription_status = "pending"
            enqueue_pdf_ocr(upload.id)
            return f"{serialize_document_attachment(url, upload.filename, '', processing=True)}\n"
        return f"{serialize_document_attachment(url, upload.filename, text_layer or '')}\n"

    text_preview = None
    try:
        text_preview = _extract_text_preview(_upload_path(upload.id), content_type, upload.filename)
    except Exception:
        logger.exception("Не удалось извлечь текст из вложения письма %s (id=%s)", upload.filename, upload.id)
    return f"{serialize_document_attachment(url, upload.filename, text_preview or '')}\n"


@router.post("/webhook")
async def webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    settings = get_settings()
    if not settings.mailgun_webhook_signing_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    form = await request.form()
    timestamp = str(form.get("timestamp", ""))
    token = str(form.get("token", ""))
    signature = str(form.get("signature", ""))
    if not _verify_signature(timestamp, token, signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    recipient = str(form.get("recipient", ""))
    local_part = recipient.split("@", 1)[0].strip()

    inbox = (await db.execute(select(EmailInbox).where(EmailInbox.local_part == local_part))).scalar_one_or_none()
    if inbox is None:
        # Адрес когда-то удалён/невалиден — не ретраить, но и не создавать.
        return {"ok": True}

    folder_name = _sender_folder_name(str(form.get("from", "")), str(form.get("sender", "")))
    folder_id = await _get_or_create_folder(db, inbox.space_id, folder_name)

    title = str(form.get("subject", "")).strip() or "Письмо без темы"
    content = str(form.get("stripped-text", "") or form.get("body-plain", "")).strip()

    attachment_count = int(form.get("attachment-count", 0) or 0)
    blocks: list[str] = []
    if attachment_count:
        user = await db.get(User, inbox.user_id)
        auto_process = user is not None and user.auto_process_uploads
        for i in range(1, attachment_count + 1):
            file = form.get(f"attachment-{i}")
            if file is None or not hasattr(file, "read"):
                continue
            data = await file.read()
            if len(data) > MAX_GENERIC_UPLOAD_BYTES:
                continue
            upload = await _save_attachment(
                db, inbox.space_id, inbox.user_id, data, file.filename or f"attachment-{i}", file.content_type or "application/octet-stream"
            )
            blocks.append(await _attachment_block(upload, data, auto_process))

    if blocks:
        content = f"{content}\n\n" + "\n\n".join(blocks) if content else "\n\n".join(blocks)

    await create_item_row(
        db,
        space_id=inbox.space_id,
        author_id=inbox.user_id,
        material_type="note",
        title=title,
        content=content,
        folder_id=folder_id,
    )

    return {"ok": True}
