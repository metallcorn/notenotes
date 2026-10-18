import re
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import Item, Space, SpaceMember, Upload, User
from app.routers.items import _serialize
from app.schemas.item import ItemOut, SemanticHit
from app.embeddings import search_semantic
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
    #
    # properties.search_keywords (миграция 0038) — обиходные слова билета
    # («авиабилет», «жд билет», tickets.py::_SEARCH_SYNONYMS). Раньше их
    # приклеивали перед OCR-текстом в data-text карточки.
    #
    # Распознанный текст файлов здесь НЕ индексируется — с 18.10 его нет в
    # заметке (app/attachment_text.py), он ищется в загрузках
    # (_upload_document) и приводит к заметке, где файл лежит.
    # extract_attr_text остаётся ради блоков старого формата.
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
            + " "
            + func.coalesce(Item.properties["search_keywords"].astext, "")
        ),
    )


def _upload_document():
    # Совпадает с индексом ix_uploads_search (миграция 0038) байт в байт.
    return func.to_tsvector(
        "simple",
        func.notenotes_immutable_unaccent(
            func.coalesce(Upload.filename, "") + " " + func.coalesce(Upload.transcript, "")
        ),
    )


# Потолок файлов, совпавших по тексту, на один запрос: каждый становится
# условием «content содержит id». На живой базе ~400 файлов всего, так что
# потолок — страховка, а не ограничение.
_MAX_MATCHED_UPLOADS = 200


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
    # заметке ("Алина" не находила бы заметку/папку с "Alina"), не
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

    # Заметка находится и по тексту своих файлов. Сначала файлы — по их
    # собственному индексу, потом заметки, где они лежат: обратный порядок
    # (для каждой заметки перебрать все файлы) считал бы to_tsvector
    # каждого файла столько раз, сколько заметок.
    matched_upload_ids = (
        await db.execute(
            select(Upload.id)
            .join(SpaceMember, SpaceMember.space_id == Upload.space_id)
            .where(SpaceMember.user_id == user_id, _upload_document().op("@@")(tsquery))
            .limit(_MAX_MATCHED_UPLOADS)
        )
    ).scalars().all()
    text_match = document.op("@@")(tsquery)
    if matched_upload_ids:
        text_match = or_(text_match, *[Item.content.contains(str(uid)) for uid in matched_upload_ids])

    query = (
        select(Item)
        .join(SpaceMember, SpaceMember.space_id == Item.space_id)
        .join(Space, Space.id == Item.space_id)
        .where(
            SpaceMember.user_id == user_id,
            Item.material_type.in_(material_types),
            Item.deleted_at.is_(None),
            text_match,
            # Сейф — сервер хранит только шифротекст, искать в нём нечего
            # (не "не положено", а физически бессмысленно). Фильтр
            # действует ДАЖЕ если space_id ниже явно указывает на сейф.
            Space.is_vault.is_(False),
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


# Порог близости, ИЗМЕРЕННЫЙ на боевой базе (2026-09-07, 8 осмысленных
# запросов против 8 заведомо посторонних):
#
#   осмысленные:  0.734 … 0.815   («проблемы с машиной», «документы»)
#   посторонние:  0.687 … 0.751   («квантовая хромодинамика», «крикет»)
#
# Диапазоны ПЕРЕКРЫВАЮТСЯ — идеального порога не существует, и это
# свойство модели, а не недоработка. У многоязычных эмбеддингов тексты на
# одном языке похожи друг на друга сами по себе, поэтому любой русский
# запрос получает базовые ~0.73 к любой русской заметке.
#
# 0.75 выбран как лучший компромисс по этим данным: отсекает посторонние
# запросы целиком (кроме «рецепт суши в древнем Египте» — 0.751, но там
# модель права, в базе есть рецепты) ценой одного осмысленного запроса из
# восьми («проблемы с машиной», 0.734). Терять его не жалко: по слову
# «машина» и «Citroën» отработает обычный полнотекстовый поиск, который
# показывается ПЕРЕД этим блоком.
#
# Ошибиться в меньшую сторону дороже, чем в большую: пустой блок
# «расширенный поиск» читается как «ничего не нашлось», а паспорт в ответ
# на вопрос про физику элементарных частиц — как сломанный поиск.
_MIN_SEMANTIC_SCORE = 0.75

# Потолок выдачи. Семантический поиск почти всегда возвращает хоть
# что-нибудь, поэтому длинный список создаёт ложное впечатление, будто
# нашлось много: показываем несколько лучших, остальное отсекаем.
_MAX_SEMANTIC_HITS = 5


@router.get("/semantic", response_model=list[SemanticHit])
async def search_semantic_endpoint(
    q: str,
    space_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SemanticHit]:
    """Поиск по смыслу — ОТДЕЛЬНЫЙ маршрут, а не режим основного.

    По ТЗ §10 это единый флоу с прогрессивной загрузкой: быстрые
    результаты (полнотекст) появляются мгновенно, семантические подгружаются
    следом отдельным блоком с индикатором. Разделение на два запроса —
    единственный способ дать это на практике: семантический ход требует
    обращения к API эмбеддингов и занимает сотни миллисекунд, и ждать его
    ради мгновенной выдачи было бы шагом назад.
    """
    hits = [h for h in await search_semantic(db, user.id, q, space_id=space_id)
            if h[1] >= _MIN_SEMANTIC_SCORE][:_MAX_SEMANTIC_HITS]
    return [
        SemanticHit(item=await _serialize(db, item, user.id), score=round(score, 4), excerpt=chunk[:300])
        for item, score, chunk in hits
    ]
