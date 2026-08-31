import html
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import HTMLResponse

from app.core.config import get_settings
from app.db import get_db
from app.models import Upload
from app.routers.items import _UPLOAD_URL_RE
from app.routers.public import _get_shared_item

# Реальная жалоба: шаришь ссылку на заметку в Telegram — превью пустое.
# Причина не в /api/link-preview (тот уже умеет собирать og:*/favicon для
# ЧУЖИХ сайтов) — дело в НАШЕЙ собственной публичной странице /s/{token}.
# Она отдаётся тем же SPA-каталом (main.py::spa) — голым index.html с
# фиксированными <title>/<meta>, без единого слова про конкретную
# заметку. Telegram (как и любой линк-анфёрлер) не исполняет JS — он
# видит ровно то, что вернул сервер синхронно, а React рендерит title
# уже ПОСЛЕ того, как бот давно ушёл. Этот роутер — отдельный, более
# специфичный путь (/s/{token}), должен быть подключён В main.py ДО
# catch-all-роута /{full_path:path}, иначе тот перехватит запрос первым.
router = APIRouter(tags=["share-preview"])

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_DESCRIPTION_LIMIT = 200


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def _plain_excerpt(content: str, limit: int = _DESCRIPTION_LIMIT) -> str:
    """Грубая, не претендующая на полную корректность очистка Markdown/HTML
    для og:description — превью в мессенджере не обязано быть идеальным
    рендером, только узнаваемым отрывком текста."""
    text = re.sub(r"<[^>]+>", " ", content)  # карточки/HTML-узлы (видео, вложения и т.п.)
    text = re.sub(r"[#*`_>\[\]!\\]", " ", text)
    text = re.sub(r"\(https?://\S+\)", " ", text)  # markdown-ссылки — оставляем только текст
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


async def _first_image_upload_id(content: str, db: AsyncSession) -> str | None:
    for match in _UPLOAD_URL_RE.findall(content):
        try:
            upload_id = uuid.UUID(match)
        except ValueError:
            continue
        upload = await db.get(Upload, upload_id)
        if upload is not None and upload.content_type.startswith("image/"):
            return match
    return None


@router.get("/s/{token}")
async def share_preview(token: str, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.is_file():
        # Локальная разработка без собранного фронтенда — отдаём как есть,
        # ниже всё равно нечего вставлять.
        return HTMLResponse("Notenotes", headers={"Cache-Control": "no-store"})

    base_url = get_settings().public_base_url.rstrip("/")
    page_url = f"{base_url}/s/{token}"

    # _get_shared_item НЕ помечает share_used_at — здесь это критично, не
    # просто "как есть": мессенджеры (Telegram и др.) сами дёргают эту
    # страницу СЕРВЕРНО, чтобы собрать превью, ещё ДО того, как получатель
    # хоть раз откроет ссылку. Если бы этот роутер помечал одноразовую
    # ссылку использованной — она сгорала бы от одного факта вставки в
    # чат, получатель видел бы "страница не найдена", ни разу не открыв её.
    try:
        item = await _get_shared_item(db, token)
    except HTTPException:
        item = None

    image_url: str | None = None
    if item is None:
        title = "Notenotes"
        description = "Заметка недоступна — ссылка устарела или отозвана."
    elif item.share_password_hash is not None:
        # Пароль защищает СОДЕРЖИМОЕ — превью не должно давать даже намёк
        # на то, что внутри (тот же принцип, что у view_public_note:
        # requires_password возвращается без title).
        title = "Защищённая заметка — Notenotes"
        description = "Эта заметка защищена паролем."
    else:
        title = item.title.strip() or "Заметка"
        description = _plain_excerpt(item.content) or "Заметка в Notenotes"
        upload_id = await _first_image_upload_id(item.content, db)
        if upload_id:
            image_url = f"{base_url}/api/public/{token}/uploads/{upload_id}"

    if not image_url:
        image_url = f"{base_url}/apple-touch-icon.png"

    html_doc = index_path.read_text(encoding="utf-8")
    html_doc = re.sub(r"<title>.*?</title>", "", html_doc, count=1, flags=re.DOTALL)
    meta_block = (
        f"<title>{_escape(title)}</title>\n"
        '    <meta property="og:type" content="article" />\n'
        '    <meta property="og:site_name" content="Notenotes" />\n'
        f'    <meta property="og:title" content="{_escape(title)}" />\n'
        f'    <meta property="og:description" content="{_escape(description)}" />\n'
        f'    <meta property="og:image" content="{_escape(image_url)}" />\n'
        f'    <meta property="og:url" content="{_escape(page_url)}" />\n'
        '    <meta name="twitter:card" content="summary_large_image" />\n'
        f'    <meta name="description" content="{_escape(description)}" />\n'
    )
    html_doc = html_doc.replace("</head>", meta_block + "  </head>", 1)
    return HTMLResponse(html_doc, headers={"Cache-Control": "no-store"})
