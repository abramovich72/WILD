from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class Project(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=_now)


class MediaItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    filename: str
    kind: str  # "video" | "image"
    stored_name: str
    thumb_name: str | None = None
    size_bytes: int = 0
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    detect_status: str = "pending"  # pending | queued | running | done | failed
    detect_error: str | None = None
    drive_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_now)


class Detection(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    media_id: int = Field(foreign_key="mediaitem.id", index=True)
    species: str  # English common name, or "human" / "vehicle" / "animal"
    confidence: float
    source: str = "speciesnet"  # speciesnet | manual
    start_time: float | None = None  # seconds; None for images
    end_time: float | None = None
    # Relative [x, y, w, h] of the most confident frame in the event.
    box_x: float | None = None
    box_y: float | None = None
    box_w: float | None = None
    box_h: float | None = None
    corrected: bool = False


class Clip(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    name: str
    status: str = "queued"  # queued | running | done | failed
    error: str | None = None
    file_name: str | None = None
    duration: float | None = None
    size_bytes: int = 0
    spec: str = "{}"  # JSON: normalized timeline items and render options
    created_at: datetime = Field(default_factory=_now)
