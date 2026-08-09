import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse
from starlette.requests import Request

from app.autotag import run_worker as run_autotag_worker
from app.cleanup import run_periodic_sweep
from app.pdf_processing import run_worker as run_pdf_worker
from app.telegram_bot import register_webhook as register_telegram_webhook, run_worker as run_telegram_worker
from app.tickets import run_worker as run_ticket_worker
from app.transcription import resume_pending as resume_transcription, run_worker as run_transcription_worker
from app.vision import resume_pending as resume_vision, run_worker as run_vision_worker
from app.routers import (
    ai_text,
    auth,
    calendar,
    debug_log,
    dialogs,
    feedback,
    folders,
    items,
    link_preview,
    lists,
    memories,
    notifications,
    search,
    skills,
    spaces,
    tags,
    telegram,
    uploads,
    voice,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    sweep_task = asyncio.create_task(run_periodic_sweep())
    transcription_task = asyncio.create_task(run_transcription_worker())
    vision_task = asyncio.create_task(run_vision_worker())
    autotag_task = asyncio.create_task(run_autotag_worker())
    telegram_task = asyncio.create_task(run_telegram_worker())
    pdf_task = asyncio.create_task(run_pdf_worker())
    ticket_task = asyncio.create_task(run_ticket_worker())
    await resume_transcription()
    await resume_vision()
    await register_telegram_webhook()
    try:
        yield
    finally:
        sweep_task.cancel()
        transcription_task.cancel()
        vision_task.cancel()
        autotag_task.cancel()
        telegram_task.cancel()
        pdf_task.cancel()
        ticket_task.cancel()


app = FastAPI(title="Notenotes", lifespan=lifespan)
app.include_router(ai_text.router)
app.include_router(auth.router)
app.include_router(calendar.router)
app.include_router(spaces.router)
app.include_router(folders.router)
app.include_router(tags.router)
app.include_router(items.router)
app.include_router(uploads.router)
app.include_router(search.router)
app.include_router(feedback.router)
app.include_router(debug_log.router)
app.include_router(notifications.router)
app.include_router(dialogs.router)
app.include_router(voice.router)
app.include_router(lists.router)
app.include_router(memories.router)
app.include_router(skills.router)
app.include_router(telegram.router)
app.include_router(link_preview.router)

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
