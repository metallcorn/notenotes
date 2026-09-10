from __future__ import annotations

from typing import Any

import logging

from app.embeddings import search_semantic
from app.llm.base import ToolDefinition
from app.routers.search import _MAX_SEMANTIC_HITS, _MIN_SEMANTIC_SCORE, search_items
from app.tools.notes import item_url
from app.tools.registry import ToolContext

logger = logging.getLogger(__name__)

# Потолок для мягкого запасного поиска. Двадцать нерелевантных заметок в
# контексте — не «на всякий случай», а активная помеха: модель отвечает по
# первой попавшейся. Пять оставлены как подсказка «в базе есть что-то
# похожее по словам», не как выдача.
_MAX_LOOSE_HITS = 5


DEFINITION = ToolDefinition(
    name="search_base",
    description=(
        "Поиск по заметкам и спискам пользователя — по ВСЕМ его спейсам, не "
        "только текущему (ТЗ §10a). Ищет и по словам, и ПО СМЫСЛУ: спрашивать "
        "можно теми словами, какими человек говорит, а не теми, какими он "
        "записывал. Результаты с полем match=\"по смыслу...\" — догадка, а не "
        "точное попадание: прежде чем отвечать по такому, прочитай его "
        "целиком через get_note и убедись, что он вообще об этом. "
        "excerpt для списка это его реальные пункты (в формате "
        "[x]/[ ] текст), а для заметки — обрезанные первые 300 символов, НЕ всё содержимое. "
        "Если в заметке таблица, длинный список или что угодно длиннее пары предложений — после "
        "поиска вызови get_note по её id, чтобы прочитать целиком, прежде чем отвечать по её "
        "содержимому. Используй перед тем, как отвечать на вопрос по содержимому базы или "
        "перед созданием заметки/списка, чтобы не плодить дубликаты — объект может быть в "
        "другом спейсе пользователя, не только в текущем."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Поисковый запрос"}},
        "required": ["query"],
    },
)


async def handle(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    if not query:
        return {"results": []}
    types = ("note", "list", "ticket", "table")
    items = await search_items(ctx.db, ctx.user_id, query, material_types=types, limit=20)

    def _serialize(item: Any) -> dict[str, Any]:
        base = {
            "id": str(item.id),
            "title": item.title,
            "material_type": item.material_type,
            "folder_id": str(item.folder_id) if item.folder_id else None,
            "space_id": str(item.space_id),
            "url": item_url(item.id),
        }
        if item.material_type == "ticket":
            # excerpt (первые 300 символов content) для билета — почти
            # только обрывок служебного <div data-ticket-attachment ...>,
            # обрезанный посреди атрибута: не текст, а мусор для модели.
            # properties — уже готовые чистые поля, отдаём их вместо excerpt.
            base["properties"] = item.properties
        else:
            base["excerpt"] = item.content[:300]
        return base

    results = [_serialize(item) for item in items]

    # Смысловой поиск отдельной пометкой.
    #
    # Зачем вообще. Полнотекст идёт по to_tsvector('simple') — конфигурации
    # БЕЗ словаря (в базе перемешаны русский, польский и английский, и
    # словарь пришлось бы выбирать один на всех). Значит словоформы не
    # склеиваются: проверено запросом в базе, «покупка» НЕ находит «купить
    # продукты». Пользователь спрашивает не теми словами, какими записывал,
    # — и ассистент не находит его же заметку.
    #
    # Индекс для этого уже построен и работает в веб-поиске; ассистенту он
    # просто не был подключён.
    #
    # Почему внутрь search_base, а не отдельным инструментом. Модель уже
    # надёжно зовёт search_base, а между двумя поисками ей пришлось бы
    # выбирать по правилу в промпте — самый слабый из наших рычагов (плюс
    # 41-й тул усугубил бы choice paralysis, см. коммит aa63515).
    #
    # Порог и потолок — те же, что в веб-поиске, и намеренно из одного
    # места: 0.75 ИЗМЕРЕН на боевой базе, дублировать такое число нельзя.
    seen_ids = {r["id"] for r in results}
    try:
        hits = await search_semantic(ctx.db, ctx.user_id, query)
    except Exception:
        # Эмбеддер недоступен — отдаём полнотекстовую выдачу как раньше.
        # Смысловой поиск здесь дополнение, а не замена: ронять из-за него
        # весь ход нельзя.
        logger.warning("Смысловой поиск не отработал, отдаю только полнотекст", exc_info=True)
        hits = []

    added = 0
    for item, score, chunk in hits:
        if added >= _MAX_SEMANTIC_HITS:
            break
        if score < _MIN_SEMANTIC_SCORE or str(item.id) in seen_ids:
            continue
        added += 1
        entry = _serialize(item)
        # excerpt — СОВПАВШИЙ кусок, а не начало заметки: по документу на
        # 80 тысяч знаков начало не объясняет, почему он вообще нашёлся.
        entry["excerpt"] = chunk[:300]
        # Явная пометка. Смысловое совпадение принципиально менее надёжно
        # (диапазоны осмысленных и посторонних запросов ПЕРЕКРЫВАЮТСЯ, см.
        # routers/search.py) — модель должна знать, что это догадка по
        # смыслу, а не точное попадание, и проверить содержимое через
        # get_note, прежде чем отвечать по нему.
        entry["match"] = "по смыслу, не точное совпадение слов"
        results.append(entry)

    if results:
        return {"results": results}

    # Не нашлось ни точно, ни по смыслу — последняя попытка: полнотекст по
    # ЛЮБОМУ слову запроса, а не по всем сразу. Модель пишет запрос
    # естественной фразой («проблемы с машиной»), и строгий AND на такой
    # фразе почти всегда пуст.
    #
    # РАНЬШЕ ЭТО СТОЯЛО ВЫШЕ и было главным источником мусора. Проверено на
    # боевой базе: «проблемы с машиной» — строгий поиск 0 результатов,
    # мягкий 20, и все двадцать не по теме («Career Master File», «Контракты
    # Мужа»), потому что совпало отдельное слово. Модель получала их без
    # всякой пометки, как точные попадания, а настоящий ответ («Обслуживание»
    # по смыслу) в эту двадцатку не попадал вовсе — его вытесняли.
    #
    # Поэтому теперь: только когда пусто и точно, и по смыслу; впятеро
    # меньше результатов; и с честной пометкой, что совпало одно слово.
    loose = await search_items(ctx.db, ctx.user_id, query, material_types=types, limit=_MAX_LOOSE_HITS, match="or")
    for item in loose:
        entry = _serialize(item)
        entry["match"] = "совпало отдельное слово запроса, скорее всего не по теме"
        results.append(entry)

    return {"results": results}
