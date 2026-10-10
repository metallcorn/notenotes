import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, select

from app import realtime
from app.core.config import get_settings
from app.db import async_session
from app.models import AuditLog, DebugLog, Item, ItemVersion, Notification, OAuthClient, OAuthCode, OAuthRefreshToken, Upload

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


# Реальный запрос: корзина не чистилась сама вообще — «удалено навсегда»
# было только руками, из TrashView. 30 дней — тот же порядок, что у
# большинства подобных приложений (не ТЗ-требование, разумный дефолт).
_TRASH_RETENTION = timedelta(days=30)


async def _purge_trash_once() -> int:
    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - _TRASH_RETENTION
        candidates = (
            await db.execute(select(Item).where(Item.deleted_at.is_not(None), Item.deleted_at < cutoff))
        ).scalars().all()
        if not candidates:
            return 0

        space_ids = set()
        for item in candidates:
            space_ids.add(item.space_id)
            # Тот же порядок, что у ручного /permanent (routers/items.py) —
            # Notification.payload не имеет FK на items.id, каскад БД её не заденет.
            await db.execute(delete(Notification).where(Notification.payload["item_id"].astext == str(item.id)))
            await db.delete(item)
        await db.commit()
        for space_id in space_ids:
            await realtime.notify_space(space_id, "items")
        return len(candidates)


# Срок хранения аудита. Это и есть его «ротация» — но с понятным сроком,
# а не «сколько влезло в 30 МБ docker-логов». Полгода: вопрос «кто
# подключался к моей базе» задают через месяцы, а держать вечно незачем,
# на 4 ГБ VPS место не бесконечное.
_AUDIT_RETENTION = timedelta(days=180)


async def _purge_audit_once() -> int:
    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - _AUDIT_RETENTION
        result = await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        await db.commit()
        return result.rowcount or 0


# Срок хранения журнала фронтенда. Короче аудита, и намеренно: там «кто
# подключался к моей базе» — вопрос на месяцы вперёд, а здесь ошибки
# браузера, которые разбирают по горячим следам или не разбирают вовсе.
#
# Почему это понадобилось: срока у debug_log не было вообще, и к 10.10 он
# накопил 14 701 строку (11 МБ) — из них 14 376 не ошибки, а отработавшие
# диагностические пробы (убраны тем же днём). На 4 ГБ VPS это не вопрос
# опрятности, а место; плюс в таком стоге настоящие 103 unhandled
# rejection никто не заметил два месяца.
_DEBUG_LOG_RETENTION = timedelta(days=30)


async def _purge_debug_log_once() -> int:
    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - _DEBUG_LOG_RETENTION
        result = await db.execute(delete(DebugLog).where(DebugLog.created_at < cutoff))
        await db.commit()
        return result.rowcount or 0


async def _purge_oauth_once() -> int:
    """Отработавшие коды, мёртвые refresh и клиенты, которыми не пользуются.

    Регистрация OAuth-клиентов ОТКРЫТАЯ — иначе claude.ai не подключится,
    он узнаёт про нас в момент подключения. Значит строки в этих таблицах
    заводит кто угодно, и без уборки они копятся вечно: на 4 ГБ VPS это
    не абстрактная опрятность, а вопрос места.

    Коды живут пять минут, refresh — два месяца. Держим их ещё сутки
    после смерти: по used_at видно ПОВТОРНУЮ попытку, а она означает
    кражу, и такой след стоит того, чтобы он полежал в логах и в базе.

    Клиента удаляем, только если он старше суток И у него не осталось ни
    одного живого refresh: свежий трогать нельзя — человек мог начать
    подключение и не дойти до конца, а вернуться через полчаса.
    """
    grace = datetime.now(timezone.utc) - timedelta(days=1)
    async with async_session() as db:
        codes = await db.execute(delete(OAuthCode).where(OAuthCode.expires_at < grace))
        tokens = await db.execute(
            delete(OAuthRefreshToken).where(
                OAuthRefreshToken.expires_at < grace,
            )
        )
        # Клиенты без единого refresh и старше суток.
        live_clients = select(OAuthRefreshToken.client_id).where(OAuthRefreshToken.revoked_at.is_(None))
        clients = await db.execute(
            delete(OAuthClient).where(
                OAuthClient.created_at < grace,
                OAuthClient.id.not_in(live_clients),
            )
        )
        await db.commit()
        return (codes.rowcount or 0) + (tokens.rowcount or 0) + (clients.rowcount or 0)


