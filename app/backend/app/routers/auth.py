import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import InviteCode, Space, SpaceMember, User
from app.schemas.auth import InviteCodeOut, UserCreate, UserLogin, UserOut, UserUpdate
from app.security import create_session_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Инвайт-код регистрации — создаётся существующим пользователем в
# настройках (POST /invite-codes), не единый секрет в vault: реальный
# запрос "хочу сам выдавать код, а не просить владельца лезть в vault
# каждый раз". Без похожих на 0/O/1/I/L символов — легче продиктовать
# вслух/переслать не перепутав.
_INVITE_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_INVITE_CODE_LENGTH = 8
_INVITE_CODE_TTL_DAYS = 7

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
    # самого Caddy внутри сети, не реального посетителя.
    #
    # Реальный найденный баг (внешний пентест): брали ПЕРВЫЙ адрес из
    # X-Forwarded-For — а Caddy по умолчанию не перезаписывает этот
    # заголовок, а ДОПИСЫВАЕТ к тому, что уже прислал клиент. Значит
    # первый адрес — это то, что подставил сам клиент (произвольная
    # строка, ничем не проверяется), а не факт его реального IP. Атакующий
    # мог слать свой X-Forwarded-For с рандомным адресом на каждый запрос
    # и полностью обходить rate-limit по IP. Последний адрес в списке —
    # тот, что реально дописал Caddy при проксировании (сам TCP-peer,
    # клиент его подделать не может) — единственный, которому можно
    # доверять при ровно одном хопе прокси перед backend'ом.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
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
    now = datetime.now(timezone.utc)
    invite: InviteCode | None = None
    code = payload.invite_code.strip()
    if code:
        result = await db.execute(select(InviteCode).where(InviteCode.code == code))
        invite = result.scalar_one_or_none()
    # Не различаем "код не найден"/"уже использован"/"истёк" в ответе —
    # снаружи это не должно быть отличимо, иначе перебор кодов утекал бы
    # чуть больше информации, чем нужно.
    if invite is None or invite.used_at is not None or invite.expires_at < now:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Неверный, использованный или истёкший инвайт-код")

    existing = await db.execute(select(User).where(User.username == payload.username))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Пользователь с таким логином уже существует")

    user = User(username=payload.username, password_hash=hash_password(payload.password), name=payload.name)
    db.add(user)
    await db.flush()

    invite.used_at = now
    invite.used_by_id = user.id

    personal_space = Space(name="Личное", owner_id=user.id)
    db.add(personal_space)
    await db.flush()

    db.add(SpaceMember(space_id=personal_space.id, user_id=user.id))
    await db.commit()
    await db.refresh(user)

    _set_session_cookie(response, user.id)
    return user


@router.post("/invite-codes", response_model=InviteCodeOut, status_code=status.HTTP_201_CREATED)
async def create_invite_code(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> InviteCode:
    code = "".join(secrets.choice(_INVITE_CODE_ALPHABET) for _ in range(_INVITE_CODE_LENGTH))
    invite = InviteCode(
        code=code,
        created_by_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=_INVITE_CODE_TTL_DAYS),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return invite


@router.get("/invite-codes", response_model=list[InviteCodeOut])
async def list_invite_codes(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[InviteCode]:
    result = await db.execute(
        select(InviteCode).where(InviteCode.created_by_id == user.id).order_by(InviteCode.created_at.desc())
    )
    return list(result.scalars().all())


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
