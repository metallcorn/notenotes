from __future__ import annotations

import json
import logging

from pywebpush import WebPushException, webpush

from app.core.config import get_settings
from app.models import PushSubscription

logger = logging.getLogger(__name__)


async def send_push(subscription: PushSubscription, title: str, body: str) -> bool:
    """Возвращает False, если подписка протухла (410/404 от push-сервиса —
    браузер её отозвал) — вызывающий код должен удалить строку. Любая
    другая ошибка — просто лог, подписку не трогаем (временный сбой сети)."""
    settings = get_settings()
    if not settings.vapid_private_key:
        return True
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
        )
        return True
    except WebPushException as e:
        if e.response is not None and e.response.status_code in (404, 410):
            return False
        logger.warning("Ошибка Web Push для подписки %s: %s", subscription.id, e)
        return True
    except Exception:
        logger.exception("Неожиданная ошибка Web Push для подписки %s", subscription.id)
        return True