# Окно, в котором обнуление считаем СВЕЖИМ. Старые (до починок 2026-09-08)
# уже найдены и восстановлены руками 2026-09-11; предупреждать о них
# каждые шесть часов — шум, за которым не заметишь новое.
_WIPE_LOOKBACK = timedelta(days=7)


async def _find_recently_wiped() -> list[tuple[str, str, datetime]]:
    """Заметки, у которых content пуст, а в истории есть непустая версия.

    Урок инцидента 2026-09-11: потерю данных чинили ТРИЖДЫ (Yjs 19.08,
    Yjs 02.09, гонка автосохранения 08.09), и каждый раз — сам баг. Но
    его жертв никто не собирал: четыре заметки простояли пустыми от двух
    до пяти недель, пока владелец не наткнулся сам. История версий их
    хранила всё это время.

    Это не восстановление, а сигнал: восстанавливать должен человек,
    потому что пустая заметка может быть и намеренно пустой. Но узнать
    о ней он должен от нас, а не случайно.
    """
    since = datetime.now(timezone.utc) - _WIPE_LOOKBACK
    async with async_session() as db:
        rows = (
            await db.execute(
                select(Item.id, Item.title, Item.updated_at)
                .where(
                    Item.deleted_at.is_(None),
                    Item.material_type == "note",
                    Item.updated_at >= since,
                    func.length(func.trim(func.coalesce(Item.content, ""))) < 5,
                    select(ItemVersion.id)
                    .where(ItemVersion.item_id == Item.id, func.length(ItemVersion.content) > 20)
                    .exists(),
                )
            )
        ).all()
    return [(str(r[0]), r[1] or "без названия", r[2]) for r in rows]


async def run_periodic_sweep() -> None:
    while True:
        try:
            removed = await _sweep_once()
            if removed:
                logger.info("Очистка неиспользуемых файлов: удалено %d", removed)
        except Exception:
            logger.exception("Ошибка при очистке неиспользуемых файлов")
        try:
            purged = await _purge_trash_once()
            if purged:
                logger.info("Автоочистка корзины (>30 дней): удалено %d", purged)
        except Exception:
            logger.exception("Ошибка при автоочистке корзины")
        try:
            purged = await _purge_oauth_once()
            if purged:
                logger.info("Очистка OAuth: удалено %d записей", purged)
        except Exception:
            logger.exception("Ошибка при очистке OAuth")
        try:
            wiped = await _find_recently_wiped()
            for item_id, title, when in wiped:
                # WARNING, не INFO: это не рутина, а именно то, что надо
                # заметить в общем потоке логов.
                logger.warning(
                    "Заметка пуста, но в истории есть содержимое — возможная потеря данных: "
                    "«%s» (%s), последняя правка %s", title, item_id, when
                )
        except Exception:
            logger.exception("Ошибка при поиске обнулённых заметок")
        try:
            purged = await _purge_audit_once()
            if purged:
                logger.info("Очистка аудита (>180 дней): удалено %d записей", purged)
        except Exception:
            logger.exception("Ошибка при очистке аудита")
        try:
            purged = await _purge_debug_log_once()
            if purged:
                logger.info("Очистка журнала фронтенда (>30 дней): удалено %d записей", purged)
        except Exception:
            logger.exception("Ошибка при очистке журнала фронтенда")
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
