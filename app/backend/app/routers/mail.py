import secrets
from pathlib import Path

from fastapi import APIRouter, Depends
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
    return {"address": _address(inbox.local_part) if inbox else None}


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


@router.delete("/inbox")
async def disable(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    inbox = await db.get(EmailInbox, user.id)
    if inbox is not None:
        await db.delete(inbox)
        await db.commit()
    return {"address": None}
