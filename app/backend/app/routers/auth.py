import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import Space, SpaceMember, User
from app.schemas.auth import UserCreate, UserLogin, UserOut, UserUpdate
from app.security import create_session_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Реальный найденный баг security-аудита: /login не сопротивлялся перебору
# пароля вообще — 6 заведомо неверных попыток подряд ушли без единой
# задержки/блокировки. Считаем только НЕУДАЧНЫЕ попытки по IP (не логину —
# заодно защищает от перебора самого логина), сбрасываем при успехе, чтобы
# не блокировать обычные опечатки нескольких людей за одним IP навсегда.
# In-memory, не Redis: один backend-процесс (без множественных воркеров,
# см. CLAUDE.md про бюджет памяти), состояние переживает столько же,
# сколько сам процесс — этого достаточно для 2-10 пользователей.
_LOGIN_ATTEMPT_WINDOW_SECONDS = 300
_LOGIN_MAX_ATTEMPTS = 5
_login_attempts: dict[str, list[float]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    # Caddy — обратный прокси перед backend'ом (docker-сеть edge), без
    # --proxy-headers у uvicorn request.client.host был бы IP-адресом
    # самого Caddy внутри сети, не реального посетителя. Caddy сам
    # проставляет X-Forwarded-For по умолчанию, один хоп — берём первый
    # адрес из списка.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _login_attempts_blocked(ip: str) -> bool:
    now = time.monotonic()
    attempts = _login_attempts[ip]
    attempts[:] = [t for t in attempts if now - t < _LOGIN_ATTEMPT_WINDOW_SECONDS]
    return len(attempts) >= _LOGIN_MAX_ATTEMPTS


def _record_failed_login(ip: str) -> None:
    _login_attempts[ip].append(time.monotonic())


def _set_session_cookie(response: Response, user_id) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=create_session_token(user_id),
        max_age=settings.session_ttl_days * 24 * 3600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, response: Response, db: AsyncSession = Depends(get_db)) -> User:
    existing = await db.execute(select(User).where(User.username == payload.username))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Пользователь с таким логином уже существует")

    user = User(username=payload.username, password_hash=hash_password(payload.password), name=payload.name)
    db.add(user)
    await db.flush()

    personal_space = Space(name="Личное", owner_id=user.id)
    db.add(personal_space)
    await db.flush()

    db.add(SpaceMember(space_id=personal_space.id, user_id=user.id))
    await db.commit()
    await db.refresh(user)

    _set_session_cookie(response, user.id)
    return user


@router.post("/login", response_model=UserOut)
async def login(payload: UserLogin, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> User:
    ip = _client_ip(request)
    if _login_attempts_blocked(ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много неудачных попыток входа — попробуй через несколько минут"
        )

    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        _record_failed_login(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")

    _login_attempts.pop(ip, None)
    _set_session_cookie(response, user.id)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: UserUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    if payload.custom_instructions is not None:
        user.custom_instructions = payload.custom_instructions.strip()
    if payload.disabled_tools is not None:
        from app.tools.registry import SKILL_CATALOG

        # Игнорируем неизвестные имена и попытки выключить нетогглящиеся
        # тулы — settings-модалка на фронте и так их не присылает, но не
        # доверяем этому одному месту.
        user.disabled_tools = [
            name for name in payload.disabled_tools if SKILL_CATALOG.get(name, {}).get("toggleable")
        ]
    if payload.tts_voice is not None:
        user.tts_voice = payload.tts_voice.strip()
    if payload.auto_process_uploads is not None:
        user.auto_process_uploads = payload.auto_process_uploads
    if payload.llm_provider is not None:
        # "" — глобальный дефолт из LLM_PROVIDER (app/llm/factory.py), иначе
        # только реально существующие провайдеры — не доверяем фронтенду.
        allowed = {"", "mistral", "gemini", "groq"}
        value = payload.llm_provider.strip().lower()
        if value not in allowed:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Неизвестный провайдер: {value}")
        user.llm_provider = value
    await db.commit()
    await db.refresh(user)
    return user
