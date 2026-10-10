"""Сроки документов: предупредить заранее, а не констатировать задним числом.

Что уже было. expiry_check.find_expired_claims помечает УЖЕ ПРОСРОЧЕННУЮ
дату, если ассистент назвал её действующей (реальный случай с мельдунком,
09.09). Это разбор постфактум: человек узнаёт, что опоздал.

Чего не было. Сроки лежат в базе задолго до истечения и видны нам
заранее — проверено на боевой базе 02.10, и это не теория:

    05.02.2031  Paszport AB7654321, ważny do        (+1587 дней)
    25.08.2027  Następny przegląd do dnia            (+327)
    14.07.2027  Umowa najmu, przedłużyć do dnia      (+285)
    11.03.2027  Техосмотр Citroën, срок истекает     (+160)
    10.12.2026  Następny przegląd do dnia             (+69)

Паспорт, аренда, техосмотр, очередное ТО — всё то, где «узнать за неделю»
значит «не успеть». Данные были, предупреждения не было.

КАК. Раз в сутки проходим по заметкам и извлечённому тексту файлов тем же
разбором, что и expiry_check (одни и те же формулировки на русском,
польском и английском), и на каждый БУДУЩИЙ срок заводим обычное
напоминание за 60 дней. Обычное — значит оно само попадёт и в утреннюю
сводку, и в list_agenda, и в колокольчик, и в Telegram: отдельного канала
доставки заводить не нужно, он уже есть.

ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО:
  * прошедших дат — ими занимается expiry_check в самом ответе;
  * сейфа — он зашифрован, сервер его не читает;
  * автоматического продления или подачи чего-либо: напоминание говорит,
    человек решает.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.db import async_session
from app.expiry_check import _CLAIM_RE, _to_date
from app.models import Item, Notification, Space, Upload

logger = logging.getLogger(__name__)

NOTIFICATION_TYPE = "document_expiry"

# За сколько предупреждать. Шестьдесят дней — чтобы хватило и подать на
# новый документ, и записаться: на карту побыту в Польше очередь в урząд
# занимают сильно заранее. Для техосмотра это с запасом, и пусть: лишний
# месяц раздумий дешевле пропущенного срока.
LEAD = timedelta(days=60)

# Насколько далеко вперёд смотрим. Паспорт до 2031 года — настоящий срок,
# но напоминание на 2031-й сегодня не нужно никому; оно заведётся само,
# когда подойдёт время (воркер ходит каждые сутки).
MAX_HORIZON = timedelta(days=400)

_CHECK_INTERVAL_SECONDS = 6 * 3600


# Разметка и служебный мусор, которые в пояснении только мешают.
#
# Живой пример из боевой базы (напоминание про сервисную книжку):
#   "-----------|&#10;| 10.12.2024 | | Warunki normalne □ | do 73 000 km"
# Это срез markdown-таблицы: горизонтальная линейка, неразэкранированный
# перевод строки и палки столбцов. Человеку непонятно, модели — тоже.
_NOISE_RE = re.compile(r"&#\d+;|&[a-z]{2,6};|[|─—]{2,}|[-]{3,}")


def _snippet(text: str, match_end: int) -> str:
    """Кусок текста вокруг срока — чтобы человек понял, о чём речь.

    Названия заметок бывают бесполезны («CamScanner 29.05.2025 07.31.pdf»),
    а строка «Paszport AB7654321, ważny do 10.08.2027» объясняет всё.
    """
    start = max(0, match_end - 140)
    raw = html.unescape(text[start:match_end])
    cleaned = _NOISE_RE.sub(" ", raw).replace("|", " ")
    return " ".join(cleaned.split())[-90:]


def find_upcoming(text: str, today: date) -> list[tuple[date, str]]:
    """Будущие сроки с пояснением. Дубли по дате схлопнуты."""
    found: dict[date, str] = {}
    for match in _CLAIM_RE.finditer(text or ""):
        parsed = _to_date(match)
        if parsed is None or parsed <= today or parsed > today + MAX_HORIZON:
            continue
        found.setdefault(parsed, _snippet(text, match.end()))
    return sorted(found.items())


async def _scan_once() -> int:
    """Завести недостающие напоминания. Возвращает, сколько добавлено."""
    today = date.today()
    added = 0
    async with async_session() as db:
        # Заметки — вместе с автором и с исключением сейфа.
        notes = (
            await db.execute(
                select(Item.id, Item.author_id, Item.title, Item.content)
                .join(Space, Space.id == Item.space_id)
                .where(Item.deleted_at.is_(None), Space.is_vault.is_(False))
            )
        ).all()
        sources: list[tuple[uuid.UUID, uuid.UUID, str, str]] = [
            (i, a, t or "Без названия", c or "") for i, a, t, c in notes
        ]

        # Файлы — их извлечённый текст. Привязываем к заметке, в которой
        # файл лежит: иначе некуда вести человека из напоминания.
        uploads = (
            await db.execute(
                select(Upload.id, Upload.filename, Upload.transcript)
                .join(Space, Space.id == Upload.space_id)
                .where(Space.is_vault.is_(False), Upload.transcript.isnot(None))
            )
        ).all()
        for upload_id, filename, transcript in uploads:
            host = next(((i, a, t) for i, a, t, c in sources if str(upload_id) in c), None)
            if host is None:
                continue
            sources.append((host[0], host[1], filename or host[2], transcript))

        for item_id, author_id, title, text in sources:
            for expires_on, snippet in find_upcoming(text, today):
                key = f"{item_id}:{expires_on.isoformat()}"
                exists = (
                    await db.execute(
                        select(Notification.id).where(
                            Notification.type == NOTIFICATION_TYPE,
                            Notification.payload["key"].astext == key,
                        )
                    )
                ).first()
                if exists is not None:
                    continue

                # Напоминание в полдень: срок — это дело дня, а не минуты,
                # и будить человека в полночь незачем.
                trigger_at = datetime.combine(expires_on - LEAD, time(12, 0))
                db.add(
                    Notification(
                        user_id=author_id,
                        type=NOTIFICATION_TYPE,
                        title=f"Срок истекает {expires_on:%d.%m.%Y}: {title[:80]}",
                        body=snippet,
                        payload={"key": key, "item_id": str(item_id), "expires_on": expires_on.isoformat()},
                        trigger_at=trigger_at.replace(tzinfo=timezone.utc),
                    )
                )
                added += 1
        if added:
            await db.commit()
    return added


async def run_worker() -> None:
    while True:
        try:
            added = await _scan_once()
            if added:
                logger.info("Сроки документов: заведено напоминаний %d", added)
        except Exception:
            logger.exception("Ошибка при проверке сроков документов")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
