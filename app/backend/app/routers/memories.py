import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import AssistantMemory, User
from app.schemas.memory import MemoryOut

router = APIRouter(prefix="/api/memories", tags=["memories"])


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[AssistantMemory]:
    result = await db.execute(
        select(AssistantMemory).where(AssistantMemory.user_id == user.id).order_by(AssistantMemory.created_at.desc())
    )
    return list(result.scalars().all())


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    memory = await db.get(AssistantMemory, memory_id)
    if memory is None or memory.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Факт не найден")
    await db.delete(memory)
    await db.commit()
