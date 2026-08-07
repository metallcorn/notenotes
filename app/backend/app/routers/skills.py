from typing import Any

from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.models import User
from app.tools.registry import list_skills

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
async def get_skills(user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    return list_skills(set(user.disabled_tools))
