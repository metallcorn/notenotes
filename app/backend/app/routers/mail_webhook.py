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
from app.models import EmailInbox, Folder, Upload
from app.routers.items import create_item_row
from app.routers.uploads import MAX_GENERIC_UPLOAD_BYTES, _upload_path

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
    links: list[str] = []
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
        links.append(f"[{upload.filename}](/api/uploads/{upload.id})")

    if links:
        content = f"{content}\n\n" + "\n".join(links) if content else "\n".join(links)

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
