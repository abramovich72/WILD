import asyncio
import json
import math

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .. import db
from ..db import get_session
from ..models.media import Detection, MediaItem, Project
from ..services import jobs
from ..services.species_names import HEBREW, display_name

router = APIRouter(prefix="/api")

ACTIVE = ("queued", "running")


class DetectIn(BaseModel):
    media_ids: list[int] | None = None
    force: bool = False
    keep_corrections: bool = True


class DetectionPatch(BaseModel):
    species: str | None = Field(default=None, min_length=1, max_length=120)
    start_time: float | None = None
    end_time: float | None = None


class ManualDetectionIn(BaseModel):
    species: str = Field(min_length=1, max_length=120)
    start_time: float | None = None
    end_time: float | None = None


def _detection_out(d: Detection) -> dict:
    return {
        **d.model_dump(),
        "display": display_name(d.species),
    }


def _validate_times(
    media: MediaItem,
    start_time: float | None,
    end_time: float | None,
    *,
    required: bool,
) -> None:
    if media.kind == "image":
        if start_time is not None or end_time is not None:
            raise HTTPException(422, "Image detections cannot have times")
        return
    if start_time is None or end_time is None:
        if required:
            raise HTTPException(422, "Video detections require start and end times")
        return
    if not math.isfinite(start_time) or not math.isfinite(end_time):
        raise HTTPException(422, "Detection times must be finite")
    if start_time < 0 or end_time <= start_time:
        raise HTTPException(422, "Detection end time must be after its start time")
    if media.duration is not None and end_time > media.duration:
        raise HTTPException(422, "Detection time exceeds the media duration")


@router.get("/species")
def list_species():
    return [
        {"species": species, "display": display}
        for species, display in sorted(HEBREW.items(), key=lambda item: item[1])
    ]


@router.post("/projects/{project_id}/detect")
def start_detection(project_id: int, body: DetectIn, session: Session = Depends(get_session)):
    if not session.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    q = select(MediaItem).where(MediaItem.project_id == project_id)
    if body.media_ids is not None:
        q = q.where(MediaItem.id.in_(body.media_ids))
    queued = skipped = 0
    for m in session.exec(q.order_by(MediaItem.id)).all():
        if m.detect_status in ACTIVE or (m.detect_status == "done" and not body.force):
            skipped += 1
            continue
        m.detect_status = "queued"
        m.detect_error = None
        session.add(m)
        session.commit()
        jobs.enqueue(jobs.Job(m.id, body.keep_corrections))
        queued += 1
    return {"queued": queued, "skipped": skipped}


@router.get("/projects/{project_id}/detections")
def list_detections(project_id: int, session: Session = Depends(get_session)):
    if not session.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    q = (
        select(Detection)
        .join(MediaItem, Detection.media_id == MediaItem.id)
        .where(MediaItem.project_id == project_id)
        .order_by(Detection.media_id, Detection.start_time, Detection.id)
    )
    return [_detection_out(d) for d in session.exec(q).all()]


@router.post("/media/{media_id}/detections", status_code=201)
def create_manual_detection(
    media_id: int, body: ManualDetectionIn, session: Session = Depends(get_session)
):
    media = session.get(MediaItem, media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    species = body.species.strip()
    if not species:
        raise HTTPException(422, "Species required")
    _validate_times(media, body.start_time, body.end_time, required=True)
    detection = Detection(
        media_id=media_id,
        species=species,
        confidence=0.0,
        source="manual",
        start_time=body.start_time,
        end_time=body.end_time,
    )
    session.add(detection)
    session.commit()
    session.refresh(detection)
    return _detection_out(detection)


@router.patch("/detections/{detection_id}")
def correct_detection(
    detection_id: int, body: DetectionPatch, session: Session = Depends(get_session)
):
    d = session.get(Detection, detection_id)
    if not d:
        raise HTTPException(404, "Detection not found")
    changes = body.model_fields_set
    if not changes:
        raise HTTPException(422, "No detection fields supplied")
    if "species" in changes:
        species = (body.species or "").strip()
        if not species:
            raise HTTPException(422, "Species required")
        d.species = species
    if "start_time" in changes or "end_time" in changes:
        media = session.get(MediaItem, d.media_id)
        if not media:
            raise HTTPException(404, "Media not found")
        start_time = body.start_time if "start_time" in changes else d.start_time
        end_time = body.end_time if "end_time" in changes else d.end_time
        _validate_times(media, start_time, end_time, required=True)
        d.start_time = start_time
        d.end_time = end_time
    if d.source != "manual":
        d.corrected = True
    session.add(d)
    session.commit()
    session.refresh(d)
    return _detection_out(d)


@router.delete("/detections/{detection_id}", status_code=204)
def delete_detection(detection_id: int, session: Session = Depends(get_session)):
    d = session.get(Detection, detection_id)
    if not d:
        raise HTTPException(404, "Detection not found")
    session.delete(d)
    session.commit()


def _snapshot(project_id: int) -> tuple[list[dict], bool]:
    with Session(db.engine) as s:
        items = s.exec(select(MediaItem).where(MediaItem.project_id == project_id)).all()
        snap = [
            {
                "id": m.id,
                "status": m.detect_status,
                "error": m.detect_error,
                "progress": round(jobs.PROGRESS.get(m.id, 0.0), 3)
                if m.detect_status == "running"
                else None,
            }
            for m in items
        ]
    return snap, any(i["status"] in ACTIVE for i in snap)


@router.get("/projects/{project_id}/detect/events")
async def detection_events(project_id: int):
    """SSE stream of detection status; ends with an `idle` event once nothing is running."""

    async def gen():
        last = None
        while True:
            snap, active = await asyncio.to_thread(_snapshot, project_id)
            payload = json.dumps(snap)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if not active:
                yield "event: idle\ndata: {}\n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )
