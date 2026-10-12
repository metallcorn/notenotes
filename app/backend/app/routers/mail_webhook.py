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
from app.mail_forward import first_other_recipient, is_own_address, parse_forwarded_sender
from app.models import EmailInbox, Folder, Item, Upload, User
from app.pdf_processing import AUTO_OCR_MAX_PDF_BYTES
from app.pdf_processing import enqueue_ocr as enqueue_pdf_ocr
from app.pdf_processing import extract_text as extract_pdf_text
from app.pdf_processing import serialize_document_attachment
from app.routers.items import create_item_row
from app.routers.uploads import MAX_GENERIC_UPLOAD_BYTES, _extract_text_preview, _upload_path, save_upload_deduplicated
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


def _sender_folder_name(
    from_header: str,
    sender: str,
    *,
    content: str,
    to_header: str,
    cc_header: str,
    own_addresses: list[str],
    mail_domain: str,
) -> str:
    """Имя папки для писем от этого адресата — приоритет отображаемому
    имени ("Иван Иванов <ivan@example.com>"), иначе сам email. Та же
    логика, что у Telegram-форвардов (_forward_sender_name в
    telegram_bot.py): письма от одного человека группируются, не сыплются
    плоско в спейс.

    Реальная жалоба: письмо, пересланное СЕБЕ на notenotes-адрес, или
    письмо, которое пользователь сам отправил кому-то, поставив
    notenotes-адрес в копию — в обоих случаях From: это сам пользователь,
    а не тот, с кем на самом деле переписка. Если From: — известный свой
    адрес (own_addresses, настройки почты), ищем реального собеседника:
    сначала в теле письма (маркер пересылки + оригинальный From:,
    mail_forward.parse_forwarded_sender), иначе среди получателей To:/Cc:
    (mail_forward.first_other_recipient) — письмо, которое пользователь
    написал сам и скопировал себе, не пересылка, но собеседник там же."""
    if is_own_address(from_header, own_addresses):
        name, email_addr = parse_forwarded_sender(content)
        if not name and not email_addr:
            name, email_addr = first_other_recipient(to_header, cc_header, own_addresses, mail_domain)
        if name or email_addr:
            return (name or email_addr or "").strip()[:255]
        return "Без отправителя"

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


def _existing_attachment_block(upload: Upload) -> str:
    """Блок для вложения, которое в этом спейсе уже лежало.

    Ссылаемся на тот же файл и говорим об этом прямым текстом: человек
    должен видеть, что это повтор, а не думать, что вложение потерялось.
    Очередь обработки не трогаем — см. комментарий у вызова.
    """
    url = f"/api/uploads/{upload.id}"
    if upload.content_type.startswith("image/"):
        return f"![]({url})\n\n_Этот файл уже был в базе — показан тот же._\n"
    return (
        f"{serialize_document_attachment(url, upload.filename, (upload.transcript or '')[:4000])}\n\n"
        "_Этот файл уже был в базе — приложен тот же._\n"
    )


async def _save_attachment(
    db: AsyncSession, space_id: uuid.UUID, author_id: uuid.UUID, content: bytes, filename: str, content_type: str
) -> tuple[Upload, bool]:
    """Вложение письма. Возвращает (файл, он_уже_был) — см.
    save_upload_deduplicated: бухгалтер присылает месячный пакет
    повторно, и без этого «ZUS DRA 07-2026.pdf» лежал в пяти копиях."""
    return await save_upload_deduplicated(db, space_id, author_id, content, filename, content_type)


