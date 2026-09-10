"""search_base ищет и по смыслу, а не только по словам.

Зачем это понадобилось. Полнотекстовый поиск идёт по to_tsvector('simple')
— конфигурации БЕЗ словаря (в базе перемешаны русский, польский и
английский). Словоформы не склеиваются, проверено прямо в боевой базе:

    select to_tsvector('simple','купить продукты')
        @@ to_tsquery('simple','покупка');   ->  f

То есть ассистент не находил заметку пользователя, если тот спрашивал не
теми словами, какими записывал. Индекс эмбеддингов при этом был построен
(225 записей, 503 куска) и работал в веб-поиске — ассистенту его просто
не подключили.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.tools import search_base


def _item(title: str, content: str = "", material_type: str = "note"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        title=title,
        content=content,
        material_type=material_type,
        folder_id=None,
        space_id=uuid.uuid4(),
        properties={},
    )


@pytest.fixture
def stub(monkeypatch):
    """Подменяет оба поиска: тест про склейку выдач, не про сами поиски."""
    state = {"fulltext": [], "semantic": [], "semantic_calls": 0, "raises": False}

    async def fake_fulltext(*args, **kwargs):
        return list(state["fulltext"])

    async def fake_semantic(db, user_id, query, **kwargs):
        state["semantic_calls"] += 1
        if state["raises"]:
            raise RuntimeError("эмбеддер недоступен")
        return list(state["semantic"])

    monkeypatch.setattr(search_base, "search_items", fake_fulltext)
    monkeypatch.setattr(search_base, "search_semantic", fake_semantic)
    return state


def _ctx():
    return SimpleNamespace(db=None, user_id=uuid.uuid4(), space_id=uuid.uuid4(), client_timezone="UTC")


async def test_смысловое_совпадение_доезжает_и_помечено(stub):
    """Тот самый случай: спросили «покупка», записано «купить продукты»."""
    note = _item("Список на неделю", "купить продукты: молоко, хлеб")
    stub["semantic"] = [(note, 0.81, "купить продукты: молоко, хлеб")]

    out = await search_base.handle(_ctx(), {"query": "покупка"})

    assert len(out["results"]) == 1
    found = out["results"][0]
    assert found["title"] == "Список на неделю"
    # Пометка обязательна: смысловое совпадение — догадка, и модель должна
    # это знать, прежде чем отвечать по нему.
    assert found["match"] == "по смыслу, не точное совпадение слов"
    # excerpt — совпавший КУСОК, а не начало заметки.
    assert found["excerpt"] == "купить продукты: молоко, хлеб"


async def test_точные_совпадения_идут_первыми_и_без_пометки(stub):
    exact = _item("Страховка PZU", "полис действует до 20.12.2026")
    guess = _item("Машина", "техосмотр в марте")
    stub["fulltext"] = [exact]
    stub["semantic"] = [(guess, 0.79, "техосмотр в марте")]

    out = await search_base.handle(_ctx(), {"query": "страховка"})

    assert [r["title"] for r in out["results"]] == ["Страховка PZU", "Машина"]
    assert "match" not in out["results"][0]
    assert out["results"][1]["match"].startswith("по смыслу")


async def test_слабое_совпадение_отсекается_порогом(stub):
    """0.75 ИЗМЕРЕН на боевой базе — посторонние запросы дают ~0.69-0.75.

    Ниже порога в выдачу попадал бы паспорт в ответ на вопрос про физику.
    """
    stub["semantic"] = [(_item("Что угодно"), 0.70, "текст")]

    out = await search_base.handle(_ctx(), {"query": "квантовая хромодинамика"})

    assert out["results"] == []


async def test_одна_запись_не_показывается_дважды(stub):
    """Найденное обоими поисками — одна строка, а не две подряд."""
    note = _item("Страховка PZU", "полис PZU")
    stub["fulltext"] = [note]
    stub["semantic"] = [(note, 0.9, "полис PZU")]

    out = await search_base.handle(_ctx(), {"query": "страховка"})

    assert len(out["results"]) == 1
    assert "match" not in out["results"][0]  # осталось точным


async def test_смысловых_не_больше_потолка(stub):
    """Смысловой поиск возвращает хоть что-то почти всегда — длинный хвост
    создавал бы у модели ложное впечатление, будто нашлось много."""
    stub["semantic"] = [(_item(f"Заметка {i}"), 0.9, "текст") for i in range(20)]

    out = await search_base.handle(_ctx(), {"query": "что-нибудь"})

    assert len(out["results"]) == search_base._MAX_SEMANTIC_HITS


async def test_падение_эмбеддера_не_роняет_поиск(stub):
    """Смысловой поиск — дополнение, а не замена.

    Нет ключа, сеть, лимит — полнотекстовая выдача обязана дойти как
    раньше, иначе ассистент теряет базовую способность из-за
    необязательной.
    """
    stub["fulltext"] = [_item("Страховка PZU", "полис")]
    stub["raises"] = True

    out = await search_base.handle(_ctx(), {"query": "страховка"})

    assert [r["title"] for r in out["results"]] == ["Страховка PZU"]


async def test_пустой_запрос_не_дёргает_эмбеддер(stub):
    """Пустой запрос — не повод платить за вектор."""
    out = await search_base.handle(_ctx(), {"query": "   "})

    assert out == {"results": []}
    assert stub["semantic_calls"] == 0


def test_описание_инструмента_предупреждает_о_догадке():
    """Модель должна знать, что match=«по смыслу» надо проверять.

    Иначе смысловое совпадение читается ею как точное, и она отвечает по
    заметке, которая вообще не про то.
    """
    description = search_base.DEFINITION.description
    assert "по смыслу" in description.lower()
    assert "get_note" in description
