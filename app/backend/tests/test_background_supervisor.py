"""_supervised — для вечных воркеров, _once — для одноразовых задач.

Реальный случай (2026-09-07): догоняющая индексация векторов была
обёрнута в _supervised. Она завершается штатно, отработав очередь, а
_supervised считает возврат сбоем и запускает заново — без паузы, в
плотном цикле. Postgres держал 93% CPU на повторяющемся тяжёлом запросе,
и в логах при этом не было ни одной ошибки: формально всё работало.
"""

import asyncio

import pytest

from app.main import _once, _supervised


async def test_supervised_restarts_a_worker_that_returns():
    """Возврат из вечного воркера — это сбой, и перезапуск тут правильный:
    так ведут себя очереди, которые не должны останавливаться."""
    calls = 0

    async def worker():
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise asyncio.CancelledError
        return

    with pytest.raises(asyncio.CancelledError):
        await _supervised("test", worker)
    assert calls == 3


async def test_once_does_not_restart_a_finished_task():
    """Одноразовая задача не должна повторяться — иначе получаем ровно тот
    цикл, что положил Postgres на 93%."""
    calls = 0

    async def task():
        nonlocal calls
        calls += 1

    await _once("test", task)
    assert calls == 1


async def test_once_swallows_errors_without_retrying():
    """Ошибка пишется в лог, но повтора нет: упавший проход упрётся в ту
    же причину, а плотный цикл повторов дороже недоделанной работы."""
    calls = 0

    async def failing():
        nonlocal calls
        calls += 1
        raise RuntimeError("сломалось")

    await _once("test", failing)  # не должно выбросить наружу
    assert calls == 1
