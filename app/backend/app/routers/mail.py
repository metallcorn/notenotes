import secrets

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import EmailInbox, Space, SpaceMember, User

router = APIRouter(prefix="/api/mail", tags=["mail"])

# Непубличный случайный локал-парт, не сам email пользователя — та же
# энтропия и та же логика неугадываемости, что у SpaceInvite.token/
# TelegramLinkCode.code.
_LOCAL_PART_BYTES = 9


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
    local_part = secrets.token_urlsafe(_LOCAL_PART_BYTES)
    db.add(EmailInbox(user_id=user.id, local_part=local_part, space_id=space.id))
    await db.commit()
    return {"address": _address(local_part)}


@router.post("/regenerate")
async def regenerate(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    inbox = await db.get(EmailInbox, user.id)
    if inbox is None:
        return {"address": None}
    inbox.local_part = secrets.token_urlsafe(_LOCAL_PART_BYTES)
    await db.commit()
    return {"address": _address(inbox.local_part)}


@router.delete("/inbox")
async def disable(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    inbox = await db.get(EmailInbox, user.id)
    if inbox is not None:
        await db.delete(inbox)
        await db.commit()
    return {"address": None}
