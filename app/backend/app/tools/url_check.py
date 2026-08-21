from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app import collab, realtime
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
        "чисто чтение, headers сюда тоже никуда не пишутся. Используй, когда "
        "пользователь просит завести отслеживание статуса/данных по ссылке. Если "
        "страница требует авторизацию (login-страница вместо данных) и пользователь "
        "САМ явно прислал заголовок/cookie/токен для этого запроса (например, из "
        "своей команды curl) — можешь передать его в headers ЭТОГО одного вызова. "
        "Никогда не подставляй значения заголовков, которые пользователь не давал "
        "явно в этом разговоре (не бери из других заметок/памяти/другого сайта)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL для запроса"},
            "headers": {
                "type": "object",
                "description": (
                    "Опционально: заголовки для ЭТОГО одного запроса (например, "
                    "Cookie/Authorization) — только если пользователь явно дал их "
                    "значение в этом разговоре. Не сохраняются."
                ),
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["url"],
    },
)


async def test_url_request(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url", "")).strip()
    if not url:
        raise ToolError("Ссылка не может быть пустой")
    headers = args.get("headers") if isinstance(args.get("headers"), dict) else None
    result = await check_url(url, headers)
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
        "и получил явное согласие — как с create_reminder, не молча.\n\n"
        "headers (авторизованные ссылки): виджет ПОСТОЯННЫЙ, кнопка «Обновить» "
        "перезапрашивает URL позже — значит headers, в отличие от test_url_request, "
        "СОХРАНЯЮТСЯ открытым текстом в самой заметке (видно всем с доступом к "
        "спейсу, в исходнике страницы, в бэкапах). Если пользователь просит "
        "авторизованную проверку — прежде чем звать этот тул с headers, ОБЯЗАТЕЛЬНО "
        "явно предупреди об этом в чате именно этими словами по смыслу ('токен "
        "сохранится в тексте заметки открытым текстом — видно всем, у кого есть "
        "доступ к этому спейсу, и попадёт в бэкапы') и получи отдельное явное "
        "согласие НА ЭТО, отдельно от согласия на сами поля. Без этого "
        "предупреждения headers не передавай, даже если пользователь их дал."
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
            "headers": {
                "type": "object",
                "description": (
                    "Опционально, только после явного предупреждения пользователя (см. "
                    "выше) и его согласия именно на хранение — заголовки авторизации, "
                    "сохраняются с виджетом для будущих обновлений."
                ),
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["item_id", "url", "fields"],
    },
)


def _esc(s: str) -> str:
    # Тот же порядок экранирования, что у serialize_document_attachment
    # (pdf_processing.py) — весь тег должен остаться на одной строке.
    return s.replace("&", "&amp;").replace("\n", "&#10;").replace('"', "&quot;")


def serialize_url_check(
    url: str, fields: list[dict], body: str | None, status_code: int | None, headers: dict[str, str] | None = None
) -> str:
    parts = [f'data-url="{_esc(url)}"', f'data-fields="{_esc(json.dumps(fields, ensure_ascii=False))}"']
    if headers:
        parts.append(f'data-headers="{_esc(json.dumps(headers, ensure_ascii=False))}"')
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
    headers_raw = args.get("headers")
    headers = {str(k): str(v) for k, v in headers_raw.items()} if isinstance(headers_raw, dict) else None

    result = await check_url(url, headers)
    body = result.get("body")
    status_code = result.get("status_code")

    block = serialize_url_check(url, fields, body, status_code, headers)

    ctx.db.add(ItemVersion(item_id=item.id, title=item.title, content=item.content, author_id=ctx.user_id))
    item.content = f"{item.content.rstrip()}\n\n{block}" if item.content.strip() else block

    await ctx.db.commit()
    await ctx.db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    # Тот же баг, что уже был найден и закрыт для update_note/append_to_note
    # (tools/notes.py) и routers/items.py::revert_version — пишет content
    # напрямую, в обход Yjs; без этого блок проверки ссылки не долетал бы
    # до заметки с открытой живой коллаборацией.
    await collab.invalidate_room(item.id)
    return {
        "id": str(item.id),
        "title": item.title,
        "fetch_error": result.get("error"),
    }
