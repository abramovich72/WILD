from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import settings

settings.storage_dir.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    f"sqlite:///{settings.storage_dir / 'wild.db'}",
    connect_args={"check_same_thread": False},
)


def _add_missing_columns() -> None:
    """Tiny migration: create_all does not add columns to existing tables."""
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(mediaitem)")}
        if "detect_status" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE mediaitem ADD COLUMN detect_status VARCHAR DEFAULT 'pending' NOT NULL"
            )
        if "detect_error" not in cols:
            conn.exec_driver_sql("ALTER TABLE mediaitem ADD COLUMN detect_error VARCHAR")
        if "drive_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE mediaitem ADD COLUMN drive_id VARCHAR")
            conn.exec_driver_sql("CREATE INDEX ix_mediaitem_drive_id ON mediaitem (drive_id)")
        # Jobs interrupted by a restart go back to pending.
        conn.exec_driver_sql(
            "UPDATE mediaitem SET detect_status='pending' "
            "WHERE detect_status IN ('queued','running')"
        )
        conn.exec_driver_sql(
            "UPDATE clip SET status='failed', error='interrupted by server restart' "
            "WHERE status IN ('queued','running')"
        )


def init_db() -> None:
    from .models import media  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
