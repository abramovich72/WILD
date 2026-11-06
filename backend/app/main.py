import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.clips import router as clips_router
from .api.detect import router as detect_router
from .api.drive import protected_router as drive_protected_router
from .api.drive import router as drive_router
from .api.routes import router
from .config import settings
from .db import init_db
from .services import storage
from .services.detect import preload_model

log = logging.getLogger("wild")


def _cleanup_uploads() -> None:
    removed = storage.cleanup_expired_uploads()
    if removed:
        log.info("Removed %d expired partial uploads", removed)


async def _cleanup_uploads_periodically() -> None:
    while True:
        await asyncio.sleep(60 * 60)
        await asyncio.to_thread(_cleanup_uploads)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _cleanup_uploads()
    init_db()
    if settings.preload_model:
        preload_model()
    cleanup_task = (
        asyncio.create_task(_cleanup_uploads_periodically())
        if settings.upload_ttl_seconds > 0
        else None
    )
    try:
        yield
    finally:
        if cleanup_task:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Wild Clips", lifespan=lifespan)
app.include_router(router)
app.include_router(detect_router)
app.include_router(drive_router)
app.include_router(drive_protected_router)
app.include_router(clips_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
