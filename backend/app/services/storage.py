import uuid
from pathlib import Path

from ..config import settings
from ..models.media import MediaItem
from . import ffmpeg


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


def ingest(project_id: int, filename: str, kind: str, tmp_path: Path) -> MediaItem:
    """Move a finished upload into project storage and extract metadata/thumbnail."""
    stored = f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
    dest = media_dir(project_id) / stored
    tmp_path.replace(dest)
    meta = ffmpeg.probe(dest)
    thumb = f"{Path(stored).stem}.jpg"
    ok = ffmpeg.make_thumbnail(dest, thumbs_dir(project_id) / thumb, kind, meta["duration"])
    return MediaItem(
        project_id=project_id,
        filename=filename,
        kind=kind,
        stored_name=stored,
        thumb_name=thumb if ok else None,
        size_bytes=dest.stat().st_size,
        **meta,
    )
