"""Повтор запроса к LLM при 429 и временных 5xx.

Тела ошибок здесь настоящие — сняты с живого ключа 2026-09-10, когда
измеряли лимиты free tier Gemini (5 запросов в минуту у 2.5-flash).
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.llm.retry import MAX_TOTAL_WAIT_SECONDS, _hinted_delay, post_with_retry

# Настоящий ответ Gemini на превышение минутной квоты, 2026-09-10.
GEMINI_429 = json.dumps(
    {
        "error": {
            "code": 429,
            "message": (
                "You exceeded your current quota. * Quota exceeded for metric: "
                "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
                "limit: 5, model: gemini-2.5-flash\nPlease retry in 10.214738512s."
            ),
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {
                            "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
                            "quotaValue": "5",
                        }
                    ],
                },
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "10s"},
            ],
        }
    }
)


def _response(status: int, body: str = "{}", headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, text=body, headers=headers or {}, request=httpx.Request("POST", "https://x"))


class _FakeClient:
    """Отдаёт заготовленные ответы по очереди и считает вызовы."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def post(self, url, **kwargs):
        self.calls += 1
        return self._responses.pop(0) if self._responses else _response(200)


@pytest.fixture
def no_sleep(monkeypatch):
    """Выдержку не ждём по-настоящему, но записываем, сколько просили."""
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("app.llm.retry.asyncio.sleep", fake_sleep)
    return slept


class TestПодсказкаПровайдера:
    def test_gemini_называет_задержку_в_structured_ошибке(self):
        assert _hinted_delay(_response(429, GEMINI_429)) == 10.0

    def test_заголовок_retry_after_имеет_приоритет(self):
        # Mistral и прочие OpenAI-совместимые отвечают заголовком.
        assert _hinted_delay(_response(429, GEMINI_429, {"Retry-After": "2"})) == 2.0

    def test_дата_в_retry_after_не_ломает_разбор(self):
        # Retry-After умеет быть HTTP-датой. Разбирать её не стали —
        # важно, что это не падение, а откат к обычной выдержке.
        resp = _response(429, "{}", {"Retry-After": "Wed, 10 Sep 2026 07:00:00 GMT"})
        assert _hinted_delay(resp) is None

    def test_без_подсказок_ничего_не_выдумываем(self):
        assert _hinted_delay(_response(503, "Service Unavailable")) is None


class TestПовтор:
    async def test_успех_с_первого_раза_не_ждёт(self, no_sleep):
        client = _FakeClient([_response(200)])
        resp = await post_with_retry(client, "https://x")
        assert resp.status_code == 200
        assert client.calls == 1
        assert no_sleep == []

    async def test_429_повторяется_и_проходит(self, no_sleep):
        client = _FakeClient([_response(429, GEMINI_429), _response(200)])
        resp = await post_with_retry(client, "https://x")
        assert resp.status_code == 200
        assert client.calls == 2
        assert no_sleep == [10.0]  # ровно столько, сколько попросил Google

    async def test_503_тоже_повторяется(self, no_sleep):
        # Поймана вживую у Gemini при замере: просто Service Unavailable,
        # без всякой квоты.
        client = _FakeClient([_response(503), _response(200)])
        resp = await post_with_retry(client, "https://x")
        assert resp.status_code == 200
        assert client.calls == 2

    async def test_обычная_ошибка_не_повторяется(self, no_sleep):
        # 400 — наш баг в запросе, повтор его не вылечит и только
        # потратит квоту.
        client = _FakeClient([_response(400, '{"error": "bad request"}')])
        resp = await post_with_retry(client, "https://x")
        assert resp.status_code == 400
        assert client.calls == 1
        assert no_sleep == []

    async def test_ошибка_отдаётся_как_есть_когда_попытки_кончились(self, no_sleep):
        # Не своё исключение, а последний ответ: разбор ошибок живёт в
        # клиентах, и запасной путь вызывающего должен увидеть статус.
        client = _FakeClient([_response(429, GEMINI_429)] * 3)
        resp = await post_with_retry(client, "https://x")
        assert resp.status_code == 429
        assert client.calls == 3

    async def test_бюджет_ожидания_не_превышается(self, no_sleep):
        """Человек смотрит на «печатает…» — молчать пять минут нельзя."""
        long_wait = json.dumps({"error": {"details": [{"retryDelay": "600s"}]}})
        client = _FakeClient([_response(429, long_wait)] * 3)

        resp = await post_with_retry(client, "https://x")

        assert resp.status_code == 429
        assert no_sleep == []  # 600с больше бюджета — не ждали вовсе
        assert client.calls == 1  # и не долбили провайдера впустую

    async def test_суммарное_ожидание_в_пределах_бюджета(self, no_sleep):
        client = _FakeClient([_response(429, '{"retryDelay": "9s"}')] * 3)
        await post_with_retry(client, "https://x")
        assert sum(no_sleep) <= MAX_TOTAL_WAIT_SECONDS

    async def test_без_подсказки_выдержка_растёт(self, no_sleep):
        client = _FakeClient([_response(503)] * 3)
        await post_with_retry(client, "https://x")
        assert len(no_sleep) == 2
        assert no_sleep[1] > no_sleep[0]  # 1с, потом 2с (с разбросом)


