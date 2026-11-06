import json
import threading
import time
import uuid
from pathlib import Path

from ..config import settings
from ..models.media import MediaItem
from . import ffmpeg

THUMBNAIL_RESERVE_BYTES = 5 * 1024 * 1024
_quota_lock = threading.RLock()


class StorageQuotaExceeded(Exception):
    pass


class UploadLimitExceeded(Exception):
    pass


def _file_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _used_bytes() -> int:
    projects = settings.storage_dir / "projects"
    uploads = settings.storage_dir / "uploads"
    used = _file_bytes(projects)
    if not uploads.exists():
        return used

    reserved_parts: set[Path] = set()
    for metadata_path in uploads.glob("*.json"):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        declared = metadata.get("reserved_bytes", metadata.get("size"))
        if not isinstance(declared, int) or declared < 0:
            raise RuntimeError(f"Invalid upload reservation: {metadata_path.name}")
        part_path = metadata_path.with_suffix(".part")
        actual = part_path.stat().st_size if part_path.is_file() else 0
        used += max(declared, actual)
        reserved_parts.add(part_path)

    for part_path in uploads.glob("*.part"):
        if part_path not in reserved_parts and part_path.is_file():
            used += part_path.stat().st_size
    return used


def used_bytes() -> int:
    with _quota_lock:
        return _used_bytes()


def _ensure_capacity(additional_bytes: int) -> None:
    limit = settings.max_storage_bytes
    if limit <= 0:
        return
    used = _used_bytes()
    if used + additional_bytes > limit:
        raise StorageQuotaExceeded(
            f"Storage quota exceeded ({used} bytes used, {additional_bytes} requested, "
            f"{limit} byte limit). Delete stored media or increase MAX_STORAGE_BYTES."
        )


def ensure_capacity(additional_bytes: int) -> None:
    if additional_bytes < 0:
        raise ValueError("additional_bytes cannot be negative")
    with _quota_lock:
        _ensure_capacity(additional_bytes)


def over_quota() -> bool:
    limit = settings.max_storage_bytes
    return limit > 0 and used_bytes() > limit


def reserve_upload(meta_path: Path, part_path: Path, metadata: dict) -> None:
    size = metadata.get("size")
    if not isinstance(size, int) or size <= 0:
        raise ValueError("Upload reservation requires a positive size")
    record = {**metadata, "reserved_bytes": size + THUMBNAIL_RESERVE_BYTES}
    with _quota_lock:
        _ensure_capacity(record["reserved_bytes"])
        try:
            meta_path.write_text(json.dumps(record), encoding="utf-8")
            part_path.touch()
        except OSError:
            meta_path.unlink(missing_ok=True)
            part_path.unlink(missing_ok=True)
            raise


def release_reservation(meta_path: Path) -> None:
    with _quota_lock:
        meta_path.unlink(missing_ok=True)


def cleanup_expired_uploads(ttl_seconds: int | None = None) -> int:
    ttl = settings.upload_ttl_seconds if ttl_seconds is None else ttl_seconds
    if ttl <= 0:
        return 0
    root = uploads_dir()
    cutoff = time.time() - ttl
    removed = 0
    with _quota_lock:
        for meta_path in root.glob("*.json"):
            part_path = meta_path.with_suffix(".part")
            paths = [path for path in (meta_path, part_path) if path.is_file()]
            if paths and max(path.stat().st_mtime for path in paths) < cutoff:
                meta_path.unlink(missing_ok=True)
                part_path.unlink(missing_ok=True)
                removed += 1
        for part_path in root.glob("*.part"):
            if part_path.with_suffix(".json").exists():
                continue
            if part_path.stat().st_mtime < cutoff:
                part_path.unlink(missing_ok=True)
                removed += 1
    return removed


def media_dir(project_id: int) -> Path:
    d = settings.storage_dir / "projects" / str(project_id) / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumbs_dir(project_id: int) -> Path:
    d = settings.storage_dir / "projects" / str(project_id) / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clips_dir(project_id: int) -> Path:
    d = settings.storage_dir / "projects" / str(project_id) / "clips"
    d.mkdir(parents=True, exist_ok=True)
    return d


def previews_dir(project_id: int) -> Path:
    d = settings.storage_dir / "projects" / str(project_id) / "previews"
    d.mkdir(parents=True, exist_ok=True)
    return d


def uploads_dir() -> Path:
    d = settings.storage_dir / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ingest(
    project_id: int,
    filename: str,
    kind: str,
    tmp_path: Path,
    reservation_path: Path | None = None,
) -> MediaItem:
    """Move a finished upload into project storage and extract metadata/thumbnail."""
    stored = f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
    dest = media_dir(project_id) / stored
    reserved_thumbnail = 0
    with _quota_lock:
        if reservation_path and reservation_path.is_file():
            reservation = json.loads(reservation_path.read_text(encoding="utf-8"))
            reserved = reservation.get("reserved_bytes", reservation.get("size", 0))
            reserved_thumbnail = max(0, reserved - tmp_path.stat().st_size)
        else:
            in_storage = settings.storage_dir.resolve() in tmp_path.resolve().parents
            additional = THUMBNAIL_RESERVE_BYTES
            if not in_storage:
                additional += tmp_path.stat().st_size
            _ensure_capacity(additional)
        tmp_path.replace(dest)
        if reservation_path and reservation_path.is_file():
            reservation["size"] = 0
            reservation["reserved_bytes"] = reserved_thumbnail
            reservation_path.write_text(json.dumps(reservation), encoding="utf-8")

    meta = ffmpeg.probe(dest)
    thumb = f"{Path(stored).stem}.jpg"
    thumb_path = thumbs_dir(project_id) / thumb
    ok = ffmpeg.make_thumbnail(dest, thumb_path, kind, meta["duration"])
    if ok and reservation_path and reservation_path.is_file():
        with _quota_lock:
            reservation = json.loads(reservation_path.read_text(encoding="utf-8"))
            reservation["reserved_bytes"] = max(
                0, reserved_thumbnail - thumb_path.stat().st_size
            )
            reservation_path.write_text(json.dumps(reservation), encoding="utf-8")
    if ok and over_quota():
        thumb_path.unlink(missing_ok=True)
        ok = False
    return MediaItem(
        project_id=project_id,
        filename=filename,
        kind=kind,
        stored_name=stored,
        thumb_name=thumb if ok else None,
        size_bytes=dest.stat().st_size,
        **meta,
    )
