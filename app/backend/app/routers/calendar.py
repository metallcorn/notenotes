import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from starlette.responses import Response

from app.deps import get_current_user
from app.models import User

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

# Отдельный HTTP-эндпоинт, а не blob: URL на фронтенде — намеренно: мобильные
# браузеры реагируют на Content-Type: text/calendar настоящего HTTP-ответа
# нативным диалогом "добавить в календарь", а blob:-ссылки чаще всего просто
# скачиваются как файл, который потом надо открывать вручную (жалоба
# пользователя). Content-Disposition: inline — та же причина: attachment
# принудительно скачивает вместо того, чтобы дать ОС решить, как открыть.


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_date(value: str, all_day: bool) -> str:
    if all_day:
        return value.replace("-", "")
    dt = datetime.fromisoformat(value)
    return dt.strftime("%Y%m%dT%H%M%S")


@router.get("/event.ics")
async def event_ics(
    title: str = Query(...),
    start: str = Query(...),
    end: str = Query(...),
    all_day: bool = Query(False),
    location: str = Query(""),
    description: str = Query(""),
    user: User = Depends(get_current_user),
) -> Response:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Notenotes//RU",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@notenotes",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART{';VALUE=DATE' if all_day else ''}:{_ics_date(start, all_day)}",
        f"DTEND{';VALUE=DATE' if all_day else ''}:{_ics_date(end, all_day)}",
        f"SUMMARY:{_escape(title)}",
    ]
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    ics = "\r\n".join(lines)
    return Response(
        content=ics,
        media_type="text/calendar",
        headers={"Content-Disposition": "inline; filename=event.ics"},
    )
