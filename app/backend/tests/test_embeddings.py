"""Семантический поиск: нарезка, индексация, права доступа (ТЗ §10).

Обращений к API эмбеддингов тут нет — embed_texts подменяется детермини-
рованной заглушкой. Проверяется НАША логика: как режется текст, что
попадает в индекс, а главное — что НЕ попадает и кому не отдаётся.
"""

import uuid

import pytest
from sqlalchemy import text

from app import embeddings
from app.embeddings import content_hash, search_semantic, split_into_chunks
from app.models import Item

DIM = embeddings.EMBEDDING_DIM


def _fake_vector(seed: str) -> list[float]:
    """Детерминированный вектор: одинаковый текст — одинаковый вектор,
    разный — разный. Этого достаточно, чтобы проверить, что поиск находит
    совпадение и соблюдает права; качество самой модели мы тут не тестируем."""
    h = sum(ord(c) for c in seed)
    v = [0.0] * DIM
    v[h % DIM] = 1.0
    return v


@pytest.fixture
def fake_embed(monkeypatch):
    async def _embed(texts: list[str]) -> list[list[float]]:
        return [_fake_vector(t) for t in texts]

    monkeypatch.setattr(embeddings, "embed_texts", _embed)
    return _embed


# --- нарезка ---------------------------------------------------------------

def test_short_text_is_a_single_chunk():
    assert split_into_chunks("Купить масло для машины") == ["Купить масло для машины"]


def test_empty_text_gives_no_chunks():
    assert split_into_chunks("") == []
    assert split_into_chunks("   \n\n  ") == []


def test_long_text_is_split_with_overlap():
    # 26 заметок из 206 в реальной базе длиннее 8000 символов — нарезка не
    # теоретическая надобность, а условие того, что они вообще попадут в
    # индекс: лимит mistral-embed 8192 токена.
    para = "Абзац про обслуживание автомобиля. " * 40  # ~1400 символов
    long_text = "\n\n".join([para] * 6)  # ~8400 символов
    chunks = split_into_chunks(long_text)

    assert len(chunks) > 1
    assert all(len(c) <= embeddings._CHUNK_CHARS for c in chunks)
    # Нахлёст: конец предыдущего куска встречается в начале следующего,
    # иначе фраза на стыке не нашлась бы ни в одном из них целиком.
    assert chunks[0][-100:] in chunks[1]


def test_paragraph_longer_than_limit_is_force_split():
    # Распознанный PDF или таблица могут прийти одним куском без переносов —
    # по абзацам такое не режется, нужен жёсткий разрез.
    monster = "х" * (embeddings._CHUNK_CHARS * 3)
    chunks = split_into_chunks(monster)
    assert len(chunks) >= 3
    assert all(len(c) <= embeddings._CHUNK_CHARS for c in chunks)


def test_content_hash_tracks_title_and_content():
    assert content_hash("A", "B") == content_hash("A", "B")
    assert content_hash("A", "B") != content_hash("A", "C")
    assert content_hash("A", "B") != content_hash("Z", "B")


# --- индексация и поиск ----------------------------------------------------

async def _make_note(auth_client, title: str, content: str, space_id: str) -> str:
    r = await auth_client.post(
        "/api/items", json={"space_id": space_id, "title": title, "content": content}
    )
    return r.json()["id"]


async def _space(auth_client, **kw) -> str:
    r = await auth_client.post("/api/spaces", json={"name": "S", **kw})
    return r.json()["id"]


async def test_indexed_note_is_found_by_matching_query(
    auth_client, db_session, test_user, fake_embed
):
    space_id = await _space(auth_client)
    note_id = await _make_note(auth_client, "Замена масла", "Сервис на Гродзиской", space_id)

    item = await db_session.get(Item, uuid.UUID(note_id))
    assert await embeddings.index_item(db_session, item) == 1

    # Запрос ровно тем же текстом, что лёг в индекс — заглушка даёт тот же
    # вектор, значит близость максимальна.
    chunks = split_into_chunks("Замена масла\n\nСервис на Гродзиской")
    hits = await search_semantic(db_session, test_user.id, chunks[0])
    assert [str(i.id) for i, _, _ in hits] == [note_id]
    assert hits[0][1] > 0.99


async def test_vault_content_is_never_indexed(auth_client, db_session, test_user, fake_embed):
    """Ключевое ограничение: в сейфе сервер хранит только шифротекст
    (CLAUDE.md, ТЗ §16.1). Векторы уходят во ВНЕШНИЙ API, поэтому попадание
    туда содержимого сейфа было бы не просто бесполезным, а утечкой."""
    vault_id = await _space(auth_client, is_vault=True, vault_salt="s", vault_verifier="v")
    note_id = await _make_note(auth_client, "Паспорт", "Секретные данные", vault_id)

    item = await db_session.get(Item, uuid.UUID(note_id))
    assert await embeddings.index_item(db_session, item) == 0

    rows = await db_session.execute(
        text("select count(*) from item_embeddings where item_id = :id"), {"id": uuid.UUID(note_id)}
    )
    assert rows.scalar_one() == 0


async def test_deleted_note_drops_out_of_the_index(auth_client, db_session, test_user, fake_embed):
    space_id = await _space(auth_client)
    note_id = await _make_note(auth_client, "Временная", "Текст", space_id)
    item = await db_session.get(Item, uuid.UUID(note_id))
    await embeddings.index_item(db_session, item)

    await auth_client.delete(f"/api/items/{note_id}")
    await db_session.refresh(item)
    assert await embeddings.index_item(db_session, item) == 0

    hits = await search_semantic(db_session, test_user.id, "Временная\n\nТекст")
    assert [str(i.id) for i, _, _ in hits] == []


