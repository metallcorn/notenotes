"""Один и тот же файл не должен лечь в базу дважды.

ЗАМЕР 12.10, из которого всё выросло: из 355 загруженных файлов 71 —
побайтовый дубликат (49 групп, каждый пятый файл). И это не случайный
мусор, а один сюжет:

    ZUS DRA 07-2026.pdf        5 копий   19.08 → 01.10   «Почта», «Личное»
    UPO ZUS DRA 07-2026.pdf    5 копий   19.08 → 01.10   «Почта», «Личное»
    ZUS DRA 08-2026.pdf        4 копии   02.09 → 25.09   «Почта», «Личное»
    EP 07-2026.pdf             3 копии
    faktura-21-08-2026.pdf     3 копии

Бухгалтер присылает месячный пакет повторно, часть владелец пересылает в
Telegram, часть загружает руками — и один и тот же байт-в-байт файл
оказывается в двух-трёх местах. Жалоба владельца: «дедупа не хватает,
когда закидываешь что-то, а оно уже есть».

ПОЧЕМУ ХЭШ, А НЕ ИМЯ И НЕ РАЗМЕР. Имя врёт в обе стороны: «image001.jpg»
приходит от разных писем и это разные картинки, а один и тот же документ
бухгалтер может переслать под «ZUS-S-72a.pades 2.pdf». Размер совпадает
у разных файлов слишком часто, чтобы на него опираться. sha256 отвечает
ровно на тот вопрос, который задаёт человек: «это оно же?»

ДВА ПРАВИЛА, И РАЗНИЦА МЕЖДУ НИМИ ВАЖНА.

  * В ПРЕДЕЛАХ СПЕЙСА дубликат не создаётся вовсе: возвращаем уже
    лежащий файл, и заметка ссылается на него. Это снимает тот самый шум
    — повторные пакеты в «Почте» перестают множиться.

  * МЕЖДУ СПЕЙСАМИ строка создаётся своя, а файл на диске
    переиспользуется жёсткой ссылкой. Иначе пришлось бы отдавать одну
    строку наружу из двух спейсов, то есть ломать проверку доступа,
    которая у нас везде построена на space_id. Жёсткая ссылка экономит
    диск и не создаёт такой связи: удаление одного имени не затрагивает
    другое.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Upload

logger = logging.getLogger(__name__)


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def find_in_space(db: AsyncSession, space_id: uuid.UUID, digest: str) -> Upload | None:
    """Тот же файл, уже лежащий в ЭТОМ спейсе."""
    return (
        await db.execute(
            select(Upload)
            .where(Upload.space_id == space_id, Upload.sha256 == digest)
            .order_by(Upload.created_at)
            .limit(1)
        )
    ).scalars().first()


async def find_anywhere(db: AsyncSession, digest: str) -> Upload | None:
    """Тот же файл в любом спейсе — только чтобы переиспользовать блоб."""
    return (
        await db.execute(
            select(Upload).where(Upload.sha256 == digest).order_by(Upload.created_at).limit(1)
        )
    ).scalars().first()


def link_or_write(source: Path | None, dest: Path, data: bytes) -> bool:
    """Положить файл: жёсткой ссылкой на уже лежащий, иначе записать байты.

    Возвращает True, если удалось сослаться. Падение ссылки (другая
    файловая система, гонка, права) — не ошибка: просто пишем байты, как
    писали раньше. Экономия диска не стоит того, чтобы из-за неё
    потерялся файл.
    """
    if source is not None and source.is_file():
        try:
            os.link(source, dest)
            return True
        except OSError:
            logger.info("Жёсткая ссылка на %s не удалась — пишу копию", source.name, exc_info=True)
    dest.write_bytes(data)
    return False
