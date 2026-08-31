import secrets
from email.utils import parseaddr
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import EmailInbox, Space, SpaceMember, User

router = APIRouter(prefix="/api/mail", tags=["mail"])

# Непубличный локал-парт из случайных слов, а не opaque-токен — реальный
# запрос: адрес должен быть НАБИРАЕМ по памяти (при пересылке с телефона
# и т.п.), не только копированием. Список — официальный BIP39 (2048 слов,
# уже отобран под ровно это: без похожих по звучанию пар, без неоднозначных
# написаний). 3 слова = 2048^3 ≈ 8.6 млрд комбинаций (~33 бита) — заведомо
# не перебираемо в лоб почтовым спамом, при этом коротко для набора руками.
_WORDLIST = (Path(__file__).resolve().parent.parent / "data" / "wordlist_en.txt").read_text().split()
_WORDS_PER_ADDRESS = 3
_GENERATE_RETRIES = 5


def _new_local_part() -> str:
    return "-".join(secrets.choice(_WORDLIST) for _ in range(_WORDS_PER_ADDRESS))


def _address(local_part: str) -> str:
    return f"{local_part}@{get_settings().mail_domain}"


@router.get("/status")
async def get_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    inbox = await db.get(EmailInbox, user.id)
    return {
        "address": _address(inbox.local_part) if inbox else None,
        "own_addresses": inbox.own_addresses if inbox else [],
    }


@router.post("/generate")
async def generate(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    inbox = await db.get(EmailInbox, user.id)
    if inbox is not None:
        return {"address": _address(inbox.local_part)}

    space = Space(name="Почта", owner_id=user.id)
    db.add(space)
    await db.flush()
    db.add(SpaceMember(space_id=space.id, user_id=user.id))
    await db.commit()

    for attempt in range(_GENERATE_RETRIES):
        local_part = _new_local_part()
        db.add(EmailInbox(user_id=user.id, local_part=local_part, space_id=space.id))
        try:
            await db.commit()
            return {"address": _address(local_part)}
        except IntegrityError:
            await db.rollback()
            if attempt == _GENERATE_RETRIES - 1:
                raise
    raise AssertionError("unreachable")


@router.post("/regenerate")
async def regenerate(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    inbox = await db.get(EmailInbox, user.id)
    if inbox is None:
        return {"address": None}

    for attempt in range(_GENERATE_RETRIES):
        inbox.local_part = _new_local_part()
        try:
            await db.commit()
            return {"address": _address(inbox.local_part)}
        except IntegrityError:
            await db.rollback()
            inbox = await db.get(EmailInbox, user.id)
            if attempt == _GENERATE_RETRIES - 1:
                raise
    raise AssertionError("unreachable")


class OwnAddressIn(BaseModel):
    email: str


# Реальная жалоба: пересылаешь себе письмо (или ставишь notenotes в копию
# письма, которое написал сам) — папка группируется по собственному имени
# пользователя, не по реальному собеседнику, потому что From: в этом
# случае — сам пользователь (см. routers/mail_webhook.py::_sender_folder_
# name). Явный список "своих" адресов — единственный способ отличить этот
# случай от письма от постороннего.
@router.post("/own-addresses")
async def add_own_address(
    payload: OwnAddressIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    inbox = await db.get(EmailInbox, user.id)
    if inbox is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сначала создайте приёмный адрес для почты")

    _, email_addr = parseaddr(payload.email)
    email_addr = email_addr.strip().lower()
    if not email_addr or "@" not in email_addr:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный email")

    if email_addr not in inbox.own_addresses:
        # Новый список объектом, не .append() — та же ловушка SQLAlchemy,
        # что и с JSONB messages в dialogs.py: мутация существующего списка
        # на месте не замечается трекером изменений колонки.
        inbox.own_addresses = [*inbox.own_addresses, email_addr]
        await db.commit()
    return {"own_addresses": inbox.own_addresses}


@router.delete("/own-addresses/{email}")
async def remove_own_address(
    email: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    inbox = await db.get(EmailInbox, user.id)
    if inbox is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Приёмный адрес для почты не настроен")

    email_lower = email.strip().lower()
    inbox.own_addresses = [a for a in inbox.own_addresses if a.lower() != email_lower]
    await db.commit()
    return {"own_addresses": inbox.own_addresses}


@router.delete("/inbox")
async def disable(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    inbox = await db.get(EmailInbox, user.id)
    if inbox is not None:
        await db.delete(inbox)
        await db.commit()
    return {"address": None}
