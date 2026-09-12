import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse
from starlette.requests import Request

from app.core.config import get_settings
from app.autotag import run_worker as run_autotag_worker
from app.embeddings import run_backfill as run_embedding_backfill, run_worker as run_embedding_worker
from app.cleanup import run_periodic_sweep
from app.note_recording import resume_pending as resume_note_recording, run_worker as run_note_recording_worker
from app.notification_dispatch import run_dispatch_worker as run_notification_dispatch_worker
from app.pdf_processing import resume_pending as resume_pdf_ocr, run_worker as run_pdf_worker
from app.telegram_bot import register_webhook as register_telegram_webhook, run_worker as run_telegram_worker
from app.tickets import run_worker as run_ticket_worker
from app.transcription import resume_pending as resume_transcription, run_worker as run_transcription_worker
from app.vision import resume_pending as resume_vision, resume_stuck_replacements, run_worker as run_vision_worker
from app.routers import (
    ai_text,
    auth,
    calendar,
    collab_ws,
    debug_log,
    dialogs,
    feedback,
    folders,
    items,
    link_preview,
    delivery_widgets,
    lists,
    mail,
    mail_webhook,
    mcp,
    memories,
    oauth,
    notifications,
    public,
    push,
    search,
    share_preview,
    skills,
    spaces,
    tables,
    tags,
    telegram,
    uploads,
    url_checks,
    voice,
)

# Логирование не настраивалось вовсе, и это молча стоило нам наблюдаемости.
# В логах видно «INFO: GET /api/...» — но это СОБСТВЕННЫЙ логгер uvicorn,
# который он поднимает сам. Корневой оставался на WARNING, поэтому каждый
# logger.info из наших модулей был мёртвым кодом.
#
# Как это вскрылось: учёт токенов и попаданий в кэш промпта (см.
# _run_dialog_turn_locked) писался через logger.info — то есть месяц
# работал вхолостую, и на вопрос «работает ли кэш» ответа не было вовсе.
# Тот же случай уже ловили с сигналом о сломанном кэше (коммит cbd0211) и
# тогда починили точечно, подняв ОДНУ строку до WARNING. Причина осталась.
#
# Уровень именно для «app.*», не корневой: корневой поднял бы заодно
# httpx, который на INFO печатает каждый исходящий запрос — в агентном
# цикле это шум, за которым не видно своего.
_app_logger = logging.getLogger("app")
_app_logger.setLevel(get_settings().log_level.upper())
# ВТОРАЯ половина настройки, без которой первая не работала. Уровень
# выставили 10.09, а handler'а у корневого логгера нет — uvicorn заводит
# свои и только для себя. Записи INFO от app.* поднимались к корню и
# падали в logging.lastResort, а тот печатает ТОЛЬКО WARNING и выше.
# Поэтому WARNING'и были видны, а весь INFO (учёт токенов, вызовы MCP)
# по-прежнему уходил в никуда. Поймано 12.09 по пустому логу при живых
# вызовах get_file. Тест проверял уровень — ровно та ловушка, которую он
# сам и описывал.
if not _app_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    _app_logger.addHandler(_handler)

logger = logging.getLogger(__name__)


# Реальный найденный случай: очередь OCR PDF молча остановилась посреди
# пачки загрузок — 4 файла обработались, 14 следующих зависли в "pending" на
# 19+ часов, без единой строки в логах (asyncio.create_task ничего не
# перезапускает и никому не сообщает, если корутина воркера когда-либо
# завершится — она просто исчезает). Помогал только рестарт бэкенда
# (resume_pending() на старте) — то, чего явно не должно требоваться
# вручную. _supervised оборачивает каждый фоновый воркер: если он всё же
# завершится НЕ через штатную отмену при остановке приложения — лог и
# перезапуск через паузу, а не тихая смерть до следующего деплоя.
async def _supervised(name: str, worker) -> None:
    """Для БЕСКОНЕЧНЫХ воркеров: возврат из worker() считается сбоем и
    приводит к перезапуску. Одноразовую задачу сюда передавать нельзя —
    она будет перезапускаться в плотном цикле без паузы (поймано живьём:
    догоняющая индексация завершалась штатно, супервизор звал её снова, и
    Postgres держал 93% CPU на повторном тяжёлом запросе). Для таких —
    _once ниже."""
    while True:
        try:
            await worker()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Фоновый воркер %s неожиданно завершился — перезапускаю через 5с", name)
            await asyncio.sleep(5)


