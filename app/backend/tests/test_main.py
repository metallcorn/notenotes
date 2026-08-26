"""_supervised (app/main.py) — реальный найденный случай: очередь OCR PDF
молча остановилась посреди пачки загрузок, помог только рестарт бэкенда.
_supervised перезапускает упавший фоновый воркер сам, без вмешательства."""
import asyncio

from app.main import _supervised


async def test_supervised_restarts_worker_after_it_raises(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    calls = 0

    async def flaky_worker():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("воркер упал")
        raise asyncio.CancelledError

    try:
        await _supervised("flaky", flaky_worker)
    except asyncio.CancelledError:
        pass

    assert calls == 3


async def test_supervised_propagates_cancellation_without_retry():
    calls = 0

    async def worker():
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError

    raised = False
    try:
        await _supervised("cancels", worker)
    except asyncio.CancelledError:
        raised = True

    assert raised
    assert calls == 1
