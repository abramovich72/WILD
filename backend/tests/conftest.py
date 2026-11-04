import pytest
from fastapi.testclient import TestClient

from app.config import settings


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from sqlmodel import create_engine

    from app import db

    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "preload_model", False)
    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{tmp_path / 't.db'}",
                                                    connect_args={"check_same_thread": False}))
    from app.main import app

    with TestClient(app) as c:
        yield c
