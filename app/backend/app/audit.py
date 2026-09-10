"""Запись действий в аудит.

События и так печатаются в лог, но этого мало: docker крутит логи по
10 МБ × 3, то есть след живёт дни, а вопрос «кто и когда подключался к
моей базе» задают через месяцы. Плюс в логе всё вперемешку с
access-строками и ищется только grep'ом.

ТРИ ПРАВИЛА, каждое куплено отдельной опасностью.

1. Аудит НИКОГДА не роняет запрос. Упавшая запись следа — не повод не
   отдать человеку его заметку: любая ошибка глотается с логом.

2. В аудит не попадает содержимое. Ни текста заметок, ни аргументов
   инструментов, ни самих токенов — только имя события и идентификаторы.
   Иначе аудит станет вторым местом, где лежат личные данные, и защищать
   придётся уже его.

3. Неудачные попытки пишутся с ПОТОЛКОМ. Иначе перебор токенов
   превращается в запись строки на каждую попытку — то есть в способ
   раздуть базу чужими руками, ровно противоположный смыслу защиты.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from app.rate_limit import rate_limited

logger = logging.getLogger(__name__)

# Имена событий. Строками не разбрасываемся: опечатка в имени означает
# запись, которую потом никто не найдёт фильтром.
MCP_TOOL = "mcp.tool"
MCP_AUTH_FAILED = "mcp.auth_failed"
MCP_TOKEN_CREATED = "mcp.token.created"
MCP_TOKEN_REVOKED = "mcp.token.revoked"
OAUTH_CLIENT_REGISTERED = "oauth.client.registered"
OAUTH_GRANTED = "oauth.granted"
OAUTH_DENIED = "oauth.denied"
OAUTH_CONNECTION_REVOKED = "oauth.connection.revoked"
OAUTH_CODE_REPLAY = "oauth.code.replay"
OAUTH_REFRESH_REPLAY = "oauth.refresh.replay"

# Сколько неудачных попыток с одного источника записываем за час. Перебор
# всё равно упирается в ограничение частоты (app/rate_limit.py); аудиту
# достаточно зафиксировать, что попытки были, и откуда.
FAILED_ATTEMPTS_PER_HOUR = 10


async def record(
    db: AsyncSession,
    *,
    event: str,
    user_id=None,
    subject: str = "",
    source: str = "",
    details: dict | None = None,
    commit: bool = False,
) -> None:
    """Записать событие. Никогда не бросает наружу.

    Пишем В ТУ ЖЕ сессию, что и само действие. Первая версия брала свою —
    и след разъезжался с тем, что он описывает: действие могло откатиться,
    а запись о нём остаться (и наоборот). Заодно это ломало тесты, которые
    работают внутри одной откатываемой транзакции.

    commit=True — для случаев, когда следом полетит исключение и обычного
    коммита не будет. Ровно один такой: неудачная попытка входа. Её надо
    сохранить ИМЕННО потому, что запрос закончится 401.
    """
    if event == MCP_AUTH_FAILED and rate_limited(
        f"audit-fail:{source}", max_requests=FAILED_ATTEMPTS_PER_HOUR, window_seconds=3600
    ):
        return

    try:
        db.add(AuditLog(
            user_id=user_id,
            event=event,
            subject=str(subject)[:255],
            source=str(source)[:64],
            details=details or {},
        ))
        if commit:
            await db.commit()
    except Exception:
        # Ровно то, ради чего эта обёртка и существует: упавшая запись
        # следа не должна отнимать у человека ответ.
        logger.warning("Не удалось записать событие аудита %s", event, exc_info=True)