async def test_reindex_replaces_old_chunks_instead_of_adding(
    auth_client, db_session, test_user, fake_embed
):
    """После правки кусков может стать МЕНЬШЕ. Если не удалять старые,
    хвосты прошлой версии всплывали бы в поиске как содержимое, которого
    в заметке уже нет."""
    space_id = await _space(auth_client)
    long_text = "\n\n".join(["Длинный абзац про машину. " * 60] * 5)
    note_id = await _make_note(auth_client, "Авто", long_text, space_id)

    item = await db_session.get(Item, uuid.UUID(note_id))
    many = await embeddings.index_item(db_session, item)
    assert many > 1

    item.content = "Коротко"
    await db_session.commit()
    assert await embeddings.index_item(db_session, item) == 1

    rows = await db_session.execute(
        text("select count(*) from item_embeddings where item_id = :id"), {"id": uuid.UUID(note_id)}
    )
    assert rows.scalar_one() == 1


async def test_stale_detection_finds_unindexed_and_skips_current(
    auth_client, db_session, test_user, fake_embed
):
    """Очередь индексации живёт в памяти процесса и теряется при
    перезапуске — поиск отставших по хэшу и есть страховка от этого."""
    space_id = await _space(auth_client)
    note_id = await _make_note(auth_client, "Ещё не в индексе", "Текст", space_id)

    stale = await embeddings.find_stale_item_ids(db_session)
    assert uuid.UUID(note_id) in stale

    item = await db_session.get(Item, uuid.UUID(note_id))
    await embeddings.index_item(db_session, item)

    stale_after = await embeddings.find_stale_item_ids(db_session)
    assert uuid.UUID(note_id) not in stale_after


async def test_other_users_notes_are_never_returned(
    auth_client, client, db_session, test_user, fake_embed
):
    """Права в семантическом поиске проверяются ОТДЕЛЬНЫМ запросом (явный
    SQL ради pgvector), а не тем же кодом, что в полнотекстовом. Логика
    доступа продублирована — значит расхождение между двумя местами
    возможно, и стоило бы утечки чужих записей. Тест закрывает именно это.
    """
    from app.security import hash_password
    from app.models import User

    stranger = User(username="stranger", password_hash=hash_password("x" * 12), name="Чужой")
    db_session.add(stranger)
    await db_session.commit()

    # Заметка нашего пользователя — она в индексе и находится им самим.
    space_id = await _space(auth_client)
    note_id = await _make_note(auth_client, "Мои финансы", "Зарплата и счета", space_id)
    item = await db_session.get(Item, uuid.UUID(note_id))
    await embeddings.index_item(db_session, item)

    query = split_into_chunks("Мои финансы\n\nЗарплата и счета")[0]
    assert [str(i.id) for i, _, _ in await search_semantic(db_session, test_user.id, query)] == [note_id]

    # Тот же запрос от чужого пользователя не находит ничего.
    assert await search_semantic(db_session, stranger.id, query) == []


async def test_stale_detection_survives_backslashes_in_content(
    auth_client, db_session, test_user, fake_embed
):
    """Регрессия, пойманная на БОЕВОЙ базе сразу после выкатки.

    Поиск отставших сравнивал хэш через text::bytea — а это приведение
    разбирает содержимое как escape-последовательности, и первая же
    заметка с обратным слэшем роняла весь запрос («invalid input syntax
    for type bytea»). Проиндексировалось ровно 20 записей, одна пачка,
    после чего догоняющий проход падал. Здесь текст, на котором это
    воспроизводится.
    """
    space_id = await _space(auth_client)
    tricky = "Путь C:\\Users\\test и regex \\d+ и хвост \\"
    note_id = await _make_note(auth_client, "Заметка с \\ слэшем", tricky, space_id)

    # Главное: запрос не падает.
    stale = await embeddings.find_stale_item_ids(db_session)
    assert uuid.UUID(note_id) in stale

    item = await db_session.get(Item, uuid.UUID(note_id))
    await embeddings.index_item(db_session, item)
    assert uuid.UUID(note_id) not in await embeddings.find_stale_item_ids(db_session)


async def test_sql_hash_matches_python_hash(auth_client, db_session, test_user, fake_embed):
    """Хэш считается в ДВУХ местах: в Python при индексации и в SQL при
    поиске отставших. Разойдись они — и каждая запись вечно считалась бы
    устаревшей, то есть переиндексировалась бы на каждом проходе, сжигая
    запросы к API впустую. Проверяем на не-ASCII и переносах."""
    space_id = await _space(auth_client)
    note_id = await _make_note(
        auth_client, "Ёлка «ёжик»", "Первая строка\n\nВторая — тире и ё", space_id
    )
    item = await db_session.get(Item, uuid.UUID(note_id))

    py_hash = content_hash(item.title or "", item.content or "")
    sql_hash = (
        await db_session.execute(
            text(
                "select encode(sha256(convert_to("
                "coalesce(title,'') || E'\\n' || coalesce(content,''), 'UTF8')), 'hex') "
                "from items where id = :id"
            ),
            {"id": item.id},
        )
    ).scalar_one()
    assert py_hash == sql_hash