async def _once(name: str, task) -> None:
    """Одноразовая фоновая задача: отработала — и всё. Ошибку пишем, но не
    повторяем: если проход упал, повтор в цикле упрётся в ту же причину."""
    try:
        await task()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Фоновая задача %s завершилась с ошибкой", name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    sweep_task = asyncio.create_task(_supervised("cleanup_sweep", run_periodic_sweep))
    transcription_task = asyncio.create_task(_supervised("transcription", run_transcription_worker))
    vision_task = asyncio.create_task(_supervised("vision", run_vision_worker))
    autotag_task = asyncio.create_task(_supervised("autotag", run_autotag_worker))
    embedding_task = asyncio.create_task(_supervised("embeddings", run_embedding_worker))
    telegram_task = asyncio.create_task(_supervised("telegram", run_telegram_worker))
    pdf_task = asyncio.create_task(_supervised("pdf_ocr", run_pdf_worker))
    ticket_task = asyncio.create_task(_supervised("tickets", run_ticket_worker))
    notification_dispatch_task = asyncio.create_task(_supervised("notification_dispatch", run_notification_dispatch_worker))
    note_recording_task = asyncio.create_task(_supervised("note_recording", run_note_recording_worker))
    await resume_transcription()
    await resume_vision()
    await resume_stuck_replacements()
    await resume_pdf_ocr()
    await resume_note_recording()
    # Догнать всё, что не проиндексировано: очередь векторов живёт в
    # памяти процесса и теряется при перезапуске, а на момент внедрения
    # в базе уже лежат сотни записей. Фоном, а не в await — иначе
    # приложение не поднималось бы, пока не отработают сотни запросов к
    # API эмбеддингов, и перезапуск превращался бы в долгий простой.
    backfill_task = asyncio.create_task(_once("embedding_backfill", run_embedding_backfill))
    await register_telegram_webhook()
    try:
        yield
    finally:
        sweep_task.cancel()
        transcription_task.cancel()
        vision_task.cancel()
        autotag_task.cancel()
        embedding_task.cancel()
        backfill_task.cancel()
        telegram_task.cancel()
        pdf_task.cancel()
        ticket_task.cancel()
        notification_dispatch_task.cancel()
        note_recording_task.cancel()


# docs_url/redoc_url/openapi_url отключены — реальный найденный баг
# security-аудита: FastAPI по умолчанию отдаёт /docs, /redoc и
# /openapi.json КОМУ УГОДНО без авторизации — это полная карта API
# (все эндпоинты, параметры, модели) наружу. Отдельного dev-окружения
# нет (CLAUDE.md, осознанно) — гасить не для кого, включать обратно
# временно вручную, если понадобится.
app = FastAPI(title="Notenotes", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(ai_text.router)
app.include_router(auth.router)
app.include_router(calendar.router)
app.include_router(spaces.router)
app.include_router(folders.router)
app.include_router(tags.router)
app.include_router(items.router)
app.include_router(collab_ws.router)
app.include_router(uploads.router)
app.include_router(public.router)
# Без /api-префикса, ровно на /s/{token} — тот же путь, что реальная
# ссылка шаринга (ShareNoteModal.tsx). Должен быть подключён ДО catch-all
# SPA-роута ниже (app.get("/{full_path:path}")) — иначе тот перехватит
# запрос первым и отдаст голый index.html без og:*/title заметки.
app.include_router(share_preview.router)
app.include_router(search.router)
app.include_router(feedback.router)
app.include_router(debug_log.router)
app.include_router(notifications.router)
app.include_router(push.router)
app.include_router(dialogs.router)
# ДО catch-all SPA-роута ниже — иначе POST /api/mcp уедет в index.html.
app.include_router(mcp.router)
# Тоже ДО catch-all: /.well-known/* обязан лежать в корне (так велит RFC),
# и SPA-роут перехватил бы его первым.
app.include_router(oauth.router)
app.include_router(voice.router)
app.include_router(lists.router)
app.include_router(tables.router)
app.include_router(memories.router)
app.include_router(skills.router)
app.include_router(telegram.router)
app.include_router(mail.router)
app.include_router(mail_webhook.router)
app.include_router(link_preview.router)
app.include_router(url_checks.router)
app.include_router(delivery_widgets.router)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/version")
def version() -> dict:
    # Имя JS-бандла уже содержит content-хэш от Vite — меняется ровно тогда,
    # когда меняется код фронтенда. Не нужно отдельно прокидывать git SHA
    # или дату сборки через Dockerfile: это и так честный, детерминированный
    # идентификатор текущей раздаваемой версии. Фронт сверяет его с тем,
    # что было при загрузке страницы (см. useVersionCheck), и предлагает
    # обновиться, если разошлось.
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.is_dir():
        for f in assets_dir.iterdir():
            if f.name.startswith("index-") and f.name.endswith(".js"):
                return {"version": f.name}
    return {"version": "unknown"}


if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(request: Request, full_path: str):
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        # index.html обязан ревалидироваться на каждый заход: Vite даёт
        # хэшированные имена под /assets (их можно кэшировать вечно), но
        # сам index.html их перечисляет — закэшированный браузером index.html
        # молча держит пользователя на предыдущем деплое без какой-либо
        # ошибки, просто "старое поведение продолжает быть", что неотличимо
        # от нового незакрытого бага.
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})
