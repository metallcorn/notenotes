"""Сквозной вид «Документы»: всё из всех спейсов, одним списком.

ЗАПРОС ВЛАДЕЛЬЦА: «как-то возможно отсортировать или пересобрать отдельно
где-то все документы, потому что всё сейчас так раскидано».

ПОЧЕМУ ВИД, А НЕ ПЕРЕМЕЩЕНИЕ. Он сам забраковал автосортировку по папкам
(«слишком много неоднозначности»), и данные это подтверждают: часть
спейсов расшарена с женой, так что неверный переезд документа — не
«неаккуратно», а чужой доступ. Плюс один и тот же документ законно живёт
в двух контекстах: архив переписки с бухгалтером («Почта») и личное
хранилище («Личное»). Единственное место для него было бы неправдой о
том, как с ним работают.

Поэтому здесь ничего не двигается, не меняются доступы и не создаётся
новых сущностей. Это запрос к тем же данным, собранный по-другому.

ЧТО СЧИТАЕТСЯ ДОКУМЕНТОМ. Файл, а не заметка: человек ищет «ZUS за июль»,
а не «письмо, в котором был ZUS за июль». Из файлов — те, что бывают
документами: PDF, офисные форматы, сканы. Видео и аудио не документы;
картинки — только с распознанным текстом (скан), иначе список утонет в
фотографиях из Telegram.

СЕЙФ ИСКЛЮЧЁН, как везде: сервер не видит его содержимого, и показывать
«документ, который нельзя открыть» бессмысленно.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.document_series import detect_series
from app.models import Item, Space, SpaceMember, Upload, User

router = APIRouter(prefix="/api/documents", tags=["documents"])

# Типы, которые бывают документами. Видео и аудио сюда не входят по
# смыслу, картинки — отдельным правилом ниже (только с распознанным
# текстом, то есть скан, а не фотография кота).
_DOCUMENT_TYPES = (
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/csv",
)


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int | None
    created_at: date
    space_id: uuid.UUID
    space_name: str
    # Заметка, в которой лежит файл — чтобы из списка можно было попасть
    # к нему в контекст, а не только скачать байты.
    item_id: uuid.UUID | None = None
    item_title: str | None = None


class InstalmentOut(BaseModel):
    period: str
    upload_id: uuid.UUID
    filename: str
    space_name: str
    received_on: date


class SeriesOut(BaseModel):
    key: str
    title: str
    monthly: bool
    status: str
    instalments: list[InstalmentOut]
    gaps: list[str]
    expected_next: str | None = None
    expected_by: date | None = None


class DocumentsOut(BaseModel):
    series: list[SeriesOut]
    documents: list[DocumentOut]


@router.get("", response_model=DocumentsOut)
async def list_documents(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> DocumentsOut:
    rows = (
        await db.execute(
            select(Upload, Space.name)
            .join(Space, Space.id == Upload.space_id)
            .join(SpaceMember, SpaceMember.space_id == Upload.space_id)
            .where(SpaceMember.user_id == user.id, Space.is_vault.is_(False))
            .order_by(Upload.created_at.desc())
        )
    ).all()

    uploads = [
        (upload, space_name)
        for upload, space_name in rows
        if upload.content_type in _DOCUMENT_TYPES
        or (upload.content_type.startswith("image/") and (upload.transcript or "").strip())
    ]

    # Заметка-хозяин ищется по ссылке на файл внутри content — так же, как
    # это делает document_expiry. Один запрос на всё и поиск подстроки в
    # памяти: заметок сотни, файлов сотни, а индекса по «ссылка внутри
    # текста» нет и быть не может.
    notes = (
        await db.execute(
            select(Item.id, Item.title, Item.content)
            .join(SpaceMember, SpaceMember.space_id == Item.space_id)
            .where(
                SpaceMember.user_id == user.id,
                Item.deleted_at.is_(None),
                Item.material_type.in_(("note", "ticket")),
            )
        )
    ).all()
    host: dict[str, tuple[uuid.UUID, str]] = {}
    for note_id, title, content in notes:
        for upload, _space in uploads:
            marker = str(upload.id)
            if marker not in host and marker in (content or ""):
                host[marker] = (note_id, title or "Без названия")

    documents = [
        DocumentOut(
            id=upload.id,
            filename=upload.filename,
            content_type=upload.content_type,
            size_bytes=upload.size_bytes,
            created_at=upload.created_at.date(),
            space_id=upload.space_id,
            space_name=space_name,
            item_id=host.get(str(upload.id), (None, None))[0],
            item_title=host.get(str(upload.id), (None, None))[1],
        )
        for upload, space_name in uploads
    ]

    series, _standalone = detect_series(
        [(str(u.id), u.filename, s, u.created_at.date()) for u, s in uploads], today=date.today()
    )
    return DocumentsOut(
        series=[
            SeriesOut(
                key=s.key,
                title=s.title,
                monthly=s.monthly,
                status=s.status,
                instalments=[
                    InstalmentOut(
                        period=i.period.label(),
                        upload_id=uuid.UUID(i.upload_id),
                        filename=i.filename,
                        space_name=i.space_name,
                        received_on=i.received_on,
                    )
                    for i in s.instalments
                ],
                gaps=[p.label() for p in s.gaps],
                expected_next=s.expected_next.label() if s.expected_next else None,
                expected_by=s.expected_by,
            )
            for s in series
        ],
        documents=documents,
    )
