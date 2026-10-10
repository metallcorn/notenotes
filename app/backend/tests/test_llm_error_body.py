"""Что провайдер сказал, когда ответил ошибкой.

Живой случай 10.10: ассистент в Telegram молчал, а в логах было ровно
«Client error '400 Bad Request' for url .../chat/completions» и больше
ничего. Причину — 7.26 МБ base64 в истории диалога — пришлось доставать
запросами к базе, хотя провайдер её почти наверняка написал в теле
ответа. raise_for_status() тело выбрасывает.
"""

from __future__ import annotations

import httpx
import pytest

from app.llm.retry import _ERROR_BODY_CHARS, raise_for_status_with_body


def _resp(status: int, body: str) -> httpx.Response:
    return httpx.Response(status, text=body, request=httpx.Request("POST", "https://api.mistral.ai/v1/chat/completions"))


def test_тело_ошибки_попадает_в_журнал(caplog):
    with caplog.at_level("ERROR"):
        with pytest.raises(httpx.HTTPStatusError):
            raise_for_status_with_body(_resp(400, '{"message":"Prompt contains 2000000 tokens, too long"}'), "Mistral")

    assert "too long" in caplog.text
    assert "Mistral" in caplog.text
    assert "400" in caplog.text


def test_исключение_по_прежнему_летит():
    """Запасной путь вызывающего (эскалация на модель покрупнее) завязан
    на исключение — журналирование не должно его съесть."""
    with pytest.raises(httpx.HTTPStatusError):
        raise_for_status_with_body(_resp(500, "boom"), "Groq")


def test_успешный_ответ_молчит(caplog):
    with caplog.at_level("ERROR"):
        raise_for_status_with_body(_resp(200, '{"choices":[]}'), "Mistral")

    assert caplog.text == ""


def test_огромное_тело_обрезается(caplog):
    """Тело ошибки бывает с эхом запроса, а запрос у нас как раз и бывает
    многомегабайтным — залить такое в журнал значит потерять журнал."""
    with caplog.at_level("ERROR"):
        with pytest.raises(httpx.HTTPStatusError):
            raise_for_status_with_body(_resp(400, "ы" * 500_000), "Mistral")

    assert len(caplog.text) < _ERROR_BODY_CHARS + 2000


def test_логгеры_приложения_живы_после_миграций():
    """Отдельная проверка на ловушку, из-за которой тест выше сначала
    падал при исправном коде.

    logging.config.fileConfig по умолчанию ВЫКЛЮЧАЕТ все уже созданные
    логгеры (disable_existing_loggers=True), а alembic/env.py её зовёт.
    В тестах миграции идут в том же процессе, поэтому после них
    logger.disabled == True у всего app.*, logger.error молча ничего не
    делает и caplog.records остаётся пустым. В проде миграции — отдельный
    процесс до uvicorn, так что там это не проявлялось: ловушка была
    ровно там, где её не видно.
    """
    import logging

    for name in ("app", "app.llm.retry", "app.routers.dialogs"):
        assert not logging.getLogger(name).disabled, f"логгер {name} выключен — записи в журнал пропадают молча"
