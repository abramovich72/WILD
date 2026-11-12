"""Single background worker that renders clips one at a time."""

import json
import logging
import queue
import shutil
import threading
import uuid

from sqlmodel import Session

from .. import db
from ..models.media import Clip, MediaItem
from . import clip as clip_service
from . import cpu_jobs, ffmpeg, storage

log = logging.getLogger("wild.render")

PROGRESS: dict[int, float] = {}

_queue: queue.Queue[int] = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def enqueue(clip_id: int) -> None:
    global _worker
    _queue.put(clip_id)
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, name="render-worker", daemon=True)
            _worker.start()


def _loop() -> None:
    while True:
        clip_id = _queue.get()
        try:
            with cpu_jobs.CPU_JOB_LOCK:
                run_job(clip_id)
        except Exception:  # keep the worker alive whatever happens
            log.exception("render job crashed")
        finally:
            PROGRESS.pop(clip_id, None)


def _finish(clip_id: int, **fields) -> None:
    with Session(db.engine) as s:
        c = s.get(Clip, clip_id)
        if not c:
            return
        for k, v in fields.items():
            setattr(c, k, v)
        s.add(c)
        s.commit()


def _segments(clip: Clip) -> tuple[list[clip_service.Segment], dict]:
    spec = json.loads(clip.spec)
    with Session(db.engine) as s:
        segments = []
        for it in spec["items"]:
            m = s.get(MediaItem, it["media_id"])
            path = storage.media_dir(m.project_id) / m.stored_name if m else None
            if not m or not path.exists():
                raise RuntimeError("a media file in the timeline was deleted")
            segments.append(
                clip_service.Segment(path, m.kind, it["start"], it["end"], it.get("label"))
            )
    return segments, spec


def run_job(clip_id: int) -> None:
    with Session(db.engine) as s:
        clip = s.get(Clip, clip_id)
        if not clip:
            return
        s.expunge(clip)
    _finish(clip_id, status="running", error=None)
    PROGRESS[clip_id] = 0.0
    tmp = storage.clips_dir(clip.project_id) / f".tmp-{clip_id}"
    name = f"{uuid.uuid4().hex}.mp4"
    out = storage.clips_dir(clip.project_id) / name
    try:
        segments, spec = _segments(clip)
        clip_service.render(
            segments, out, tmp,
            captions=spec.get("captions", False),
            transition=spec.get("transition", "none"),
            opening_title=spec.get("opening_title", ""),
            opening_title_seconds=spec.get("opening_title_seconds", 3.0),
            closing_title=spec.get("closing_title", ""),
            closing_title_seconds=spec.get("closing_title_seconds", 3.0),
            music=spec.get("music"),
            on_progress=lambda f: PROGRESS.__setitem__(clip_id, f),
        )
        storage.ensure_capacity(0)
        meta = ffmpeg.probe(out)
        _finish(
            clip_id, status="done", file_name=name, duration=meta["duration"],
            size_bytes=out.stat().st_size,
        )
    except Exception as e:
        log.exception("render failed for clip %s", clip_id)
        out.unlink(missing_ok=True)
        _finish(clip_id, status="failed", error=(str(e) or e.__class__.__name__)[:400])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
