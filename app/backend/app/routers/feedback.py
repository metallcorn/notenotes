import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import FileResponse

from app.core.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import Feedback, User
from app.schemas.feedback import FeedbackOut
from app.security import decode_session_token

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

MAX_SCREENSHOT_BYTES = 15 * 1024 * 1024


def _feedback_dir() -> Path:
    path = Path(get_settings().upload_dir) / "feedback"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _optional_user(request: Request, db: AsyncSession) -> User | None:
    # Отзыв можно отправить и до логина (например, баг на самом экране
    # входа) — поэтому не Depends(get_current_user), который требует cookie.
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        return None
    user_id = decode_session_token(token)
    if user_id is None:
        return None
    return await db.get(User, user_id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_feedback(
    request: Request,
    message: str = Form(...),
    page_url: str = Form(""),
    screenshot: UploadFile | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    message = message.strip()
    if not message:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой отзыв")

    user = await _optional_user(request, db)

    feedback = Feedback(
        user_id=user.id if user else None,
        message=message,
        page_url=page_url[:500],
        user_agent=(request.headers.get("user-agent") or "")[:500],
    )
    db.add(feedback)
    await db.flush()

    if screenshot is not None and screenshot.content_type == "image/png":
        data = await screenshot.read(MAX_SCREENSHOT_BYTES + 1)
        if len(data) <= MAX_SCREENSHOT_BYTES:
            filename = f"{feedback.id}.png"
            (_feedback_dir() / filename).write_bytes(data)
            feedback.screenshot_filename = filename

    await db.commit()
    return {"id": str(feedback.id)}


@router.get("", response_model=list[FeedbackOut])
async def list_feedback(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[Feedback]:
    result = await db.execute(select(Feedback).order_by(Feedback.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{feedback_id}/screenshot")
async def get_feedback_screenshot(
    feedback_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> FileResponse:
    feedback = await db.get(Feedback, feedback_id)
    if feedback is None or not feedback.screenshot_filename:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Скриншот не найден")
    path = _feedback_dir() / feedback.screenshot_filename
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Скриншот не найден")
    return FileResponse(path, media_type="image/png")
