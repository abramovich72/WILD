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
_active_job_id: str | None = None
_MAX_FOLDERS = 2000


class ImportAlreadyRunning(Exception):
    pass


class ImportNotActive(Exception):
    pass


class ImportCancelled(Exception):
    pass


def _check_cancelled(job: dict) -> None:
    if job["_cancel_event"].is_set():
        raise ImportCancelled


def create_job(project_id: int, items: list[dict], recursive: bool = False) -> dict:
    global _active_job_id, _worker
    job = {
        "id": uuid.uuid4().hex,
        "project_id": project_id,
        "status": "queued",  # queued | running | done | failed | cancelled
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
        "_cancel_event": threading.Event(),
    }
    with _worker_lock:
        if _active_job_id is not None:
            active = JOBS.get(_active_job_id)
            if active and active["status"] in ("queued", "running"):
                raise ImportAlreadyRunning
        JOBS[job["id"]] = job
        _active_job_id = job["id"]
        _queue.put(job["id"])
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, name="drive-import", daemon=True)
            _worker.start()
    return public(job)


def active_job() -> dict | None:
    with _worker_lock:
        job = JOBS.get(_active_job_id) if _active_job_id else None
        return public(job) if job and job["status"] in ("queued", "running") else None


def cancel_job(job_id: str) -> dict:
    with _worker_lock:
        job = JOBS.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job["status"] == "cancelled":
            return public(job)
        if job["status"] not in ("queued", "running") or _active_job_id != job_id:
            raise ImportNotActive
        job["_cancel_event"].set()
        job["phase"] = "מבטל הורדה…"
        return public(job)


def public(job: dict) -> dict:
    return {k: v for k, v in job.items() if not k.startswith("_")}


def _loop() -> None:
    global _active_job_id
    while True:
        job = JOBS[_queue.get()]
        try:
            _run(job)
        except ImportCancelled:
            job["status"] = "cancelled"
            job["phase"] = "ההורדה בוטלה"
            job["current"] = None
        except Exception:  # keep the worker alive whatever happens
            log.exception("drive import crashed")
            job["status"] = "failed"
            job["phase"] = "נכשל"
        finally:
            job.pop("_items", None)
            with _worker_lock:
                if _active_job_id == job["id"]:
                    _active_job_id = None


def _expand(job: dict) -> list[dict]:
    """Flatten selected files and folders (recursively) into a list of files."""
    files: list[dict] = []
    stack = [(it, 0) for it in job["_items"]]
    folders_seen = 0
    while stack:
        _check_cancelled(job)
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
                _check_cancelled(job)
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
    _check_cancelled(job)
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
        _check_cancelled(job)
        job["current"] = f["name"]
        job["phase"] = "מוריד"
        nk = _name_and_kind(f)
        if not nk:
            job["failed"] += 1
            job["errors"].append({"name": f["name"], "error": "סוג קובץ לא נתמך"})
            continue
        size = f.get("size")
        expected_size = size if isinstance(size, int) and size > 0 else None
        if expected_size is not None and expected_size > settings.max_upload_bytes:
            job["failed"] += 1
            job["errors"].append({"name": f["name"], "error": "הקובץ גדול מדי"})
            continue
        name, kind = nk
        reservation_id = uuid.uuid4().hex
        part = storage.uploads_dir() / f"drive_{reservation_id}.part"
        reservation = part.with_suffix(".json")
        reserved_size = expected_size or settings.max_upload_bytes
        try:
            storage.reserve_upload(
                reservation,
                part,
                {"size": reserved_size, "filename": name, "kind": kind},
            )
        except storage.StorageQuotaExceeded as e:
            job["failed"] += 1
            job["errors"].append({"name": f["name"], "error": str(e)})
            continue

        downloaded = 0

        def on_bytes(count: int, file_size: int | None = expected_size) -> None:
            nonlocal downloaded
            downloaded += count
            if downloaded > settings.max_upload_bytes or (
                file_size is not None and downloaded > file_size
            ):
                raise storage.UploadLimitExceeded("הקובץ גדול מדי")
            job["bytes_done"] += count

        try:
            gdrive.download(
                f["id"], part, f.get("resource_key"),
                on_bytes=on_bytes,
                cancel_event=job["_cancel_event"],
            )
            _check_cancelled(job)
            item = storage.ingest(pid, name, kind, part, reservation)
            try:
                _check_cancelled(job)
            except ImportCancelled:
                (storage.media_dir(pid) / item.stored_name).unlink(missing_ok=True)
                if item.thumb_name:
                    (storage.thumbs_dir(pid) / item.thumb_name).unlink(missing_ok=True)
                raise
            item.drive_id = f["id"]
            with Session(db.engine) as s:
                s.add(item)
                s.commit()
            job["done"] += 1
        except gdrive.DownloadCancelled as e:
            raise ImportCancelled from e
        except ImportCancelled:
            raise
        except Exception as e:  # noqa: BLE001 - one bad file must not stop the batch
            log.warning("drive import failed for %s: %s", f["name"], e)
            msg = str(e) if isinstance(e, (gdrive.DriveError, storage.StorageQuotaExceeded,
                                           storage.UploadLimitExceeded)) else "הורדה או עיבוד נכשלו"
            job["failed"] += 1
            job["errors"].append({"name": f["name"], "error": msg})
        finally:
            Path(part).unlink(missing_ok=True)
            storage.release_reservation(reservation)
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
