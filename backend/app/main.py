from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.clips import router as clips_router
from .api.detect import router as detect_router
from .api.drive import router as drive_router
from .api.routes import router
from .config import settings
from .db import init_db
from .services.detect import preload_model


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if settings.preload_model:
        preload_model()
    yield


app = FastAPI(title="Wild Clips", lifespan=lifespan)
app.include_router(router)
app.include_router(detect_router)
app.include_router(drive_router)
app.include_router(clips_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
