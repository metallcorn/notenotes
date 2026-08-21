from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app import collab, realtime
from app.llm.base import ToolDefinition
from app.models import ItemVersion, UrlCheckWidget
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
        "headers (авторизованные ссылки): url/поля/заголовки/результат живут отдельно "
        "от текста заметки (в заметке — только непрозрачная ссылка на виджет), сам "
        "токен не виден в содержимом заметки, в исходнике страницы и т.п. Но кнопка "
        "«Обновить» перезапрашивает URL позже ОТ ИМЕНИ этого сохранённого токена — то "
        "есть им сможет пользоваться (не увидеть значение, но применить для этого "
        "запроса) кто угодно с доступом к этому спейсу. Если пользователь просит "
        "авторизованную проверку — упомяни это коротко в чате перед вызовом (не нужен "
        "отдельный долгий диалог, но и не молча)."
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
                    "выше) — заголовки авторизации, сохраняются с виджетом для будущих "
                    "обновлений."
                ),
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["item_id", "url", "fields"],
    },
)


def serialize_url_check(widget_id: object) -> str:
    # Единственное, что живёт в content: непрозрачная ссылка на
    # UrlCheckWidget — url/поля/заголовки/результат последнего запроса
    # больше не проходят через content/Yjs/ItemVersion вообще (см.
    # models.py::UrlCheckWidget про то, что это чинит).
    return f'<div data-url-check data-url-check-id="{widget_id}"></div>'


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

    widget = UrlCheckWidget(
        item_id=item.id,
        url=url,
        fields=fields,
        headers=headers,
        last_result=body,
        last_fetched_at=datetime.now(timezone.utc) if body is not None else None,
        last_status=status_code,
    )
    ctx.db.add(widget)
    await ctx.db.flush()

    block = serialize_url_check(widget.id)

    ctx.db.add(ItemVersion(item_id=item.id, title=item.title, content=item.content, author_id=ctx.user_id))
    item.content = f"{item.content.rstrip()}\n\n{block}" if item.content.strip() else block

    await ctx.db.commit()
    await ctx.db.refresh(item)
    await realtime.notify_space(item.space_id, "items")
    # Тот же баг, что уже был найден и закрыт для update_note/append_to_note
    # (tools/notes.py) и routers/items.py::revert_version — пишет content
    # напрямую, в обход Yjs; без этого блок проверки ссылки не долетал бы
    # до заметки с открытой живой коллаборацией. Только здесь, при создании
    # — «Обновить» (routers/url_checks.py) больше не трогает content вовсе.
    await collab.invalidate_room(item.id)
    return {
        "id": str(item.id),
        "title": item.title,
        "fetch_error": result.get("error"),
    }
