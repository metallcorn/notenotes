from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app import realtime
from app.llm.base import ToolDefinition
from app.models import ItemVersion
from app.tools.notes import _get_item_cross_space
from app.tools.registry import ToolContext, ToolError
from app.url_check import check_url

# Виджет «Проверить по ссылке» (extensions/UrlCheckAttachment.ts) — вместо
# того чтобы просить пользователя вручную указывать JSON-пути и подписи,
# ассистент сам делает тестовый запрос (test_url_request), смотрит на
# реальный ответ и предлагает поля — пользователь только подтверждает
# (см. промпт в dialogs.py). insert_url_check_block вызывается ТОЛЬКО
# после этого подтверждения, тот же принцип, что у create_reminder —
# не молча.

_MAX_BODY_CHARS_FOR_MODEL = 4000


TEST_URL_REQUEST = ToolDefinition(
    name="test_url_request",
    description=(
        "Делает GET-запрос по ссылке и возвращает код ответа и тело (обычно JSON) — "
        "чтобы УВИДЕТЬ реальные данные, прежде чем предлагать пользователю, какие поля "
        "показать в виджете «Проверить по ссылке». Ничего не создаёт и не сохраняет — "
        "чисто чтение. Используй, когда пользователь просит завести отслеживание "
        "статуса/данных по ссылке (в т.ч. если прислал команду curl — возьми из неё "
        "ТОЛЬКО URL, без заголовков авторизации/cookie/токенов, они нигде не "
        "сохраняются). Только публичные, не требующие авторизации ссылки — если URL "
        "явно требует токен/сессию, которых у тебя нет, результат придёт с ошибкой "
        "или не тем, что нужно, — сообщи об этом честно, не выдумывай данные."
    ),
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "URL для запроса (только сам URL, без заголовков)"}},
        "required": ["url"],
    },
)


async def test_url_request(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url", "")).strip()
    if not url:
        raise ToolError("Ссылка не может быть пустой")
    result = await check_url(url)
    if "error" in result:
        return result
    body = result["body"]
    truncated = len(body) > _MAX_BODY_CHARS_FOR_MODEL
    return {"status_code": result["status_code"], "body": body[:_MAX_BODY_CHARS_FOR_MODEL], "truncated": truncated}


INSERT_URL_CHECK_BLOCK = ToolDefinition(
    name="insert_url_check_block",
    description=(
        "Добавляет в конец заметки виджет «Проверить по ссылке» — карточку с полями "
        "(подтверждёнными пользователем после test_url_request) и кнопкой «Обновить». "
        "Делает свежий запрос сама, виджет появится сразу с реальными данными. "
        "ВЫЗЫВАЙ ТОЛЬКО после того, как показал пользователю предложенные поля в чате "
        "и получил явное согласие — как с create_reminder, не молча."
    ),
    parameters={
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "url": {"type": "string"},
            "fields": {
                "type": "array",
                "description": "Поля для показа в карточке, в порядке отображения",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Путь в JSON-ответе, например passportStatus.name"},
                        "label": {"type": "string", "description": "Подпись поля на русском, например 'Статус'"},
                    },
                    "required": ["path", "label"],
                },
            },
        },
        "required": ["item_id", "url", "fields"],
    },
)


def _esc(s: str) -> str:
    # Тот же порядок экранирования, что у serialize_document_attachment
    # (pdf_processing.py) — весь тег должен остаться на одной строке.
    return s.replace("&", "&amp;").replace("\n", "&#10;").replace('"', "&quot;")


def serialize_url_check(url: str, fields: list[dict], body: str | None, status_code: int | None) -> str:
    parts = [f'data-url="{_esc(url)}"', f'data-fields="{_esc(json.dumps(fields, ensure_ascii=False))}"']
    if body is not None:
        parts.append(f'data-last-result="{_esc(body)}"')
        parts.append(f'data-last-fetched-at="{_esc(datetime.now(timezone.utc).isoformat())}"')
    if status_code is not None:
        parts.append(f'data-last-status="{status_code}"')
    return f"<div data-url-check {' '.join(parts)}></div>"


async def insert_url_check_block(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item = await _get_item_cross_space(ctx, args.get("item_id"))
    url = str(args.get("url", "")).strip()
    if not url:
        raise ToolError("Ссылка не может быть пустой")
    fields_raw = args.get("fields")
    if not isinstance(fields_raw, list) or not fields_raw:
        raise ToolError("Нужно хотя бы одно поле")
    fields = []
    for f in fields_raw:
        if not isinstance(f, dict) or not f.get("path") or not f.get("label"):
            continue
        fields.append({"path": str(f["path"]), "label": str(f["label"])})
    if not fields:
        raise ToolError("Не удалось разобрать поля")

    result = await check_url(url)
    body = result.get("body")
    status_code = result.get("status_code")

    block = serialize_url_check(url, fields, body, status_code)

    ctx.db.add(ItemVersion(item_id=item.id, title=item.title, content=item.content, author_id=ctx.user_id))
    item.content = f"{item.content.rstrip()}\n\n{block}" if item.content.strip() else block

    await ctx.db.commit()
    await ctx.db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    return {
        "id": str(item.id),
        "title": item.title,
        "fetch_error": result.get("error"),
    }
