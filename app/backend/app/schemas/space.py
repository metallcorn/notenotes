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
    # Публичные страницы (routers/public.py) — взаимоисключающе с
    # is_vault, проверка в routers/spaces.py::create_space.
    is_public_pages: bool = False


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
    is_public_pages: bool


class VaultUnlockInfoOut(BaseModel):
    vault_salt: str
    vault_verifier: str


class VaultRotateItemIn(BaseModel):
    id: uuid.UUID
    vault: dict


class SpaceMemberOut(BaseModel):
    user_id: uuid.UUID
    username: str
    name: str
    joined_at: datetime


class SpaceMemberAddIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class SpaceInviteOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    token: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class VaultRotatePasswordIn(BaseModel):
    """Смена пароля сейфа — клиент уже расшифровал всё старым ключом и
    зашифровал новым (сервер не может это сделать сам, у него никогда не
    было ни одного из ключей). Файлы к этому моменту уже перешифрованы и
    лежат во временных .new-копиях рядом с оригиналами (PUT /uploads/{id}) —
    здесь только id тех, что нужно подтвердить. Всё применяется одной
    транзакцией (routers/spaces.py) — либо целиком, либо старый пароль
    остаётся рабочим и ничего не теряется."""

    new_salt: str
    new_verifier: str
    items: list[VaultRotateItemIn]
    upload_ids: list[uuid.UUID] = []
