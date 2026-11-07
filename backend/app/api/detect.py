import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import db
from ..db import get_session
from ..models.media import Detection, MediaItem, Project
from ..services import jobs
from ..services.species_names import display_name

router = APIRouter(prefix="/api")

ACTIVE = ("queued", "running")


class DetectIn(BaseModel):
    media_ids: list[int] | None = None
    force: bool = False
    keep_corrections: bool = True


class DetectionPatch(BaseModel):
    species: str


def _detection_out(d: Detection) -> dict:
    return {
        **d.model_dump(),
        "display": display_name(d.species),
    }


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


@router.patch("/detections/{detection_id}")
def correct_detection(
    detection_id: int, body: DetectionPatch, session: Session = Depends(get_session)
):
    d = session.get(Detection, detection_id)
    if not d:
        raise HTTPException(404, "Detection not found")
    species = body.species.strip()
    if not species:
        raise HTTPException(422, "Species required")
    d.species = species
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
