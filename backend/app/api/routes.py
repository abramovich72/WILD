import json
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from ..config import settings
from ..db import get_session
from ..models.media import Detection, MediaItem, Project
from ..services import ffmpeg, storage

router = APIRouter(prefix="/api")
_preview_lock = threading.Lock()


class ProjectIn(BaseModel):
    name: str


class UploadInit(BaseModel):
    filename: str
    size: int


def _project(session: Session, project_id: int) -> Project:
    p = session.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def _media(session: Session, media_id: int) -> MediaItem:
    m = session.get(MediaItem, media_id)
    if not m:
        raise HTTPException(404, "Media not found")
    return m


@router.get("/projects")
def list_projects(session: Session = Depends(get_session)):
    return session.exec(select(Project).order_by(Project.id)).all()


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, session: Session = Depends(get_session)):
    p = Project(name=body.name.strip() or "פרויקט חדש")
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


@router.patch("/projects/{project_id}")
def rename_project(project_id: int, body: ProjectIn, session: Session = Depends(get_session)):
    p = _project(session, project_id)
    p.name = body.name.strip() or p.name
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


@router.get("/projects/{project_id}/media")
def list_media(project_id: int, session: Session = Depends(get_session)):
    _project(session, project_id)
    q = select(MediaItem).where(MediaItem.project_id == project_id).order_by(MediaItem.id)
    items = session.exec(q).all()
    for m in items:
        if not m.thumb_name:  # retry thumbnails that failed at upload time
            name = f"{Path(m.stored_name).stem}.jpg"
            src = storage.media_dir(project_id) / m.stored_name
            thumb_path = storage.thumbs_dir(project_id) / name
            if src.exists():
                try:
                    storage.ensure_capacity(storage.THUMBNAIL_RESERVE_BYTES)
                except storage.StorageQuotaExceeded as e:
                    raise HTTPException(507, str(e)) from e
            if src.exists() and ffmpeg.make_thumbnail(src, thumb_path, m.kind, m.duration):
                if storage.over_quota():
                    thumb_path.unlink(missing_ok=True)
                    raise HTTPException(507, "Storage quota exceeded while creating thumbnail")
                m.thumb_name = name
                session.add(m)
                session.commit()
    return items


@router.delete("/media/{media_id}", status_code=204)
def delete_media(media_id: int, session: Session = Depends(get_session)):
    m = _media(session, media_id)
    (storage.media_dir(m.project_id) / m.stored_name).unlink(missing_ok=True)
    if m.thumb_name:
        (storage.thumbs_dir(m.project_id) / m.thumb_name).unlink(missing_ok=True)
    (storage.previews_dir(m.project_id) / f"{Path(m.stored_name).stem}.mp4").unlink(missing_ok=True)
    for d in session.exec(select(Detection).where(Detection.media_id == media_id)).all():
        session.delete(d)
    session.delete(m)
    session.commit()


@router.get("/media/{media_id}/file")
def media_file(media_id: int, session: Session = Depends(get_session)):
    m = _media(session, media_id)
    path = storage.media_dir(m.project_id) / m.stored_name
    if not path.exists():
        raise HTTPException(404, "File missing")
    return FileResponse(path, filename=m.filename, content_disposition_type="inline")


@router.get("/media/{media_id}/preview")
def media_preview(media_id: int, session: Session = Depends(get_session)):
    """Original if the browser can play it, otherwise a cached MP4 transcode."""
    m = _media(session, media_id)
    src = storage.media_dir(m.project_id) / m.stored_name
    if not src.exists():
        raise HTTPException(404, "File missing")
    if m.kind != "video" or src.suffix.lower() in ffmpeg.BROWSER_VIDEO_EXT:
        return FileResponse(src, filename=m.filename, content_disposition_type="inline")
    dest = storage.previews_dir(m.project_id) / f"{src.stem}.mp4"
    with _preview_lock:
        if not dest.exists():
            try:
                storage.ensure_capacity(0)
            except storage.StorageQuotaExceeded as e:
                raise HTTPException(507, str(e)) from e
            if not ffmpeg.make_preview(src, dest):
                raise HTTPException(500, "Could not prepare a preview")
            if storage.over_quota():
                dest.unlink(missing_ok=True)
                raise HTTPException(507, "Storage quota exceeded while creating preview")
    return FileResponse(dest, media_type="video/mp4")


@router.get("/media/{media_id}/thumb")
def media_thumb(media_id: int, session: Session = Depends(get_session)):
    m = _media(session, media_id)
    if not m.thumb_name:
        raise HTTPException(404, "No thumbnail")
    path = storage.thumbs_dir(m.project_id) / m.thumb_name
    if not path.exists():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(path, media_type="image/jpeg")


# Resumable chunked uploads: init -> PUT chunks at offset -> complete.
def _upload_paths(upload_id: str) -> tuple[Path, Path]:
    try:
        uid = uuid.UUID(upload_id).hex
    except ValueError:
        raise HTTPException(404, "Upload not found")
    base = storage.uploads_dir()
    return base / f"{uid}.json", base / f"{uid}.part"


def _load_upload(upload_id: str) -> tuple[dict, Path, Path]:
    meta_path, part_path = _upload_paths(upload_id)
    if not meta_path.exists():
        raise HTTPException(404, "Upload not found")
    return json.loads(meta_path.read_text(encoding="utf-8")), meta_path, part_path


@router.post("/projects/{project_id}/uploads", status_code=201)
def init_upload(project_id: int, body: UploadInit, session: Session = Depends(get_session)):
    _project(session, project_id)
    kind = ffmpeg.detect_kind(body.filename)
    if not kind:
        raise HTTPException(415, "Unsupported file type")
    if body.size <= 0 or body.size > settings.max_upload_bytes:
        raise HTTPException(413, "Invalid file size")
    storage.cleanup_expired_uploads()
    upload_id = uuid.uuid4().hex
    meta_path, part_path = _upload_paths(upload_id)
    meta = {"project_id": project_id, "filename": Path(body.filename).name,
            "size": body.size, "kind": kind}
    try:
        storage.reserve_upload(meta_path, part_path, meta)
    except storage.StorageQuotaExceeded as e:
        raise HTTPException(507, str(e)) from e
    return {"upload_id": upload_id, "offset": 0}


@router.get("/uploads/{upload_id}")
def upload_status(upload_id: str):
    _, _, part_path = _load_upload(upload_id)
    return {"offset": part_path.stat().st_size}


@router.put("/uploads/{upload_id}")
async def upload_chunk(upload_id: str, offset: int, request: Request):
    meta, _, part_path = _load_upload(upload_id)
    current = part_path.stat().st_size
    if offset != current:
        raise HTTPException(409, detail={"offset": current})
    written = 0
    with part_path.open("ab") as f:
        async for chunk in request.stream():
            written += len(chunk)
            if current + written > meta["size"]:
                f.truncate(current)
                raise HTTPException(413, "Chunk exceeds declared size")
            f.write(chunk)
    return {"offset": current + written}


@router.post("/uploads/{upload_id}/complete", status_code=201)
def complete_upload(upload_id: str, session: Session = Depends(get_session)):
    meta, meta_path, part_path = _load_upload(upload_id)
    if part_path.stat().st_size != meta["size"]:
        raise HTTPException(409, detail={"offset": part_path.stat().st_size})
    try:
        item = storage.ingest(
            meta["project_id"], meta["filename"], meta["kind"], part_path, meta_path
        )
    except storage.StorageQuotaExceeded as e:
        raise HTTPException(507, str(e)) from e
    finally:
        storage.release_reservation(meta_path)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item
