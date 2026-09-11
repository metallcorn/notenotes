"""Проверка «заметка пуста, а в истории есть содержимое».

Урок инцидента 2026-09-11: потерю данных чинили трижды, каждый раз — сам
баг. А его жертв никто не собирал: четыре заметки простояли пустыми от
двух до пяти недель, пока владелец не наткнулся сам. История версий
хранила их всё это время.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Item, ItemVersion, Space, SpaceMember


async def _note(db, user, content: str, *, history: str | None = None, days_ago: float = 0, kind="note"):
    space = Space(name="S", owner_id=user.id)
    db.add(space)
    await db.flush()
    db.add(SpaceMember(space_id=space.id, user_id=user.id))
    item = Item(space_id=space.id, author_id=user.id, title="Заметка", content=content,
                material_type=kind, properties={})
    db.add(item)
    await db.flush()
    if history is not None:
        db.add(ItemVersion(item_id=item.id, title="Заметка", content=history, author_id=user.id))
    item.updated_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    await db.commit()
    return item


async def _run(monkeypatch, db_session):
    """_find_recently_wiped открывает свою сессию — в тесте подменяем на
    нашу, чтобы видеть откатываемые данные."""
    import contextlib

    from app import cleanup

    @contextlib.asynccontextmanager
    async def same_session():
        yield db_session

    monkeypatch.setattr(cleanup, "async_session", same_session)
    return await cleanup._find_recently_wiped()


async def test_пустая_с_историей_находится(db_session, test_user, monkeypatch):
    item = await _note(db_session, test_user, "", history="Тут было 3184 символа тренировок")

    found = await _run(monkeypatch, db_session)

    assert str(item.id) in {i for i, _, _ in found}


async def test_намеренно_пустая_без_истории_не_тревожит(db_session, test_user, monkeypatch):
    """Пустая заметка может быть и намеренно пустой — только что созданной."""
    await _note(db_session, test_user, "", history=None)

    assert await _run(monkeypatch, db_session) == []


async def test_непустая_не_тревожит(db_session, test_user, monkeypatch):
    await _note(db_session, test_user, "живой текст", history="старый текст")

    assert await _run(monkeypatch, db_session) == []


async def test_старое_обнуление_не_тревожит(db_session, test_user, monkeypatch):
    """Жертвы прошлых инцидентов уже восстановлены руками; напоминать о них
    каждые шесть часов — шум, за которым не заметишь новое."""
    await _note(db_session, test_user, "", history="давно потеряно", days_ago=30)

    assert await _run(monkeypatch, db_session) == []


async def test_диалоги_не_считаются(db_session, test_user, monkeypatch):
    """У диалога сообщения в properties, пустой content — норма."""
    await _note(db_session, test_user, "", history="x" * 50, kind="dialog")

    assert await _run(monkeypatch, db_session) == []
