from __future__ import annotations

import re
from email.utils import getaddresses, parseaddr

# Реальная жалоба: пересылаешь себе письмо на notenotes-адрес — заметка
# попадает в папку с собственным именем пользователя, потому что From: в
# пересланном письме — это он сам, а не оригинальный автор письма
# (см. routers/mail_webhook.py). Эти функции — чистые, без БД/сети, чтобы
# их можно было проверить на реальных образцах писем изолированно.

_SEARCH_WINDOW_CHARS = 1500
_FROM_LINE_WINDOW_CHARS = 500

# Осознанно неполный список — не все клиенты/локали мира, а те, что реально
# встретились (Gmail EN/RU, Apple Mail, Outlook). Расширяется по мере
# находок, тот же подход, что у остальных парсеров в этой сессии
# (dialogs.py::_CATEGORY_KEYWORDS и т.п. — чиним по факту пробела, не
# пытаемся угадать всё сразу).
_FORWARD_MARKER_RE = re.compile(
    r"-{2,}\s*Forwarded message\s*-{2,}"
    r"|-{2,}\s*Пересланное сообщение\s*-{2,}"
    r"|-{2,}\s*Переслано письмо\s*-{2,}"
    r"|Begin forwarded message:"
    r"|-{2,}\s*Original Message\s*-{2,}",
    re.IGNORECASE,
)

_FROM_LINE_RE = re.compile(r"^\s*(?:From|От кого|От|Von|De)\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

# Старые версии Outlook пишут "From: Имя [mailto:адрес]" вместо
# "From: Имя <адрес>" — parseaddr() этого не понимает (ждёт угловые скобки).
_MAILTO_RE = re.compile(r"\[mailto:([^\]]+)\]", re.IGNORECASE)


def is_own_address(addr: str, own_addresses: list[str]) -> bool:
    """addr — сырой заголовок ("Имя <a@b.c>" либо голый адрес), сравнение
    по email-части, регистронезависимо."""
    _, email_addr = parseaddr(addr)
    email_addr = email_addr.strip().lower()
    if not email_addr:
        return False
    return email_addr in {a.strip().lower() for a in own_addresses}


def parse_forwarded_sender(body: str) -> tuple[str | None, str | None]:
    """Ищет маркер пересылки (Gmail/Apple Mail/Outlook) в начале тела
    письма, а под ним — строку вида "From:"/"От:"/"От кого:" с адресом
    первоначального отправителя. (None, None) — маркер или адрес в нём не
    найдены (письмо не похоже на пересылку в известном формате)."""
    marker = _FORWARD_MARKER_RE.search(body[:_SEARCH_WINDOW_CHARS])
    if marker is None:
        return None, None

    window = body[marker.end() : marker.end() + _FROM_LINE_WINDOW_CHARS]
    from_match = _FROM_LINE_RE.search(window)
    if from_match is None:
        return None, None

    from_line = from_match.group(1).strip()
    display_name, email_addr = parseaddr(from_line)
    if not email_addr:
        mailto_match = _MAILTO_RE.search(from_line)
        if mailto_match:
            email_addr = mailto_match.group(1).strip()
            display_name = from_line.split("[mailto:")[0].strip() or display_name

    if not email_addr and not display_name:
        return None, None
    return (display_name or None), (email_addr or None)


def first_other_recipient(
    to_header: str, cc_header: str, own_addresses: list[str], mail_domain: str
) -> tuple[str | None, str | None]:
    """Первый адрес из To:+Cc:, который не свой и не сам notenotes-приёмник
    (иначе для писем, где в копии только notenotes, не осталось бы никого) —
    реальный собеседник, которому пользователь написал/скопировал письмо."""
    own_lower = {a.strip().lower() for a in own_addresses}
    mail_domain_suffix = f"@{mail_domain.strip().lower()}" if mail_domain.strip() else None

    for display_name, addr in getaddresses([to_header or "", cc_header or ""]):
        addr_lower = addr.strip().lower()
        if not addr_lower:
            continue
        if addr_lower in own_lower:
            continue
        if mail_domain_suffix and addr_lower.endswith(mail_domain_suffix):
            continue
        return (display_name or None), addr

    return None, None
