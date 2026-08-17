from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.models import User
from app.schemas.url_check import UrlCheckFetchIn, UrlCheckFetchOut
from app.url_check import check_url

router = APIRouter(prefix="/api/url-checks", tags=["url-checks"])


@router.post("/fetch", response_model=UrlCheckFetchOut)
async def fetch_url_check(payload: UrlCheckFetchIn, user: User = Depends(get_current_user)) -> UrlCheckFetchOut:
    """Кнопка «Обновить» на карточке виджета (UrlCheckCard.tsx) — прямой
    REST, без участия ассистента: обновление данных не требует LLM, только
    сам GET-запрос (app/url_check.py, SSRF-safe). Ассистент нужен один раз,
    при создании блока (tools/url_check.py::insert_url_check_block)."""
    return UrlCheckFetchOut(**await check_url(payload.url))
