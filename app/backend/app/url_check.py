from __future__ import annotations

import httpx

from app.link_preview import _check_request_url, _validate_url, _SSRFBlocked

# Виджет «Проверить по ссылке» в заметке (extensions/UrlCheckAttachment.ts):
# GET по сохранённому URL, результат кладётся прямо в атрибуты карточки.
# SSRF-guard — не свой, а импорт из link_preview.py (тот же приём, что уже
# в кодовой базе — pdf_processing.py импортирует _analyze/_split_ticket_marker
# из vision.py напрямую): резолвит хост сам, блокирует private/loopback/
# link-local/reserved/multicast/unspecified адреса, перепроверяет на КАЖДОМ
# хопе редиректа через event_hooks — не только первый URL, иначе DNS
# rebinding/редирект на внутренний адрес обошли бы проверку.
TIMEOUT = httpx.Timeout(10.0)
MAX_BODY_BYTES = 512 * 1024

# Осознанно узкий масштаб: только GET, без тела запроса. Кастомные
# заголовки/авторизация раньше были запрещены целиком ("физически некуда
# положить" учётные данные) — пользователь explicitly попросил разрешить
# для СВОЕГО, некритичного сайта, с осознанием, что значение хранится
# открытым текстом в data-headers виджета (routers/url_checks.py,
# tools/url_check.py) — видно всем с доступом к спейсу, в исходнике
# страницы, в бэкапах. Требует явного предупреждения при создании
# постоянного виджета (см. INSERT_URL_CHECK_BLOCK.description) — разовая
# проверка (test_url_request) ничего не сохраняет, там предупреждать не о чем.
_UNSAFE_HEADER_NAMES = {"host"}


def _build_request_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Чистая функция — тестируема без реального HTTP-вызова. host
    исключён: подмена меняла бы адресацию запроса внутри httpx, что не тот
    класс вещей, который пользователь имел в виду под 'подставь мой токен'."""
    request_headers = {"User-Agent": "Notenotesbot-url-check/1.0"}
    for name, value in (headers or {}).items():
        if name.strip().lower() in _UNSAFE_HEADER_NAMES:
            continue
        request_headers[name] = value
    return request_headers


async def check_url(url: str, headers: dict[str, str] | None = None) -> dict:
    """GET по URL, SSRF-safe. Возвращает {"status_code", "body"} либо
    {"error": "..."} — никогда не бросает наружу, тот же принцип, что
    read_website.fetch/link_preview.fetch_preview."""
    try:
        _validate_url(url)
    except _SSRFBlocked as exc:
        return {"error": str(exc)}

    request_headers = _build_request_headers(headers)

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            max_redirects=5,
            event_hooks={"request": [_check_request_url]},
        ) as client:
            async with client.stream("GET", url, headers=request_headers) as resp:
                body = b""
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BODY_BYTES:
                        break
                status_code = resp.status_code
    except (httpx.HTTPError, _SSRFBlocked) as exc:
        return {"error": f"Не удалось выполнить запрос: {exc}"}

    return {"status_code": status_code, "body": body.decode("utf-8", errors="replace")}
