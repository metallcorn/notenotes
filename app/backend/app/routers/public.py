import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import FileResponse

from app.db import get_db
from app.models import Item
from app.routers.auth import _client_ip
from app.routers.items import _UPLOAD_URL_RE
from app.routers.uploads import _safe_to_inline, _upload_path
from app.schemas.item import PublicItemOut
from app.security import verify_password

router = APIRouter(prefix="/api/public", tags=["public"])

# Свой счётчик, не тот же, что у /auth/login (routers/auth.py) — другой
# ресурс, нет смысла делить состояние. Тот же паттерн и тот же реальный
# повод (security-аудит: перебор пароля без задержки/блокировки).
_UNLOCK_ATTEMPT_WINDOW_SECONDS = 300
_UNLOCK_MAX_ATTEMPTS = 5
_unlock_attempts: dict[str, list[float]] = defaultdict(list)


def _unlock_blocked(ip: str) -> bool:
    now = time.monotonic()
    attempts = _unlock_attempts[ip]
    attempts[:] = [t for t in attempts if now - t < _UNLOCK_ATTEMPT_WINDOW_SECONDS]
    return len(attempts) >= _UNLOCK_MAX_ATTEMPTS


def _record_failed_unlock(ip: str) -> None:
    _unlock_attempts[ip].append(time.monotonic())


async def _get_shared_item(db: AsyncSession, token: str) -> Item:
    """Общая проверка валидности шаринга — is_public, срок действия,
    однократность. НЕ проверяет пароль (это отдельный шаг, см.
    view_public_note/unlock_public_note ниже) и НЕ помечает use_at —
    это ответственность вызывающего, только там, где контент реально
    показывается."""
    result = await db.execute(select(Item).where(Item.share_token == token))
    item = result.scalar_one_or_none()
    # Не различаем "нет такого токена"/"не опубликовано"/"истекло" в
    # ответе — снаружи это не должно быть отличимо (тот же принцип, что
    # у инвайт-кодов в routers/auth.py).
    if item is None or not item.is_public or item.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Страница не найдена")
    if item.share_expires_at is not None and item.share_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Страница не найдена")
    if item.share_single_use and item.share_used_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Страница не найдена")
    return item


def _public_out(item: Item) -> PublicItemOut:
    return PublicItemOut(title=item.title, content=item.content, updated_at=item.updated_at)


async def _mark_used_if_single_use(db: AsyncSession, item: Item) -> None:
    if item.share_single_use and item.share_used_at is None:
        item.share_used_at = datetime.now(timezone.utc)
        await db.commit()


@router.get("/{token}")
async def view_public_note(token: str, db: AsyncSession = Depends(get_db)) -> dict | PublicItemOut:
    item = await _get_shared_item(db, token)
    if item.share_password_hash is not None:
        return {"requires_password": True}
    # Собрать ответ ДО commit() — после commit SQLAlchemy истекает поля
    # объекта, и обращение к ним вне активного await-контекста роняет
    # сессию (MissingGreenlet, реально пойманное при живой проверке).
    result = _public_out(item)
    await _mark_used_if_single_use(db, item)
    return result


@router.post("/{token}/unlock", response_model=PublicItemOut)
async def unlock_public_note(
    token: str, request: Request, db: AsyncSession = Depends(get_db)
) -> PublicItemOut:
    ip = _client_ip(request)
    if _unlock_blocked(ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток — попробуйте через несколько минут"
        )
    body = await request.json()
    password = str(body.get("password") or "")

    item = await _get_shared_item(db, token)
    if item.share_password_hash is None or not verify_password(password, item.share_password_hash):
        _record_failed_unlock(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный пароль")

    _unlock_attempts.pop(ip, None)
    result = _public_out(item)
    await _mark_used_if_single_use(db, item)
    return result


@router.get("/{token}/uploads/{upload_id}")
async def get_public_upload(token: str, upload_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> FileResponse:
    """Анонимный доступ к файлу, вложенному в опубликованную заметку.
    Осознанно НЕ повторяет проверку однократности (см. докстринг модуля
    плана/README) — только сама заметка блокируется после первого показа,
    её вложения продолжают отдаваться по тому же токену. Без
    предварительного просмотра content (уже заблокированного) чужой
    upload_id всё равно неизвестен — окно доверия того не стоит.

    upload_id обязан реально встречаться в content ЭТОЙ заметки (тот же
    substring-приём, что items.py::move_item_space/cleanup.py) — иначе
    валидный токен одной заметки давал бы доступ к произвольному upload_id
    просто по угадыванию UUID."""
    item = await _get_shared_item(db, token)
    if str(upload_id) not in _UPLOAD_URL_RE.findall(item.content):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден")

    from app.models import Upload

    upload = await db.get(Upload, upload_id)
    if upload is None or upload.space_id != item.space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден")

    path = _upload_path(upload_id)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден")
    disposition = "inline" if _safe_to_inline(upload.content_type) else "attachment"
    return FileResponse(
        path, media_type=upload.content_type, filename=upload.filename, content_disposition_type=disposition
    )


@router.get("/{token}/uploads/{upload_id}/text")
async def get_public_upload_text(token: str, upload_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Распознанный текст вложения опубликованной заметки — для карточки
    файла на публичной странице. С 18.10 текст в заметке не хранится
    (app/attachment_text.py), без этого маршрута аноним видел бы карточку
    без текста. Те же проверки, что у самого файла выше."""
    item = await _get_shared_item(db, token)
    if str(upload_id) not in _UPLOAD_URL_RE.findall(item.content):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден")

    from app.models import Upload

    upload = await db.get(Upload, upload_id)
    if upload is None or upload.space_id != item.space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден")
    return {"text": upload.transcript or "", "status": upload.transcription_status}
