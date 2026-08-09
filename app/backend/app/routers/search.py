import re
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import Item, SpaceMember, User
from app.routers.items import _serialize
from app.schemas.item import ItemOut
from app.transliterate import transliteration_variant

router = APIRouter(prefix="/api/search", tags=["search"])


def _document():
    # notenotes_immutable_unaccent — обёртка над unaccent(), заведённая в
    # миграции 0001: сам unaccent() не IMMUTABLE, поэтому GIN-индекс
    # ix_items_search построен на этой обёртке. Здесь используем ту же
    # функцию, иначе выражение не совпадёт с индексом и postgres пойдёт
    # последовательным сканом вместо индекса.
    #
    # notenotes_extract_attr_text (миграция 0015) — PostgreSQL распознаёт
    # <div data-doc-attachment ...> (DocumentAttachment.ts) как единый XML-тег
    # и полностью исключает его из to_tsvector (обнаружено через ts_debug) —
    # распознанный текст PDF, лежащий в атрибуте data-text, был бы невидим
    # для поиска без этой отдельной экстракции.
    #
    # notenotes_urlsplit (миграция 0019) — та же проблема с <a href="...">
    # (карточка ссылки, см. LinkPreview.ts/_linkify_bare_urls) — тег
    # целиком невидим для to_tsvector, а голая ссылка в title/content
    # индексируется одним составным токеном ('www.zalando.pl'), не
    # отдельными словами, поэтому "zalando" её не находил. Выражение здесь
    # ДОЛЖНО совпадать с индексом ix_items_search байт в байт, иначе
    # postgres не сможет им воспользоваться.
    title = func.coalesce(Item.title, "")
    content = func.coalesce(Item.content, "")
    return func.to_tsvector(
        "simple",
        func.notenotes_immutable_unaccent(
            title
            + " "
            + content
            + " "
            + func.notenotes_extract_attr_text(content)
            + " "
            + func.notenotes_urlsplit(title + " " + content)
        ),
    )


async def search_items(
    db: AsyncSession,
    user_id: uuid.UUID,
    q: str,
    *,
    material_types: tuple[str, ...] = ("note",),
    space_id: uuid.UUID | None = None,
    limit: int = 50,
    match: str = "and",
) -> list[Item]:
    """Общее ядро поиска — переиспользуется и HTTP-эндпоинтом, и тулом
    search_base ассистента (ТЗ §10b: retrieval-слой общий для поиска и
    диалога, не два разных механизма).

    match="and" (по умолчанию, как в поиске-по-мере-набора) требует все
    слова запроса — точно для короткого точного ввода человеком, но слишком
    строго для LLM: тот пишет запросы естественной фразой ("купить
    продукты"), где половина слов — не из заметки. match="or" — мягкий
    вариант, им search_base подстраховывается, если "and" ничего не нашёл."""
    q = q.strip()
    if not q:
        return []

    # websearch_to_tsquery ищет только целые слова — набранное "те" никогда
    # не находило бы "тестовая", хотя пользователь ждёт результат уже по
    # ходу набора, как в обычном поиске-фильтре. Поэтому каждое слово ищем
    # как префикс через :*, а не целиком.
    words = re.findall(r"\w+", q, flags=re.UNICODE)
    if not words:
        return []
    joiner = " & " if match == "and" else " | "
    # Кириллица/латиница — тем же словом, но не тем алфавитом, что в
    # заметке ("Ульяна" не находила бы заметку/папку с "Ulyana"), не
    # находились вовсе: реальный случай. transliterate.py даёт второй
    # вариант написания слова — добавляем его через OR внутри терма, сам
    # AND/OR между словами (joiner) не меняется.
    terms = []
    for w in words:
        variant = transliteration_variant(w)
        terms.append(f"({w}:* | {variant}:*)" if variant else f"{w}:*")
    tsquery_text = joiner.join(terms)
    tsquery = func.to_tsquery("simple", func.notenotes_immutable_unaccent(tsquery_text))
    document = _document()
    rank = func.ts_rank(document, tsquery).label("rank")

    query = (
        select(Item)
        .join(SpaceMember, SpaceMember.space_id == Item.space_id)
        .where(
            SpaceMember.user_id == user_id,
            Item.material_type.in_(material_types),
            Item.deleted_at.is_(None),
            document.op("@@")(tsquery),
        )
        .order_by(rank.desc())
        .limit(limit)
    )
    if space_id is not None:
        query = query.where(Item.space_id == space_id)
    return list((await db.execute(query)).scalars().all())


@router.get("", response_model=list[ItemOut])
async def search(
    q: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ItemOut]:
    items = await search_items(db, user.id, q, material_types=("note", "ticket"))
    return [await _serialize(db, item, user.id) for item in items]
