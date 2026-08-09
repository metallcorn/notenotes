from fastapi import APIRouter, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.config import get_settings
from app.db import get_db
from app.models import DebugLog, User
from app.security import decode_session_token

router = APIRouter(prefix="/api/debug-log", tags=["debug-log"])

MAX_EVENT_LEN = 100


class DebugLogIn(BaseModel):
    event: str
    data: dict = {}


async def _optional_user(request: Request, db: AsyncSession) -> User | None:
    # sendBeacon с fetch(keepalive) как фолбэком (см. diagnostics.ts) не
    # всегда донесёт куки в контексте выгружаемой/сворачиваемой страницы —
    # логируем, что можем, не требуя строгой авторизации.
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        return None
    user_id = decode_session_token(token)
    if user_id is None:
        return None
    return await db.get(User, user_id)


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def create_debug_log(
    request: Request,
    payload: DebugLogIn,
    db: AsyncSession = Depends(get_db),
) -> None:
    user = await _optional_user(request, db)
    log = DebugLog(user_id=user.id if user else None, event=payload.event[:MAX_EVENT_LEN], data=payload.data)
    db.add(log)
    await db.commit()
