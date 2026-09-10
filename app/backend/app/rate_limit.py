"""Ограничение частоты запросов по ключу.

Третья копия одного и того же счётчика (были в routers/debug_log.py и
routers/mcp.py) — вынесена, чтобы не разошлись.

Счётчик в памяти процесса, не в Redis. Это осознанно и достаточно: бэкенд
один процесс (CLAUDE.md — на 4 ГБ VPS второго не будет), а при
перезапуске сброс счётчика ничего не ломает. Появится второй процесс —
переносить в Redis, но не раньше.
"""

from __future__ import annotations

import ipaddress
import time
from collections import defaultdict

from fastapi import Request

_hits: dict[str, list[float]] = defaultdict(list)


def rate_limited(key: str, *, max_requests: int, window_seconds: int) -> bool:
    """True — лимит превышен, запрос надо отклонить.

    Заодно подчищает свой же словарь: без этого он рос бы по одному ключу
    на каждый IP навсегда, а IP-ключи как раз и приходят от кого угодно.
    """
    now = time.monotonic()
    hits = _hits[key]
    hits[:] = [t for t in hits if now - t < window_seconds]
    hits.append(now)
    if not hits:
        _hits.pop(key, None)
    return len(hits) > max_requests


def client_ip(request: Request) -> str:
    """Адрес клиента — ПОСЛЕДНИЙ в X-Forwarded-For, не первый.

    Тот же приём и та же причина, что в routers/auth.py и debug_log.py:
    Caddy дописывает свой адрес в конец, не перезаписывает заголовок. А
    первый адрес клиент подделывает сам — если брать его, ограничение
    обходится сменой заголовка, то есть не существует вовсе.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


def client_subnet(request: Request) -> str:
    """Ключ по подсети, а не по одному адресу.

    Для IPv6 иначе ограничение бесполезно: провайдер выдаёт /64 целиком,
    и «новый адрес» стоит нисколько — счётчик по одному адресу обходится
    в один шаг. Режем до /64 у IPv6 и до /32 (то есть до адреса) у IPv4.
    """
    ip = client_ip(request)
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if parsed.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return ip
