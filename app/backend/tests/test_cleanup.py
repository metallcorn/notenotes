

class TestСрокЖурналаФронтенда:
    """Срока у debug_log не было вообще, и к 10.10 он накопил 14 701
    строку (11 МБ). В таком стоге настоящие 103 unhandled rejection никто
    не заметил два месяца."""

    async def test_старое_удаляется(self, db_session, monkeypatch, test_user):
        import contextlib
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select

        from app import cleanup
        from app.models import DebugLog

        now = datetime.now(timezone.utc)
        db_session.add(DebugLog(id=__import__("uuid").uuid4(), user_id=test_user.id, event="старое",
                                data={}, created_at=now - timedelta(days=40)))
        db_session.add(DebugLog(id=__import__("uuid").uuid4(), user_id=test_user.id, event="свежее",
                                data={}, created_at=now - timedelta(days=3)))
        await db_session.commit()

        @contextlib.asynccontextmanager
        async def same_session():
            yield db_session

        monkeypatch.setattr(cleanup, "async_session", same_session)
        removed = await cleanup._purge_debug_log_once()

        left = [r.event for r in (await db_session.execute(select(DebugLog))).scalars().all()]
        assert removed == 1
        assert left == ["свежее"]

    def test_срок_короче_чем_у_аудита(self):
        """Там «кто подключался к моей базе» — вопрос на месяцы вперёд, а
        здесь ошибки браузера, которые разбирают по горячим следам."""
        from app import cleanup

        assert cleanup._DEBUG_LOG_RETENTION < cleanup._AUDIT_RETENTION
