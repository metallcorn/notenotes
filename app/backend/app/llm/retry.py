"""Повтор запроса к LLM-провайдеру при 429 и временных 5xx.

Почему это понадобилось. Ни один из трёх клиентов не переживал 429 вовсе:
одна ошибка — и ход диалога падал. При этом провайдер в самой ошибке
говорит, когда можно повторить. Замер free tier Gemini 2026-09-10 нашим
ключом:

    quotaId:    GenerateRequestsPerMinutePerProjectPerModel-FreeTier
    model:      gemini-2.5-flash
    quotaValue: 5
    "Please retry in 10.2s"

Пять запросов в минуту — а один ход ассистента это 2-5 вызовов подряд
(search_base, get_note, web_search, ответ). Без повтора один вопрос
пользователя упирается в потолок сам по себе, на середине хода. С
повтором те же пять в минуту — это не «не работает», а «медленно».

Нужно это не только Gemini: у Mistral 429 при всплеске тоже бывает, и
там задержка обычно секунда-две, то есть повтор почти незаметен.

ПОТОЛОК ОБЯЗАТЕЛЕН. На том конце сидит живой человек и смотрит на
«печатает…». Лучше честная ошибка через полминуты, чем молчание на пять
минут: у вызывающего кода есть свой запасной путь (тихая эскалация на
модель покрупнее, см. _run_dialog_turn_locked), и он должен успеть
сработать.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re

import httpx

logger = logging.getLogger(__name__)

# 429 — квота. 5xx — временные сбои на стороне провайдера: 503 от Gemini
# поймана вживую при тех же замерах, ответ был просто «Service
# Unavailable» без всякой квоты. Повтор безопасен: вызов чата не имеет
# побочных эффектов, дублировать нечего.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

MAX_ATTEMPTS = 3
# Суммарное ожидание на ОДИН вызов. Ход состоит из нескольких вызовов,
# поэтому потолок здесь напрямую задаёт худшее время ответа в чате.
MAX_TOTAL_WAIT_SECONDS = 25.0

_RETRY_DELAY_RE = re.compile(r"\"retryDelay\"\s*:\s*\"(\d+(?:\.\d+)?)s\"")
_RETRY_IN_RE = re.compile(r"retry in (\d+(?:\.\d+)?)s", re.IGNORECASE)


def _hinted_delay(resp: httpx.Response) -> float | None:
    """Сколько провайдер САМ просит подождать, если он это сказал.

    Три формы, все встречаются вживую: заголовок Retry-After (Mistral,
    OpenAI-совместимые), поле retryDelay в structured-ошибке Gemini и
    та же величина словами в тексте сообщения.
    """
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return float(header.strip())
        except ValueError:
            # Retry-After умеет быть и HTTP-датой. Разбирать её ради
            # редкого случая незачем — уйдём на обычную выдержку.
            pass
    try:
        body = resp.text
    except Exception:
        return None
    for pattern in (_RETRY_DELAY_RE, _RETRY_IN_RE):
        found = pattern.search(body)
        if found:
            return float(found.group(1))
    return None


def _backoff_delay(attempt: int) -> float:
    """Выдержка, когда провайдер ничего не подсказал: 1с, 2с, 4с.

    Разброс нужен не для красоты: несколько ходов, упавших в одну и ту же
    секунду (например, два открытых чата), иначе повторятся одновременно
    и снова упрутся вместе.
    """
    return (2.0**attempt) * (0.75 + random.random() * 0.5)


async def post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    max_total_wait: float = MAX_TOTAL_WAIT_SECONDS,
    **kwargs,
) -> httpx.Response:
    """POST с повтором по 429 и временным 5xx.

    Возвращает последний ответ КАК ЕСТЬ — raise_for_status остаётся на
    вызывающем клиенте, чтобы разбор ошибок не разъезжался по файлам.
    Если бюджет ожидания исчерпан, повторов больше не делаем и отдаём
    ответ с ошибкой: пусть сработает запасной путь вызывающего.
    """
    waited = 0.0
    resp = None
    for attempt in range(max_attempts):
        resp = await client.post(url, **kwargs)
        if resp.status_code not in RETRYABLE_STATUSES:
            return resp
        if attempt == max_attempts - 1:
            break

        delay = _hinted_delay(resp)
        hinted = delay is not None
        if delay is None:
            delay = _backoff_delay(attempt)
        if waited + delay > max_total_wait:
            logger.warning(
                "LLM ответил %s, но ждать ещё %.1fс нельзя — бюджет %.0fс исчерпан (ждали %.1fс)",
                resp.status_code, delay, max_total_wait, waited,
            )
            break

        logger.warning(
            "LLM ответил %s, повтор %d из %d через %.1fс (%s)",
            resp.status_code, attempt + 1, max_attempts - 1, delay,
            "провайдер сам назвал задержку" if hinted else "обычная выдержка",
        )
        await asyncio.sleep(delay)
        waited += delay

    assert resp is not None  # max_attempts >= 1, цикл выполнился хотя бы раз
    return resp

# Что ответил провайдер, когда ответил ошибкой.
#
# Живой случай 10.10: ассистент в Telegram молчал, в логах — ровно
# «httpx.HTTPStatusError: Client error '400 Bad Request' for url
# https://api.mistral.ai/v1/chat/completions» и больше ничего. Причину
# (7.26 МБ base64 в истории диалога) пришлось доставать запросами к базе,
# хотя провайдер её наверняка написал в теле ответа — только его никто не
# читал: raise_for_status() тело выбрасывает.
#
# Обрезаем: тело ошибки бывает с эхом запроса, а запрос у нас как раз и
# бывает многомегабайтным — залить такое в журнал значит потерять журнал.
_ERROR_BODY_CHARS = 2000


def raise_for_status_with_body(resp: httpx.Response, provider: str) -> None:
    """raise_for_status, но сначала записать, ЧТО именно не понравилось."""
    if resp.is_success:
        return
    try:
        body = resp.text[:_ERROR_BODY_CHARS]
    except Exception:  # pragma: no cover — тело может быть нечитаемым
        body = "(тело ответа прочитать не удалось)"
    logger.error("%s ответил %s: %s", provider, resp.status_code, body)
    resp.raise_for_status()
