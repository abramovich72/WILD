import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..config import settings
from ..db import get_session
from ..models.media import Clip, Detection, MediaItem, Project
from ..services import clip as clip_service
from ..services import renders, storage
from ..services.species_names import display_name

router = APIRouter(prefix="/api")


class AutoIn(BaseModel):
    media_ids: list[int] | None = None  # None = all media in the project, oldest first
    length: float = Field(30, ge=1, le=600)
    animals_only: bool = False
    image_seconds: float = Field(3.0, gt=0, le=60)


class TimelineItemIn(BaseModel):
    media_id: int
    start: float = Field(0, ge=0)
    end: float | None = None  # images: display seconds (default 3)
    label: str | None = None


class ClipIn(BaseModel):
    name: str = ""
    items: list[TimelineItemIn] = Field(min_length=1)
    captions: bool = False
    opening_title: str = Field("", max_length=200)
    opening_title_seconds: float = Field(3.0, ge=1, le=60)
    closing_title: str = Field("", max_length=200)
    closing_title_seconds: float = Field(3.0, ge=1, le=60)
    transition: Literal["none", "fade"] = "none"


def _project(session: Session, project_id: int) -> Project:
    p = session.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def _clip(session: Session, clip_id: int) -> Clip:
    c = session.get(Clip, clip_id)
    if not c:
        raise HTTPException(404, "Clip not found")
    return c


def _clip_out(c: Clip) -> dict:
    return {
        "id": c.id,
        "project_id": c.project_id,
        "name": c.name,
        "status": c.status,
        "error": c.error,
        "progress": renders.PROGRESS.get(c.id) if c.status == "running" else None,
        "duration": c.duration,
        "size_bytes": c.size_bytes,
        "created_at": c.created_at,
        "spec": json.loads(c.spec),
    }


@router.post("/projects/{project_id}/timeline/auto")
def auto_timeline(project_id: int, body: AutoIn, session: Session = Depends(get_session)):
    _project(session, project_id)
    q = select(MediaItem).where(MediaItem.project_id == project_id).order_by(MediaItem.id)
    items = session.exec(q).all()
    if body.media_ids is not None:
        by_id = {m.id: m for m in items}
        items = [by_id[i] for i in dict.fromkeys(body.media_ids) if i in by_id]
    ids = [m.id for m in items]
    dets = session.exec(select(Detection).where(Detection.media_id.in_(ids))).all() if ids else []
    pieces, skipped = clip_service.plan_timeline(
        [clip_service.PlanMedia(m.id, m.kind, m.duration) for m in items],
        [
            clip_service.PlanDet(
                d.media_id, d.species, display_name(d.species), d.confidence, d.start_time, d.end_time
            )
            for d in dets
        ],
        length=body.length,
        animals_only=body.animals_only,
        image_seconds=body.image_seconds,
        pad=settings.animal_pad_seconds,
    )
    return {
        "items": [
            {"media_id": p.media_id, "start": round(p.start, 2), "end": round(p.end, 2), "label": p.label}
            for p in pieces
        ],
        "total": round(sum(p.duration for p in pieces), 2),
        "skipped": skipped,
    }


@router.post("/projects/{project_id}/clips", status_code=201)
def create_clip(project_id: int, body: ClipIn, session: Session = Depends(get_session)):
    _project(session, project_id)
    ids = {i.media_id for i in body.items}
    media = {
        m.id: m
        for m in session.exec(
            select(MediaItem).where(MediaItem.project_id == project_id, MediaItem.id.in_(ids))
        ).all()
    }
    items = []
    for it in body.items:
        m = media.get(it.media_id)
        if not m:
            raise HTTPException(422, f"Unknown media {it.media_id}")
        if m.kind == "image":
            start, end = 0.0, it.end if it.end is not None else settings.image_seconds
        else:
            start = it.start
            end = it.end if it.end is not None else (m.duration or 0)
            if m.duration:
                end = min(end, m.duration)
        if end - start < clip_service.MIN_RENDER_PIECE:
            raise HTTPException(422, f"Segment of {m.filename} is too short")
        items.append(
            {"media_id": m.id, "start": round(start, 3), "end": round(end, 3), "label": it.label}
        )
    opening_title = body.opening_title.strip()
    closing_title = body.closing_title.strip()
    total = sum(i["end"] - i["start"] for i in items)
    total += (body.opening_title_seconds if opening_title else 0)
    total += (body.closing_title_seconds if closing_title else 0)
    if total > settings.max_clip_seconds:
        raise HTTPException(422, f"Clip is longer than {settings.max_clip_seconds:.0f} seconds")
    try:
        storage.ensure_capacity(1)
    except storage.StorageQuotaExceeded as e:
        raise HTTPException(507, str(e)) from e

    clip = Clip(
        project_id=project_id,
        name=body.name.strip() or "קליפ",
        spec=json.dumps(
            {
                "items": items,
                "captions": body.captions,
                "opening_title": opening_title,
                "opening_title_seconds": body.opening_title_seconds,
                "closing_title": closing_title,
                "closing_title_seconds": body.closing_title_seconds,
                "transition": body.transition,
            },
            ensure_ascii=False,
        ),
    )
    session.add(clip)
    session.commit()
    session.refresh(clip)
    if not body.name.strip():
        clip.name = f"קליפ {clip.id}"
        session.add(clip)
        session.commit()
    renders.enqueue(clip.id)
    return _clip_out(clip)


@router.get("/projects/{project_id}/clips")
def list_clips(project_id: int, session: Session = Depends(get_session)):
    _project(session, project_id)
    q = select(Clip).where(Clip.project_id == project_id).order_by(Clip.id.desc())
    return [_clip_out(c) for c in session.exec(q).all()]


@router.get("/clips/{clip_id}/file")
def clip_file(clip_id: int, download: bool = False, session: Session = Depends(get_session)):
    c = _clip(session, clip_id)
    path = storage.clips_dir(c.project_id) / c.file_name if c.file_name else None
    if c.status != "done" or not path or not path.exists():
        raise HTTPException(404, "Clip not ready")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"{c.name}.mp4",
        content_disposition_type="attachment" if download else "inline",
    )


@router.delete("/clips/{clip_id}", status_code=204)
def delete_clip(clip_id: int, session: Session = Depends(get_session)):
    c = _clip(session, clip_id)
    if c.status in ("queued", "running"):
        raise HTTPException(409, "Clip is still rendering")
    if c.file_name:
        (storage.clips_dir(c.project_id) / c.file_name).unlink(missing_ok=True)
    session.delete(c)
    session.commit()
