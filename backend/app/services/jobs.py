"""Single background worker that runs detection jobs one at a time (CPU-friendly)."""

import logging
import queue
import threading
from dataclasses import dataclass

from sqlmodel import Session, select

from .. import db
from ..models.media import Detection, MediaItem
from . import detect, storage

log = logging.getLogger("wild.jobs")

PROGRESS: dict[int, float] = {}


@dataclass
class Job:
    media_id: int
    keep_corrections: bool = True


_queue: queue.Queue[Job] = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def enqueue(job: Job) -> None:
    global _worker
    _queue.put(job)
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, name="detect-worker", daemon=True)
            _worker.start()


def _loop() -> None:
    while True:
        job = _queue.get()
        try:
            run_job(job)
        except Exception:  # keep the worker alive whatever happens
            log.exception("detection job crashed")
        finally:
            PROGRESS.pop(job.media_id, None)


def _set_status(media_id: int, status: str, error: str | None = None) -> MediaItem | None:
    with Session(db.engine) as s:
        m = s.get(MediaItem, media_id)
        if not m:
            return None
        m.detect_status = status
        m.detect_error = error
        s.add(m)
        s.commit()
        s.refresh(m)
        s.expunge(m)
        return m


def run_job(job: Job) -> None:
    item = _set_status(job.media_id, "running")
    if not item:
        return  # deleted while queued
    PROGRESS[job.media_id] = 0.0
    try:
        path = storage.media_dir(item.project_id) / item.stored_name
        if item.kind == "image":
            events = detect.analyze_image(path)
        else:
            events = detect.analyze_video(
                path, item.duration, lambda f: PROGRESS.__setitem__(job.media_id, f)
            )
    except Exception as e:
        log.exception("detection failed for media %s", job.media_id)
        _set_status(job.media_id, "failed", str(e)[:300] or e.__class__.__name__)
        return
    _save_results(job, events)


def _save_results(job: Job, events: list[detect.Event]) -> None:
    with Session(db.engine) as s:
        m = s.get(MediaItem, job.media_id)
        if not m:
            return  # deleted while running
        existing = s.exec(select(Detection).where(Detection.media_id == job.media_id)).all()
        kept: list[detect.Event] = []
        for d in existing:
            if d.source == "manual" or (job.keep_corrections and d.corrected):
                box = (d.box_x, d.box_y, d.box_w, d.box_h)
                kept.append(
                    detect.Event(
                        d.species, d.confidence, d.start_time, d.end_time,
                        box if None not in box else None,  # type: ignore[arg-type]
                    )
                )
            else:
                s.delete(d)
        for e in events:
            if any(
                detect.events_overlap(e, k)
                or (
                    e.start is None
                    and k.start is None
                    and e.species.casefold() == k.species.casefold()
                )
                for k in kept
            ):
                continue
            bx, by, bw, bh = e.box or (None, None, None, None)
            s.add(
                Detection(
                    media_id=job.media_id, species=e.species, confidence=e.conf,
                    start_time=e.start, end_time=e.end,
                    box_x=bx, box_y=by, box_w=bw, box_h=bh,
                )
            )
        m.detect_status = "done"
        m.detect_error = None
        s.add(m)
        s.commit()
