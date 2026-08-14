import json
import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.config import get_settings
from app.db import get_db
from app.models import DebugLog, User
from app.security import decode_session_token

router = APIRouter(prefix="/api/debug-log", tags=["debug-log"])

MAX_EVENT_LEN = 100
# Реальный найденный баг (внешний пентест): эндпоинт принимал произвольный
# dict без ограничения размера от кого угодно (авторизация опциональна —
# см. _optional_user) — анонимный write-sink в ту же БД, что и боевые
# данные, на том же 40-ГБ шифрованном томе. Потолок на размер payload'а +
# rate-limit по IP закрывают storage-DoS, не трогая саму опциональность
# авторизации (она осталась намеренно — см. комментарий в _optional_user).
MAX_DATA_BYTES = 2000
_RATE_WINDOW_SECONDS = 60
_RATE_MAX_REQUESTS = 30
_recent_requests: dict[str, list[float]] = defaultdict(list)


class DebugLogIn(BaseModel):
    event: str
    data: dict = {}


def _client_ip(request: Request) -> str:
    # Тот же приём и та же причина, что в routers/auth.py::_client_ip —
    # последний адрес в X-Forwarded-For, не первый (Caddy дописывает свой
    # в конец, не перезаписывает — первый адрес клиент может подделать).
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    hits = _recent_requests[ip]
    hits[:] = [t for t in hits if now - t < _RATE_WINDOW_SECONDS]
    hits.append(now)
    return len(hits) > _RATE_MAX_REQUESTS


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
    ip = _client_ip(request)
    if _rate_limited(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много запросов")
    if len(json.dumps(payload.data, ensure_ascii=False)) > MAX_DATA_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"data больше {MAX_DATA_BYTES} байт")

    user = await _optional_user(request, db)
    log = DebugLog(user_id=user.id if user else None, event=payload.event[:MAX_EVENT_LEN], data=payload.data)
    db.add(log)
    await db.commit()
