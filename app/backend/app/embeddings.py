"""Семантический поиск: нарезка записей, векторы, поиск по смыслу (ТЗ §10).

Зачем вообще. Полнотекстовый поиск (routers/search.py) работает на
конфигурации 'simple' — без словаря, то есть без морфологии: «купить»,
«покупка» и «закупка» для него три разных слова. Так выбрано сознательно
(в базе перемешаны русский, польский и английский, ни один словарь не
подошёл бы всем), но цена — поиск не находит по смыслу. Векторный решает
морфологию, синонимы и разноязычность разом.

Он НЕ заменяет полнотекстовый, а дополняет: по ТЗ §10 быстрые результаты
показываются мгновенно, а семантические подгружаются следом отдельным
блоком «расширенный поиск». Это один поток с прогрессивной загрузкой, а
не два режима.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import async_session
from app.models import Item, ItemEmbedding, Space, SpaceMember

logger = logging.getLogger(__name__)

# Размерность mistral-embed. Зашита и здесь, и в миграции 0031: pgvector
# требует фиксированной размерности для индекса, поэтому смена модели на
# другую размерность означает миграцию и полную переиндексацию.
EMBEDDING_DIM = 1024

# Лимит модели — 8192 токена. Режем с большим запасом по СИМВОЛАМ, а не по
# токенам: точный подсчёт требовал бы токенизатора провайдера, а
# кириллица даёт заметно больше токенов на символ, чем латиница. 4000
# символов кириллицы — примерно 1300–2000 токенов, до потолка далеко даже
# на самом плохом тексте.
_CHUNK_CHARS = 4000
# Нахлёст между кусками: фраза, попавшая на стык, иначе не найдётся ни в
# одном из них целиком.
_CHUNK_OVERLAP = 400

# Типы, которые имеет смысл искать по смыслу. dialog сознательно НЕ здесь:
# разговоры с ассистентом это не контент базы, они длинные, их много (102
# против 206 заметок), и семантические попадания в них зашумляли бы выдачу
# ровно тем, что пользователь уже видел в чате.
INDEXABLE_TYPES = ("note", "ticket", "list", "table")

_queue: "asyncio.Queue[uuid.UUID]" = asyncio.Queue()


def enqueue_embedding(item_id: uuid.UUID) -> None:
    """Поставить запись в очередь на индексацию. Тот же приём, что у
    autotag.enqueue_autotag: очередь в памяти процесса, воркер разбирает её
    по одной. Потеря очереди при перезапуске не страшна — пропущенное
    находится по content_hash (см. find_stale_item_ids)."""
    _queue.put_nowait(item_id)


def content_hash(title: str, content: str) -> str:
    return hashlib.sha256(f"{title}\n{content}".encode()).hexdigest()


def split_into_chunks(text_value: str) -> list[str]:
    """Нарезка по абзацам с нахлёстом.

    По абзацам, а не по символам вслепую: разрыв посреди предложения даёт
    кусок, вектор которого описывает обрубок, а не мысль. Абзац —
    естественная граница смысла в markdown, а формат хранения у нас всегда
    markdown (CLAUDE.md).

    Абзац длиннее лимита (таблица, длинный список, распознанный текст без
    переносов) режется жёстко — иначе он не влез бы вовсе.
    """
    normalized = text_value.strip()
    if not normalized:
        return []
    if len(normalized) <= _CHUNK_CHARS:
        return [normalized]

    paragraphs = re.split(r"\n\s*\n", normalized)
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) > _CHUNK_CHARS:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(para), _CHUNK_CHARS - _CHUNK_OVERLAP):
                chunks.append(para[i : i + _CHUNK_CHARS])
            continue
        if current and len(current) + len(para) + 2 > _CHUNK_CHARS:
            chunks.append(current)
            # Нахлёст: хвост предыдущего куска уходит в начало следующего.
            current = current[-_CHUNK_OVERLAP:] + "\n\n" + para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Векторы для списка текстов одним запросом.

    Провайдер жёстко Mistral, в отличие от чат-клиента с его абстракцией
    LLMClient: размерность вектора зашита в схему таблицы и в индекс, так
    что «просто переключить провайдера» тут всё равно нельзя — потребуется
    миграция и переиндексация. Заводить абстракцию, которая обещает
    несуществующую взаимозаменяемость, вреднее, чем не заводить.
    Европейский провайдер — по ТЗ §20.
    """
    if not texts:
        return []
    settings = get_settings()
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY не задан — векторный поиск недоступен")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.mistral.ai/v1/embeddings",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={"model": settings.embedding_model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
    # Порядок в ответе соответствует порядку входа, но index приходит явно —
    # сортируем по нему, а не полагаемся на порядок.
    return [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]


def _vector_literal(vec: list[float]) -> str:
    """pgvector принимает вектор текстом вида '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{v:.7g}" for v in vec) + "]"


async def index_item(db: AsyncSession, item: Item) -> int:
    """Пересчитать векторы одной записи. Возвращает число кусков.

    Сейф исключён жёстко: сервер хранит там только шифротекст (CLAUDE.md,
    ТЗ §16.1), индексировать нечего, а отправлять его во внешний API тем
    более незачем. Тот же фильтр, что в полнотекстовом поиске.
    """
    if item.material_type not in INDEXABLE_TYPES or item.deleted_at is not None:
        await _drop_embeddings(db, item.id)
        return 0

    space = await db.get(Space, item.space_id)
    if space is None or space.is_vault:
        await _drop_embeddings(db, item.id)
        return 0

    title = item.title or ""
    content = item.content or ""
    chunks = split_into_chunks(f"{title}\n\n{content}" if title else content)
    if not chunks:
        await _drop_embeddings(db, item.id)
        return 0

    vectors = await embed_texts(chunks)
    digest = content_hash(title, content)

    # Полная замена, а не досчёт: кусков после правки может стать меньше,
    # и оставшиеся «хвосты» от прошлой версии всплывали бы в поиске как
    # содержимое, которого в заметке уже нет.
    await _drop_embeddings(db, item.id)
    for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
        await db.execute(
            text(
                "insert into item_embeddings (id, item_id, chunk_index, chunk_text, embedding, content_hash) "
                "values (:id, :item_id, :idx, :chunk, cast(:vec as vector), :hash)"
            ),
            {
                "id": uuid.uuid4(),
                "item_id": item.id,
                "idx": i,
                "chunk": chunk,
                "vec": _vector_literal(vec),
                "hash": digest,
            },
        )
    await db.commit()
    return len(chunks)


async def _drop_embeddings(db: AsyncSession, item_id: uuid.UUID) -> None:
    await db.execute(text("delete from item_embeddings where item_id = :id"), {"id": item_id})


async def find_stale_item_ids(db: AsyncSession, limit: int = 200) -> list[uuid.UUID]:
    """Записи, которые не проиндексированы или устарели.

    Это и есть страховка от того, что очередь живёт в памяти: после
    перезапуска, после правки заметки мимо очереди и при первом внедрении
    (когда в базе уже лежат сотни записей) недостающее находится одним
    запросом, а не теряется молча.

    Сравнение по content_hash, а не по updated_at: правка тегов или
    переименование папки меняют updated_at, но не текст — переиндексация
    там была бы тратой запросов к API впустую.

    convert_to(..., 'UTF8'), а НЕ text::bytea. Поймано на боевой базе сразу
    после выкатки: приведение текста к bytea разбирает содержимое как
    escape-последовательности, и первая же заметка с обратным слэшем
    роняет весь запрос («invalid input syntax for type bytea»).
    Проиндексировалось ровно 20 записей — одна пачка, — после чего
    догоняющий проход падал. convert_to кодирует текст как UTF-8 байты,
    что и совпадает с content_hash в Python (str.encode()).
    """
    rows = await db.execute(
        text(
            """
            select i.id
            from items i
            join spaces s on s.id = i.space_id
            left join lateral (
                select content_hash from item_embeddings e
                where e.item_id = i.id limit 1
            ) e on true
            where i.deleted_at is null
              and i.material_type = any(:types)
              and s.is_vault = false
              -- Пустая запись (ни заголовка, ни текста) НИКОГДА не станет
              -- проиндексированной: резать нечего, строки в индексе не
              -- появляется, и без этого условия запрос возвращал бы её
              -- вечно. Поймано на боевой базе: 4 пустые заметки из 225
              -- загнали догоняющий проход в бесконечный цикл, бэкенд жёг
              -- 58% CPU, Postgres 37%.
              and length(trim(coalesce(i.title,'') || coalesce(i.content,''))) > 0
              and (e.content_hash is null or e.content_hash <> encode(
                    sha256(convert_to(
                        coalesce(i.title,'') || E'\\n' || coalesce(i.content,''), 'UTF8')), 'hex'))
            limit :limit
            """
        ),
        {"types": list(INDEXABLE_TYPES), "limit": limit},
    )
    return [r[0] for r in rows]


async def search_semantic(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    *,
    limit: int = 20,
    space_id: uuid.UUID | None = None,
) -> list[tuple[Item, float, str]]:
    """Поиск по смыслу. Возвращает (запись, близость 0..1, совпавший кусок).

    Права проверяются тем же способом, что в полнотекстовом поиске: join с
    space_members плюс жёсткое исключение сейфа. Дублировать логику доступа
    в двух местах опасно, но здесь запрос идёт явным SQL ради pgvector, так
    что условия повторены буквально — расхождение между ними означало бы
    утечку чужих записей, поэтому оно закрыто тестом.

    DISTINCT ON — одна запись в выдаче один раз, по её лучшему куску: без
    этого длинная заметка занимала бы всю первую страницу своими кусками.
    """
    query = query.strip()
    if not query:
        return []
    vectors = await embed_texts([query])
    vec = _vector_literal(vectors[0])

    sql = """
        select distinct on (i.id) i.id, 1 - (e.embedding <=> cast(:vec as vector)) as score, e.chunk_text
        from item_embeddings e
        join items i on i.id = e.item_id
        join spaces s on s.id = i.space_id
        join space_members m on m.space_id = i.space_id and m.user_id = :user_id
        where i.deleted_at is null
          and s.is_vault = false
          {space_filter}
        order by i.id, e.embedding <=> cast(:vec as vector)
    """.format(space_filter="and i.space_id = :space_id" if space_id else "")
    params: dict = {"vec": vec, "user_id": user_id}
    if space_id:
        params["space_id"] = space_id

    # Сортировка по близости — во внешнем запросе: DISTINCT ON требует,
    # чтобы ORDER BY начинался с различаемого выражения, поэтому внутри
    # порядок по i.id, а нужный порядок наводится снаружи.
    rows = await db.execute(
        text(f"select * from ({sql}) t order by t.score desc limit :limit"),
        {**params, "limit": limit},
    )
    scored = [(r[0], float(r[1]), r[2]) for r in rows]
    if not scored:
        return []

    items = {
        it.id: it
        for it in (await db.execute(select(Item).where(Item.id.in_([i for i, _, _ in scored])))).scalars()
    }
    return [(items[i], score, chunk) for i, score, chunk in scored if i in items]


async def _process(item_id: uuid.UUID) -> None:
    async with async_session() as db:
        item = await db.get(Item, item_id)
        if item is None:
            return
        # Текст не изменился — не тратим запрос к API. В очередь запись
        # попадает при ЛЮБОЙ правке, а правкой считается и перенос в папку,
        # и отметка галочки в списке, и смена тегов: без этой проверки
        # каждая такая мелочь стоила бы полного пересчёта векторов.
        if item.material_type in INDEXABLE_TYPES and item.deleted_at is None:
            current = content_hash(item.title or "", item.content or "")
            existing = (
                await db.execute(
                    select(ItemEmbedding.content_hash).where(ItemEmbedding.item_id == item_id).limit(1)
                )
            ).scalar_one_or_none()
            if existing == current:
                return
        n = await index_item(db, item)
        if n:
            logger.info("Проиндексировано %s: %d кусков", item_id, n)


async def run_worker() -> None:
    """Разбирает очередь индексации. Запускается из main.py рядом с
    autotag-воркером и по тому же образцу."""
    while True:
        item_id = await _queue.get()
        try:
            await _process(item_id)
        except Exception:
            logger.exception("Не удалось построить векторы для %s", item_id)
        finally:
            _queue.task_done()


async def run_backfill(batch: int = 20) -> int:
    """Догнать всё непроиндексированное. Возвращает число обработанных.

    Вызывается вручную (scripts) и один раз на старте: на момент внедрения
    в базе уже лежит несколько сотен записей, без этого векторный поиск
    находил бы только то, что создано после выкатки, и выглядел бы
    сломанным.
    """
    done = 0
    while True:
        try:
            async with async_session() as db:
                ids = await find_stale_item_ids(db, limit=batch)
        except Exception:
            # Сам поиск отставших тоже может упасть — так и случилось при
            # первой выкатке. Не даём этому оборвать проход молча: пишем
            # причину в лог, а не притворяемся, что всё проиндексировано.
            logger.exception("Backfill: не удалось получить список неиндексированных")
            return done
        if not ids:
            return done
        before = done
        for item_id in ids:
            try:
                await _process(item_id)
                done += 1
            except Exception:
                logger.exception("Backfill: не удалось проиндексировать %s", item_id)
                return done
        # Страховка от вечного цикла: если пачка обработана, а список
        # отставших не сократился, значит эти записи не индексируются в
        # принципе и следующий проход вернёт их снова. Условие выше
        # закрывает известную причину (пустой текст), эта проверка —
        # любую будущую.
        async with async_session() as db:
            if set(await find_stale_item_ids(db, limit=batch)) == set(ids):
                logger.warning(
                    "Backfill: %d записей не индексируются и не уходят из очереди, останавливаюсь: %s",
                    len(ids), [str(i) for i in ids[:5]],
                )
                return done
        if done == before:
            return done
