"""Catch-all SPA-роут не должен отвечать за API.

Найдено 10.10 простой проверкой живого сервера:

    GET /api/такого-нет  →  200 OK, и в теле index.html

Catch-all подключён последним и перехватывал всё, включая опечатки в
адресах API. Два следствия, оба неприятные:

  * фронтенд на такой ответ падал с «Unexpected token '<'» — ошибка
    указывала на разбор JSON, а не на неверный адрес;
  * в логах любой сканер получал 200 на что угодно («GET
    /credentials.json 200 OK», «GET /.config/gcloud/... 200 OK»), и
    настоящие 404 в этом шуме не разглядеть.
"""

from __future__ import annotations

import pytest

from app.main import STATIC_DIR

pytestmark = pytest.mark.skipif(not STATIC_DIR.is_dir(), reason="нет собранного фронтенда — catch-all не подключён")


async def test_неизвестный_api_путь_даёт_404(client):
    r = await client.get("/api/такого-нет-точно")

    assert r.status_code == 404
    assert "<!doctype html>" not in r.text.lower(), "HTML вместо JSON ломает разбор на клиенте"


async def test_неизвестный_api_путь_с_хвостом(client):
    assert (await client.get("/api/items/нет/такого/пути")).status_code == 404


async def test_страница_приложения_по_прежнему_отдаётся(client):
    """Главное, что нельзя сломать: любой НЕ-api путь — это маршрут
    фронтенда (?item=..., /settings и прочее), и он обязан отдавать
    index.html, иначе перезагрузка страницы в приложении даст 404."""
    r = await client.get("/какой-то/маршрут/приложения")

    assert r.status_code == 200
    assert "<!doctype html>" in r.text.lower()


async def test_index_не_кэшируется(client):
    """Закэшированный index.html молча держит человека на предыдущем
    деплое — это уже ловили."""
    r = await client.get("/")

    assert r.headers.get("cache-control") == "no-store"


async def test_настоящий_api_путь_работает(client):
    """Контроль: 404 отдаётся именно на неизвестное, а не на всё под /api."""
    assert (await client.get("/api/health")).status_code == 200
