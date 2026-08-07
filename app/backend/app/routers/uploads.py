import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import FileResponse

from app.core.config import get_settings
from app.db import get_db
from app.deps import ensure_space_access, get_current_user
from app.models import Upload, User
from app.schemas.upload import UploadOut
from app.transcription import enqueue_transcription
from app.vision import enqueue_vision

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

# Произвольные файлы (ТЗ §9 — файл как item — придёт в Фазе 2; пока это
# просто вложение к заметке). Тип не ограничиваем: файл никогда не
# исполняется, только отдаётся обратно через авторизованный FileResponse.
# 300 МБ хватает на видео с телефона в разумном качестве (диск — 27 ГБ
# свободно, не узкое место); раньше было 25 МБ — заимствовано у лимита
# Whisper API для голосовых сообщений, для видео категорически мало.
MAX_UPLOAD_BYTES = 300 * 1024 * 1024
_STREAM_CHUNK_BYTES = 1024 * 1024


def _upload_path(upload_id: uuid.UUID) -> Path:
    return Path(get_settings().upload_dir) / str(upload_id)


@router.post("", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def create_upload(
    space_id: uuid.UUID,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UploadOut:
    await ensure_space_access(db, space_id, user.id)

    content_type = file.content_type or "application/octet-stream"
    upload = Upload(
        space_id=space_id,
        author_id=user.id,
        filename=file.filename or "файл",
        content_type=content_type,
    )
    db.add(upload)
    await db.flush()

    upload_dir = Path(get_settings().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = _upload_path(upload.id)

    # Пишем на диск чанками, не читаем файл целиком в память — backend
    # ограничен 768 МБ (docker-compose.yml.j2), а с потолком 300 МБ на
    # аплоад чтение целиком в bytes перед записью держало бы это в памяти
    # одним куском на весь запрос, легко несколько таких параллельно — OOM.
    total = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(_STREAM_CHUNK_BYTES):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Файл больше 300 МБ")
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        await db.rollback()
        raise

    if content_type.startswith("video/") or content_type.startswith("image/"):
        upload.transcription_status = "pending"

    await db.commit()

    if content_type.startswith("video/"):
        enqueue_transcription(upload.id)
    elif content_type.startswith("image/"):
        enqueue_vision(upload.id)

    return UploadOut(id=upload.id, url=f"/api/uploads/{upload.id}", filename=upload.filename, content_type=content_type)


@router.post("/{upload_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess_upload(
    upload_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Повторный запуск OCR/расшифровки — нужен файлам, загруженным до того,
    как появились vision.py/transcription.py (для них воркер никогда не
    запускался), а также если распознавание в первый раз не задалось."""
    upload = await db.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден")
    await ensure_space_access(db, upload.space_id, user.id)

    if not (upload.content_type.startswith("video/") or upload.content_type.startswith("image/")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Распознавание доступно только для видео и картинок")

    upload.transcription_status = "pending"
    await db.commit()

    if upload.content_type.startswith("video/"):
        enqueue_transcription(upload.id)
    else:
        enqueue_vision(upload.id)

    return {"status": "pending"}


@router.get("/{upload_id}")
async def get_upload(
    upload_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> FileResponse:
    upload = await db.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден")
    await ensure_space_access(db, upload.space_id, user.id)

    path = _upload_path(upload.id)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден")
    return FileResponse(path, media_type=upload.content_type, filename=upload.filename)
