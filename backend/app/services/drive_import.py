"""Background worker that downloads selected Google Drive files and folders into a project."""

import logging
import mimetypes
import queue
import threading
import uuid
from pathlib import Path

from sqlmodel import Session, select

from .. import db
from ..config import settings
from ..models.media import MediaItem
from . import ffmpeg, gdrive, storage

log = logging.getLogger("wild.drive")

JOBS: dict[str, dict] = {}

_queue: queue.Queue[str] = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_MAX_FOLDERS = 2000


def create_job(project_id: int, items: list[dict], recursive: bool = False) -> dict:
    job = {
        "id": uuid.uuid4().hex,
        "project_id": project_id,
        "status": "queued",  # queued | running | done | failed
        "phase": "ממתין",
        "total": 0,
        "done": 0,
        "skipped": 0,
        "failed": 0,
        "current": None,
        "bytes_done": 0,
        "errors": [],
        "_items": items,
        "recursive": recursive,
    }
    JOBS[job["id"]] = job
    global _worker
    _queue.put(job["id"])
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, name="drive-import", daemon=True)
            _worker.start()
    return public(job)


def public(job: dict) -> dict:
    return {k: v for k, v in job.items() if not k.startswith("_")}


def _loop() -> None:
    while True:
        job = JOBS[_queue.get()]
        try:
            _run(job)
        except Exception:  # keep the worker alive whatever happens
            log.exception("drive import crashed")
            job["status"] = "failed"
            job["phase"] = "נכשל"
        finally:
            job.pop("_items", None)


def _expand(job: dict) -> list[dict]:
    """Flatten selected files and folders (recursively) into a list of files."""
    files: list[dict] = []
    stack = [(it, 0) for it in job["_items"]]
    folders_seen = 0
    while stack:
        it, depth = stack.pop(0)
        if it["kind"] != "folder":
            files.append(it)
            continue
        if depth > 0 and not job["recursive"]:
            continue
        folders_seen += 1
        if folders_seen > _MAX_FOLDERS:
            job["errors"].append({"name": it["name"], "error": "יותר מדי תיקיות, דילגתי"})
            continue
        job["phase"] = f"סורק תיקייה: {it['name']}"
        token = None
        try:
            while True:
                page = gdrive.list_items(it["id"], token, it.get("resource_key"))
                stack.extend((i, depth + 1) for i in page["items"])
                token = page["next_page_token"]
                if not token:
                    break
        except gdrive.DriveError as e:
            job["failed"] += 1
            job["errors"].append({"name": it["name"], "error": e.message})
    return files


def _name_and_kind(f: dict) -> tuple[str, str] | None:
    name = f["name"]
    kind = ffmpeg.detect_kind(name)
    if not kind:
        ext = mimetypes.guess_extension(f.get("mime", "").split(";")[0]) or ""
        name += ext
        kind = ffmpeg.detect_kind(name)
    return (name, kind) if kind else None


def _run(job: dict) -> None:
    job["status"] = "running"
    files = _expand(job)
    pid = job["project_id"]
    with Session(db.engine) as s:
        have = set(
            s.exec(
                select(MediaItem.drive_id).where(
                    MediaItem.project_id == pid, MediaItem.drive_id.is_not(None)  # type: ignore[union-attr]
                )
            ).all()
        )
    todo: list[dict] = []
    for f in files:
        if f["id"] in have:
            job["skipped"] += 1
        else:
            have.add(f["id"])
            todo.append(f)
    job["total"] = len(todo)

    for f in todo:
        job["current"] = f["name"]
        job["phase"] = "מוריד"
        nk = _name_and_kind(f)
        if not nk:
            job["failed"] += 1
            job["errors"].append({"name": f["name"], "error": "סוג קובץ לא נתמך"})
            continue
        if f.get("size") and f["size"] > settings.max_upload_bytes:
            job["failed"] += 1
            job["errors"].append({"name": f["name"], "error": "הקובץ גדול מדי"})
            continue
        name, kind = nk
        part = storage.uploads_dir() / f"drive_{job['id']}_{f['id']}.part"
        try:
            gdrive.download(
                f["id"], part, f.get("resource_key"),
                on_bytes=lambda n: job.__setitem__("bytes_done", job["bytes_done"] + n),
            )
            item = storage.ingest(pid, name, kind, part)
            item.drive_id = f["id"]
            with Session(db.engine) as s:
                s.add(item)
                s.commit()
            job["done"] += 1
        except Exception as e:  # noqa: BLE001 - one bad file must not stop the batch
            log.warning("drive import failed for %s: %s", f["name"], e)
            Path(part).unlink(missing_ok=True)
            job["failed"] += 1
            msg = e.message if isinstance(e, gdrive.DriveError) else "הורדה או עיבוד נכשלו"
            job["errors"].append({"name": f["name"], "error": msg})
    job["current"] = None
    job["status"] = "done"
    job["phase"] = "הסתיים"


def imported_ids(project_id: int) -> list[str]:
    with Session(db.engine) as s:
        return list(
            s.exec(
                select(MediaItem.drive_id).where(
                    MediaItem.project_id == project_id,
                    MediaItem.drive_id.is_not(None),  # type: ignore[union-attr]
                )
            ).all()
        )
