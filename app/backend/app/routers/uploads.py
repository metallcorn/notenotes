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

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

# Произвольные файлы (ТЗ §9 — файл как item — придёт в Фазе 2; пока это
# просто вложение к заметке). Тип не ограничиваем: файл никогда не
# исполняется, только отдаётся обратно через авторизованный FileResponse.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


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

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Файл больше 25 МБ")

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
    _upload_path(upload.id).write_bytes(data)

    await db.commit()
    return UploadOut(id=upload.id, url=f"/api/uploads/{upload.id}", filename=upload.filename, content_type=content_type)


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
