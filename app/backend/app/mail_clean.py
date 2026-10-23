"""Чистка текста входящего письма перед сохранением в заметку.

Запрос владельца 23.10: пересланное самому себе письмо приходило в
заметку со всей служебной обвязкой — «---------- Forwarded message
---------», блоками From/Date/Subject/To (по-польски Od/Temat/Do, по-русски
От/Тема/Кому), трекинговыми ссылками рассылок вида
<https://mandrillapp.com/track/click/…> и тройными пустыми строками.
Нужное — текст и вложения — оставляем, обвязку убираем.

Чистится только то, что сохраняется в заметку: определение папки по
отправителю (mail_forward.py) смотрит на сырой текст, где эти заголовки
как раз и нужны.
"""
import re
from urllib.parse import urlparse

_FORWARD_SEPARATOR_RE = re.compile(
    r"^\s*(?:-{3,}|_{3,}|={3,})?\s*"
    r"(?:Forwarded message|Original Message|Пересылаемое сообщение|Переслано|"
    r"Wiadomość przekazana dalej|Weitergeleitete Nachricht|Message transféré)"
    r"\s*(?:-{3,}|_{3,}|={3,})?\s*$",
    re.IGNORECASE,
)
_HEADER_LINE_RE = re.compile(
    r"^\s*(?:From|Od|Von|De|От кого|От|"
    r"Date|Data|Datum|Sent|Wysłano|Envoyé|Дата|Отправлено|"
    r"Subject|Temat|Betreff|Objet|Тема|"
    r"To|Do|An|À|Кому|Cc|DW|Kopia|Копия|Bcc|UDW|Reply-To|Odpowiedź do)"
    r"\s*:\s",
    re.IGNORECASE,
)
# «Текст <https://…>» — так Mailgun разворачивает ссылки из HTML. Ссылки
# трекеров рассылок бесполезны в заметке (одноразовые, ведут через
# редирект и устаревают), обычные оставляем как есть.
_ANGLE_URL_RE = re.compile(r"\s*<(https?://[^\s<>]+)>")
_TRACKER_HOST_PREFIXES = ("click.", "links.", "link.", "trk.", "track.", "email.", "e.", "go.", "clicks.")
_TRACKER_HOSTS = ("mandrillapp.com", "sendgrid.net", "list-manage.com", "mailchimp.com", "mailtrack.io", "awstrack.me")
_TRACKER_PATH_RE = re.compile(r"/(?:track|click|ls/click|wf/click|CL0/|e3t/)", re.IGNORECASE)
_SUBJECT_PREFIX_RE = re.compile(r"^\s*(?:(?:fwd?|fw|re|aw|wg|odp|przek|пересл|ответ)\s*:\s*)+", re.IGNORECASE)


def _is_tracker(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in _TRACKER_HOSTS):
        return True
    if any(host.startswith(p) for p in _TRACKER_HOST_PREFIXES) and _TRACKER_PATH_RE.search(parsed.path or ""):
        return True
    return bool(_TRACKER_PATH_RE.search(parsed.path or "")) and len(url) > 120


def clean_subject(subject: str) -> str:
    """«Fwd: Fwd: Re: Тема» → «Тема»."""
    cleaned = _SUBJECT_PREFIX_RE.sub("", subject).strip()
    return cleaned or subject.strip()


def clean_forwarded_text(text: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _FORWARD_SEPARATOR_RE.match(line):
            # Сам разделитель и идущий за ним блок заголовков (с пустыми
            # строками между ними — некоторые клиенты их добавляют).
            i += 1
            while i < n and (not lines[i].strip() or _HEADER_LINE_RE.match(lines[i])):
                i += 1
            continue
        if _HEADER_LINE_RE.match(line) and not out and i + 1 < n and _HEADER_LINE_RE.match(lines[i + 1]):
            # Блок заголовков в самом начале, без разделителя (Outlook).
            while i < n and (not lines[i].strip() or _HEADER_LINE_RE.match(lines[i])):
                i += 1
            continue
        out.append(line)
        i += 1

    cleaned = "\n".join(out)
    cleaned = _ANGLE_URL_RE.sub(lambda m: "" if _is_tracker(m.group(1)) else m.group(0), cleaned)
    # Строки, где осталась только пустота после вырезанной ссылки.
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