def test_наши_модули_логируют_на_info():
    """Уровень «app.*» должен быть INFO, иначе учёт токенов — мёртвый код.

    Логирование не настраивалось вовсе: в логах видно «INFO: GET /api/...»,
    но это собственный логгер uvicorn, а корневой оставался на WARNING.
    Из-за этого строка про попадания в кэш промпта не печаталась месяц, и
    на вопрос «работает ли кэш» ответа не было.
    """
    import logging

    import app.main  # noqa: F401  — настройка уровня происходит при импорте
    from app.core.config import get_settings

    assert get_settings().log_level.upper() == "INFO"
    # Проверяем УРОВЕНЬ логгера, а не isEnabledFor: последний учитывает
    # глобальный logging.disable, а его внутри прогона двигает сам pytest
    # (_pytest.logging). В нашем коде logging.disable не вызывается нигде,
    # так что в проде это различие не проявляется — но тест на isEnabledFor
    # падал бы всегда, проверяя чужой плагин вместо нашей настройки.
    assert logging.getLogger("app").level == logging.INFO
    # И handler. Уровень без handler'а — мёртвая настройка: записи INFO
    # уходят в logging.lastResort, а тот печатает только WARNING и выше.
    # Поймано 12.09 по пустому логу при живых вызовах MCP — этот самый
    # тест тогда был зелёным, потому что проверял только уровень.
    assert logging.getLogger("app").handlers, "уровень INFO без handler'а ничего не печатает"
    # Именно «app.*», не корневой: корневой поднял бы и httpx, который на
    # INFO печатает каждый исходящий запрос — в агентном цикле это шум.
    assert logging.getLogger("httpx").getEffectiveLevel() > logging.INFO


class TestОграничениеЧастотыПоПодсети:
    """IPv6 обходит ограничение по одному адресу за один шаг."""

    def _request(self, forwarded: str):
        from types import SimpleNamespace

        return SimpleNamespace(headers={"x-forwarded-for": forwarded}, client=None)

    def test_подделанный_первый_адрес_не_учитывается(self):
        """Caddy дописывает свой адрес В КОНЕЦ, не перезаписывает заголовок.

        Брать первый значит брать то, что клиент написал сам, — тогда
        ограничение обходится сменой заголовка, то есть не существует.
        """
        from app.rate_limit import client_ip

        assert client_ip(self._request("1.2.3.4, 203.0.113.9")) == "203.0.113.9"

    def test_ipv6_режется_до_подсети(self):
        """Провайдер выдаёт /64 целиком: «новый адрес» стоит нисколько."""
        from app.rate_limit import client_subnet

        a = client_subnet(self._request("2001:db8:abcd:1234::1"))
        b = client_subnet(self._request("2001:db8:abcd:1234::ffff"))
        assert a == b, "иначе лимит обходится сменой последнего сегмента адреса"

    def test_разные_подсети_не_путаются(self):
        from app.rate_limit import client_subnet

        a = client_subnet(self._request("2001:db8:abcd:1111::1"))
        b = client_subnet(self._request("2001:db8:abcd:2222::1"))
        assert a != b

    def test_ipv4_считается_по_адресу(self):
        from app.rate_limit import client_subnet

        assert client_subnet(self._request("203.0.113.9")) == "203.0.113.9"

    def test_словарь_счётчиков_не_растёт_бесконечно(self):
        """Ключи приходят от кого угодно — без уборки это утечка памяти."""
        import app.rate_limit as rl

        rl._hits.clear()
        rl.rate_limited("разовый", max_requests=5, window_seconds=0)
        # Окно нулевое: запись протухает сразу же и не должна оставаться.
        rl.rate_limited("разовый", max_requests=5, window_seconds=0)
        assert len(rl._hits) <= 1
        rl._hits.clear()