# Повторная доставка одного и того же письма.
#
# ЧТО НАШЛОСЬ НА ЖИВОЙ БАЗЕ 10.10 — две пары заметок:
#
#   Fwd: Налоги 08-2026       14:49:22  и  14:59:32   (02.09)
#   Fwd: Налоги за 07-2026    21:09:21  и  21:19:32   (25.08)
#
# Ровно десять минут и десять секунд в обоих случаях — это не человек,
# переслал дважды, это РАСПИСАНИЕ ПОВТОРОВ Mailgun. Он повторяет
# доставку, если вебхук не ответил вовремя, а обработчик здесь делает
# тяжёлую работу прямо в запросе: читает все вложения, вытаскивает текст
# из PDF, заводит загрузки. На большом письме с вложениями на 4 ГБ VPS
# это легко выходит за таймаут вебхука — и письмо приезжает снова.
#
# Содержимое двух заметок при этом РАЗЛИЧАЕТСЯ (24 784 и 26 641
# символа), и это сбивало со следа: выглядит как два разных письма. На
# самом деле текст письма один, а отличаются блоки вложений — в них
# входит id загрузки, он у второй доставки другой, плюс OCR на одном
# проходе успел извлечь текст, а на другом нет.
#
# Ключ — Message-Id из самого письма: он уникален глобально и один для
# всех доставок одного сообщения. Ни «похожесть», ни тема, ни время:
# «Fwd: Przedłużenie umowy najmu» в той же базе встречается трижды за
# двенадцать дней — это РАЗНЫЕ письма с одной темой, и схлопывать их
# было бы потерей.
#
# Проверяем в пределах спейса этого ящика, а не глобально: если один и
# тот же рассылочный лист придёт двум людям, каждый должен получить свою
# заметку, а Message-Id у них совпадёт.
#
# Храним в properties заметки, без отдельной таблицы и индекса: писем
# единицы в день, записей в базе сотни, а лишняя сущность со своей
# миграцией тут дороже, чем seq scan раз в несколько часов (тот же
# довод, что у дедупликации в document_expiry.py).
async def _already_received(db: AsyncSession, space_id: uuid.UUID, message_id: str) -> bool:
    if not message_id:
        return False
    found = (
        await db.execute(
            select(Item.id).where(
                Item.space_id == space_id,
                Item.properties["mail_message_id"].astext == message_id,
            )
        )
    ).first()
    return found is not None


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
        # Реальный найденный баг: enqueue_vision кладёт upload_id только в
        # процесс-локальную очередь в памяти — если рестарт/деплой случится
        # ДО того, как воркер реально начал обработку, задача теряется
        # молча, а transcription_status всё ещё дефолтный "none" (не
        # "pending"/"processing"), так что resume_pending() при старте её
        # не находит — плейсхолдер "обрабатывается…" остаётся навсегда
        # (реальный случай: вложение письма "Re: Fw: Invoice Examplecorp").
        upload.transcription_status = "pending"
        enqueue_vision(upload.id)
        return f"![]({url})\n\n{image_placeholder_text(upload.id)}\n"

    if content_type.startswith("video/") or content_type.startswith("audio/"):
        upload.transcription_status = "pending"
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

    title = str(form.get("subject", "")).strip() or "Письмо без темы"
    content = str(form.get("stripped-text", "") or form.get("body-plain", "")).strip()

    # Регистр поля не документирован (как и у To/Cc ниже) — пробуем оба.
    message_id = str(form.get("Message-Id", "") or form.get("message-id", "")).strip()
    if await _already_received(db, inbox.space_id, message_id):
        # 200, а не ошибка: Mailgun должен считать доставку успешной и
        # прекратить повторы, иначе он будет возвращаться каждые десять
        # минут до конца своего расписания.
        logger.info("Письмо %s уже получено — повторная доставка пропущена", message_id)
        return {"ok": True, "duplicate": True}

    # Mailgun отдаёт заголовки как есть из письма — регистр поля у To/Cc
    # не документирован так же чётко, как у "from"/"sender"/"recipient"
    # (те — собственные поля Mailgun, всегда нижним регистром); пробуем
    # оба варианта написания, отсутствие обоих — просто нет сигнала.
    to_header = str(form.get("To", "") or form.get("to", ""))
    cc_header = str(form.get("Cc", "") or form.get("cc", ""))
    folder_name = _sender_folder_name(
        str(form.get("from", "")),
        str(form.get("sender", "")),
        content=content,
        to_header=to_header,
        cc_header=cc_header,
        own_addresses=inbox.own_addresses,
        mail_domain=settings.mail_domain,
    )
    folder_id = await _get_or_create_folder(db, inbox.space_id, folder_name)

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
            upload, reused = await _save_attachment(
                db, inbox.space_id, inbox.user_id, data, file.filename or f"attachment-{i}", file.content_type or "application/octet-stream"
            )
            # Повторно присланный файл не обрабатываем заново: OCR и
            # распознавание речи уже отработали на нём в прошлый раз, и
            # второй проход — это и деньги провайдера, и очередь на 4 ГБ
            # VPS, и риск перезаписать уже извлечённый текст пустотой.
            blocks.append(
                _existing_attachment_block(upload)
                if reused
                else await _attachment_block(upload, data, auto_process)
            )

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
        properties={"mail_message_id": message_id} if message_id else None,
    )

    return {"ok": True}
