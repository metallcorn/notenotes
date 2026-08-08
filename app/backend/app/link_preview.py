import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

MAX_BODY_BYTES = 2 * 1024 * 1024
TIMEOUT = httpx.Timeout(10.0)


class _SSRFBlocked(Exception):
    pass


def _assert_public_host(hostname: str) -> None:
    # Единственное место в проекте, где бэкенд по запросу пользователя
    # обращается на произвольный URL — классический SSRF-вектор (запрос
    # на localhost/внутренний IP сервера/облачные метаданные). Резолвим
    # хост САМИ и проверяем результат, а не полагаемся на то, что httpx
    # "просто" сходит куда-то — редиректы и DNS rebinding тоже целятся
    # именно в этот момент, поэтому проверка идёт на каждый хоп (см. hooks
    # ниже), а не один раз до первого запроса.
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise _SSRFBlocked(f"Не удалось разрешить хост: {hostname}") from exc
    for family, _, _, _, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise _SSRFBlocked(f"Хост резолвится во внутренний адрес: {hostname} -> {ip}")


async def _check_request_url(request: httpx.Request) -> None:
    if request.url.scheme not in ("http", "https"):
        raise _SSRFBlocked(f"Недопустимая схема: {request.url.scheme}")
    _assert_public_host(request.url.host)


class _HeadParser(HTMLParser):
    """Достаёт только то, что нужно для карточки превью, останавливается
    на закрытии </head> — тело страницы может быть мегабайтами, которые
    незачем даже парсить."""

    def __init__(self) -> None:
        super().__init__()
        self.title: str | None = None
        self.og_title: str | None = None
        self.description: str | None = None
        self.og_description: str | None = None
        self.og_image: str | None = None
        self.icon: str | None = None
        self._in_title = False
        self.done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            prop = attrs_d.get("property", "").lower()
            name = attrs_d.get("name", "").lower()
            content = attrs_d.get("content", "")
            if prop == "og:title" and content:
                self.og_title = content
            elif prop == "og:description" and content:
                self.og_description = content
            elif prop == "og:image" and content:
                self.og_image = content
            elif name == "description" and content:
                self.description = content
        elif tag == "link":
            rel = attrs_d.get("rel", "").lower()
            href = attrs_d.get("href", "")
            if "icon" in rel and href:
                self.icon = href
        elif tag == "head":
            pass
        elif tag == "body":
            self.done = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "head":
            self.done = True

    def handle_data(self, data: str) -> None:
        if self._in_title and self.title is None:
            self.title = data.strip()


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise _SSRFBlocked("Недопустимая схема")
    if not parsed.hostname:
        raise _SSRFBlocked("Нет хоста")
    _assert_public_host(parsed.hostname)
    return url


async def fetch_preview(url: str) -> dict:
    """Возвращает dict с title/description/image_url/favicon_url либо
    fetch_failed=True, если сайт не ответил или заблокирован SSRF-проверкой.
    Никогда не бросает наружу — вызывающий роутер всегда получает валидный
    результат для сохранения в кэш."""
    try:
        _validate_url(url)
    except _SSRFBlocked:
        return {"fetch_failed": True}

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            max_redirects=5,
            event_hooks={"request": [_check_request_url]},
        ) as client:
            async with client.stream("GET", url, headers={"User-Agent": "Notenotesbot-link-preview/1.0"}) as resp:
                if resp.status_code >= 400:
                    return {"fetch_failed": True}
                content_type = resp.headers.get("content-type", "")
                if "html" not in content_type and content_type:
                    return {"fetch_failed": True}
                body = b""
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BODY_BYTES:
                        break
                final_url = str(resp.url)
    except (httpx.HTTPError, _SSRFBlocked):
        return {"fetch_failed": True}

    parser = _HeadParser()
    try:
        parser.feed(body.decode("utf-8", errors="replace"))
    except Exception:
        return {"fetch_failed": True}

    title = parser.og_title or parser.title
    description = parser.og_description or parser.description
    image_url = urljoin(final_url, parser.og_image) if parser.og_image else None
    favicon_url = urljoin(final_url, parser.icon) if parser.icon else urljoin(final_url, "/favicon.ico")

    if not title:
        return {"fetch_failed": True}

    return {
        "title": title[:500],
        "description": (description or "")[:1000],
        "image_url": image_url,
        "favicon_url": favicon_url,
        "fetch_failed": False,
    }
