import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

USERNAME_PATTERN = r"^[a-zA-Z0-9_.-]+$"


def _normalize_username(v: str) -> str:
    # На телефоне автозаглавная буква клавиатуры и случайный пробел от
    # автозаполнения пароль-менеджера — обычное дело. mode="before": нормализуем
    # ДО проверки pattern, иначе пробел в конце сам по себе завалит валидацию,
    # не успев быть обрезанным.
    return v.strip().lower()


def _normalize_password(v: str) -> str:
    return v.strip()


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=255)
    # Реальный найденный баг (внешний пентест): регистрация была открыта
    # всему интернету — противоречит ТЗ §4 ("пользователи добавляются
    # вручную"). Инвайт-код, не полное отключение эндпоинта — семью всё
    # ещё можно добавлять, просто не анониму с улицы.
    invite_code: str = ""

    _normalize_username = field_validator("username", mode="before")(_normalize_username)
    _normalize_password = field_validator("password", mode="before")(_normalize_password)


class UserLogin(BaseModel):
    username: str
    password: str

    _normalize_username = field_validator("username", mode="before")(_normalize_username)
    _normalize_password = field_validator("password", mode="before")(_normalize_password)


class UserOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    username: str
    name: str
    created_at: datetime
    custom_instructions: str = ""
    disabled_tools: list[str] = []
    tts_voice: str = "default_low"
    auto_process_uploads: bool = True
    llm_provider: str = ""


class UserUpdate(BaseModel):
    # Все поля опциональны — PATCH меняет только то, что передано, не
    # затирает остальные, если фронтенд обновляет их порознь.
    custom_instructions: str | None = Field(default=None, max_length=4000)
    disabled_tools: list[str] | None = None
    tts_voice: str | None = Field(default=None, min_length=1, max_length=128)
    auto_process_uploads: bool | None = None
    llm_provider: str | None = None
