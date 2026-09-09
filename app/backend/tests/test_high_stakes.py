"""«Дорогая» тема определяется по СМЫСЛУ, а не по списку слов.

Список слов был и провалился дважды: сначала не распознавал «Что нужно с
документами?» и «надо заново замельдоваться» вовсе, а после дописывания
недостающих слов замер сдвинулся всего с 3,3,3 до 3,3,4.

Но главное возражение не в замере: список слов не масштабируется.
Английский, польский, новая тема, другая формулировка — и он мимо.
Дописывать по слову на каждый случай значит вечно чинить хвосты.

Здесь тема задаётся ОПИСАНИЕМ и сравнивается многоязычным эмбеддером.
Тесты работают на подменённых векторах: настоящие вызовы к API в юнит-
тестах недопустимы (деньги, сеть, недетерминированность). Реальное
разделение измерено отдельно на 16 живых примерах, цифры — в докстринге
app/high_stakes.py.
"""

import pytest

from app import high_stakes


@pytest.fixture(autouse=True)
def _reset_cache():
    high_stakes._anchor_vectors = None
    yield
    high_stakes._anchor_vectors = None


def _fake_embedder(mapping: dict[str, list[float]], default: list[float]):
    async def _embed(texts):
        return [mapping.get(t, default) for t in texts]
    return _embed


async def test_high_stakes_text_is_detected(monkeypatch):
    stakes_vec, everyday_vec = [1.0, 0.0], [0.0, 1.0]
    mapping = {a: stakes_vec for a in high_stakes.HIGH_STAKES_ANCHORS}
    mapping.update({a: everyday_vec for a in high_stakes.EVERYDAY_ANCHORS})
    mapping["Сколько парацетамола дать ребёнку 4 лет?"] = stakes_vec

    monkeypatch.setattr("app.embeddings.embed_texts", _fake_embedder(mapping, everyday_vec))
    assert await high_stakes.is_high_stakes_topic("Сколько парацетамола дать ребёнку 4 лет?")


async def test_everyday_text_is_not_flagged(monkeypatch):
    stakes_vec, everyday_vec = [1.0, 0.0], [0.0, 1.0]
    mapping = {a: stakes_vec for a in high_stakes.HIGH_STAKES_ANCHORS}
    mapping.update({a: everyday_vec for a in high_stakes.EVERYDAY_ANCHORS})

    monkeypatch.setattr("app.embeddings.embed_texts", _fake_embedder(mapping, everyday_vec))
    assert not await high_stakes.is_high_stakes_topic("Составь список покупок: молоко, хлеб")


async def test_embedder_failure_does_not_break_the_turn(monkeypatch):
    """Сбой провайдера НЕ роняет ход и НЕ включает защиту: разговор идёт
    как обычный. Обратный выбор — считать всё «дорогим» при сбое — сделал
    бы ассистента бесполезно-осторожным ровно тогда, когда он и так
    работает хуже."""
    async def _boom(texts):
        raise RuntimeError("провайдер недоступен")

    monkeypatch.setattr("app.embeddings.embed_texts", _boom)
    assert not await high_stakes.is_high_stakes_topic("Сколько парацетамола дать ребёнку?")


async def test_very_short_text_is_not_judged(monkeypatch):
    """«ок», «да» — судить не по чем, и лишний вызов эмбеддера ни к чему."""
    called = False

    async def _track(texts):
        nonlocal called
        called = True
        return [[1.0, 0.0]] * len(texts)

    monkeypatch.setattr("app.embeddings.embed_texts", _track)
    assert not await high_stakes.is_high_stakes_topic("ок")
    assert not called, "короткий текст не должен стоить вызова к API"


async def test_anchors_are_embedded_once(monkeypatch):
    """Описания тем не меняются — эмбеддить их на каждое сообщение значило
    бы платить за одно и то же."""
    calls = 0
    stakes_vec, everyday_vec = [1.0, 0.0], [0.0, 1.0]
    mapping = {a: stakes_vec for a in high_stakes.HIGH_STAKES_ANCHORS}
    mapping.update({a: everyday_vec for a in high_stakes.EVERYDAY_ANCHORS})

    async def _counting(texts):
        nonlocal calls
        calls += 1
        return [mapping.get(t, everyday_vec) for t in texts]

    monkeypatch.setattr("app.embeddings.embed_texts", _counting)
    await high_stakes.is_high_stakes_topic("Первый достаточно длинный вопрос про визу")
    first = calls
    await high_stakes.is_high_stakes_topic("Второй достаточно длинный вопрос про визу")
    # На второй раз — только сам текст, без повторного прогона описаний.
    assert calls - first == 1
