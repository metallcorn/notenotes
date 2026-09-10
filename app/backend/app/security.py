import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


# Сессионная кука и OAuth-токен для MCP подписываются ОДНИМ secret_key и
# одним алгоритмом. Значит нужен способ не перепутать их: иначе токен,
# выданный внешнему сервису (claude.ai), работал бы как сессионная кука —
# с полным доступом ко всему API, включая эндпоинты сейфа, которых у MCP
# нет и не должно быть.
#
# ДЕРЖИТ ЭТО ПОЛЕ aud, а не typ ниже. Проверено на живом PyJWT:
#
#   токен С aud,  decode без audience=  -> InvalidAudienceError
#   токен БЕЗ aud, decode с audience=   -> MissingRequiredClaimError
#
# То есть разделение обеспечивается тем, что у OAuth-токена aud есть и
# сверяется, а у сессионной куки его нет вовсе. Убрать aud, понадеявшись
# на typ, нельзя — сломается ровно эта граница.
#
# typ — второй слой, на случай если кто-то заведёт третий вид токена и
# забудет про aud. Он дешёвый, поэтому оставлен, но несущим его считать
# не надо.
#
# Разделять ключи было бы надёжнее всего, но потребовало бы нового
# секрета в vault и цепочки восстановления к нему (CLAUDE.md).
TOKEN_TYPE_SESSION = "session"
TOKEN_TYPE_MCP_ACCESS = "mcp_access"


def hash_token(token: str) -> str:
    """Хэш для СЛУЧАЙНОГО высокоэнтропийного токена — sha256, не bcrypt.

    bcrypt намеренно медленный, и это правильно для пароля: он защищает от
    перебора по словарю. Токен на 256 бит перебирать нечем, зато медленный
    хэш здесь вредит дважды.

    Во-первых, искать токен по хэшу нельзя — соль у каждого своя, — значит
    приходится тянуть ВСЕ активные строки и проверять по очереди. При
    bcrypt это ~100 мс на строку: двадцать токенов превращают каждый
    запрос в две секунды, а заодно дают дешёвый способ положить сервер.
    Во-вторых, при sha256 хэш детерминирован, поэтому находится одним
    индексированным запросом.

    Соль не нужна по той же причине, по какой не нужен медленный хэш:
    радужную таблицу на 256 бит случайности не построить.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def create_session_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "typ": TOKEN_TYPE_SESSION,
        "iat": now,
        "exp": now + timedelta(days=settings.session_ttl_days),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_session_token(token: str) -> uuid.UUID | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        # Отсутствие typ считаем сессией: куки, выданные до появления поля,
        # должны продолжать работать — иначе выкинуло бы всех разом. А вот
        # ЧУЖОЙ тип отвергаем жёстко, ради этого всё и заведено.
        if payload.get("typ", TOKEN_TYPE_SESSION) != TOKEN_TYPE_SESSION:
            return None
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def create_mcp_access_token(user_id: uuid.UUID, client_id: str, audience: str, ttl_seconds: int) -> str:
    """Access-токен OAuth для MCP.

    aud обязателен и проверяется при каждом запросе: спека требует, чтобы
    сервер принимал только токены, выписанные ИМЕННО ДЛЯ НЕГО. Без этого
    токен, полученный клиентом для другого ресурса, открывал бы нашу базу.

    Хранить в БД нечего — подпись самодостаточна, а короткий срок жизни
    заменяет отзыв. Отзывается refresh-токен, он и лежит в таблице.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "typ": TOKEN_TYPE_MCP_ACCESS,
        "aud": audience,
        "client_id": client_id,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_mcp_access_token(token: str, audience: str) -> uuid.UUID | None:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[ALGORITHM],
            # ЭТА строка и есть защита от подмены: PyJWT отвергает и
            # несовпадающий aud, и его отсутствие. Сессионная кука сюда не
            # пролезет именно поэтому, а не из-за typ ниже.
            audience=audience,
        )
        if payload.get("typ") != TOKEN_TYPE_MCP_ACCESS:
            return None
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def mcp_access_token_client(token: str, audience: str) -> uuid.UUID | None:
    """client_id из access-токена — чтобы проверить, не отозвано ли
    подключение (см. routers/mcp.py). Подпись и aud проверяются так же
    строго, как в decode_mcp_access_token: читать что-либо из
    непроверенного токена нельзя."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM], audience=audience)
        if payload.get("typ") != TOKEN_TYPE_MCP_ACCESS:
            return None
        return uuid.UUID(payload["client_id"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
