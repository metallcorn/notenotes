from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import Space, SpaceMember, User
from app.schemas.auth import UserCreate, UserLogin, UserOut, UserUpdate
from app.security import create_session_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
async def login(payload: UserLogin, response: Response, db: AsyncSession = Depends(get_db)) -> User:
    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")

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
    await db.commit()
    await db.refresh(user)
    return user
