import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db import async_session
from app.models import Item, Upload

logger = logging.getLogger(__name__)

# Файл, вставленный в заметку, а потом удалённый из текста — раньше висел
# на диске вечно, никто его не искал (жалоба: "сколько будет храниться").
# Не воркер/очередь — обычный asyncio-цикл внутри процесса backend, тот же
# принцип, что уже применён к realtime.py: один процесс, лишняя
# инфраструктура не нужна, пока не появится несколько воркеров.
#
# Грейс-период 24ч — не удаляем сразу: только что созданный upload ещё не
# успел попасть в content заметки (сначала аплоадится файл, потом
# сохраняется заметка с его url).
_GRACE_PERIOD = timedelta(hours=24)
_SWEEP_INTERVAL_SECONDS = 6 * 3600


async def _sweep_once() -> int:
    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - _GRACE_PERIOD
        candidates = (await db.execute(select(Upload).where(Upload.created_at < cutoff))).scalars().all()
        if not candidates:
            return 0

        # Небольшой масштаб (2-10 пользователей) — простой substring-скан
        # по всем content'ам в памяти дешевле и надёжнее, чем городить
        # отдельный индекс/таблицу связей файл-заметка ради этого.
        contents = (await db.execute(select(Item.content))).scalars().all()
        blob = "\n".join(contents)

        upload_dir = Path(get_settings().upload_dir)
        removed = 0
        for upload in candidates:
            if f"/api/uploads/{upload.id}" in blob:
                continue
            (upload_dir / str(upload.id)).unlink(missing_ok=True)
            await db.delete(upload)
            removed += 1

        if removed:
            await db.commit()
        return removed


async def run_periodic_sweep() -> None:
    while True:
        try:
            removed = await _sweep_once()
            if removed:
                logger.info("Очистка неиспользуемых файлов: удалено %d", removed)
        except Exception:
            logger.exception("Ошибка при очистке неиспользуемых файлов")
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
