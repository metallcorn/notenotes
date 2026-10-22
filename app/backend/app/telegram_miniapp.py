"""Проверка initData Telegram Mini App (https://core.telegram.org/bots/webapps).

Telegram открывает приложение в своём вебвью и передаёт строку initData:
query-string с полями user, auth_date, hash и т.д. Подлинность — HMAC:
    secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    hash       = hex(HMAC_SHA256(key=secret_key, msg=data_check_string))
где data_check_string — все поля кроме hash, отсортированные по ключу,
«key=value» через перевод строки. Подделать без токена бота нельзя, а
auth_date защищает от переиспользования старой строки.
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

# Сутки: Telegram сам обновляет initData при каждом открытии, старая
# строка в честном клиенте не встречается.
MAX_AGE_SECONDS = 24 * 3600


class InitDataError(ValueError):
    pass


def verify_init_data(init_data: str, bot_token: str, *, now: float | None = None) -> dict:
    """Возвращает словарь полей initData (user — уже разобранный JSON).

    Бросает InitDataError, если подпись не сходится, данные устарели или
    нет пользователя. Токен бота — только для подписи, наружу не уходит.
    """
    if not bot_token:
        raise InitDataError("Бот не настроен")
    pairs = parse_qsl(init_data, keep_blank_values=True)
    fields = dict(pairs)
    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise InitDataError("Нет подписи")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("Подпись не сходится")
    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError as exc:
        raise InitDataError("Некорректная дата") from exc
    current = now if now is not None else time.time()
    if auth_date <= 0 or current - auth_date > MAX_AGE_SECONDS:
        raise InitDataError("Данные устарели — открой приложение заново")
    try:
        user = json.loads(fields.get("user", "")) if fields.get("user") else None
    except json.JSONDecodeError as exc:
        raise InitDataError("Некорректный пользователь") from exc
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise InitDataError("Нет пользователя")
    return {**fields, "user": user}


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Собирает подписанную строку initData — для тестов (и только)."""
    from urllib.parse import urlencode

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": signature})
