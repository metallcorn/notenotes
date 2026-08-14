import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SpaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    # Сейф — все три поля вместе или ни одного (см. валидатор в
    # routers/spaces.py). Сервер их не проверяет по смыслу (не может —
    # у него нет ключа), только сохраняет как есть.
    is_vault: bool = False
    vault_salt: str | None = None
    vault_verifier: str | None = None


class SpaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class SpaceOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    owner_id: uuid.UUID
    created_at: datetime
    # Только для иконки замка в сайдбаре. salt/verifier сюда намеренно НЕ
    # входят — SpaceOut отдаётся при каждом GET /spaces (список всех
    # спейсов сразу), а verifier — материал для офлайн-подбора пароля
    # (зашифрованная известная строка + соль достаточно, чтобы пробовать
    # пароли не обращаясь больше к серверу). Не секрет в криптографическом
    # смысле (без пароля бесполезен), но незачем светить его там, где он
    # не нужен — см. VaultUnlockInfoOut/отдельный эндпоинт.
    is_vault: bool


class VaultUnlockInfoOut(BaseModel):
    vault_salt: str
    vault_verifier: str
