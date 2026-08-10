import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import AssistantMemory, User
from app.schemas.memory import MemoryCreate, MemoryOut

router = APIRouter(prefix="/api/memories", tags=["memories"])


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[AssistantMemory]:
    result = await db.execute(
        select(AssistantMemory).where(AssistantMemory.user_id == user.id).order_by(AssistantMemory.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> AssistantMemory:
    # Ручное добавление факта из настроек — раньше запомнить что-то мог
    # только сам ассистент через remember_fact внутри диалога; симметрия с
    # уже существующим ручным удалением (DELETE ниже) и с тем, что
    # remember_fact/forget_fact/list_memories и так работают триадой на
    # стороне ассистента.
    content = payload.content.strip()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Текст факта не может быть пустым")
    memory = AssistantMemory(user_id=user.id, content=content)
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return memory


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    memory = await db.get(AssistantMemory, memory_id)
    if memory is None or memory.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Факт не найден")
    await db.delete(memory)
    await db.commit()
