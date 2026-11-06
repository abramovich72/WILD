import json
import threading
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import settings
from app.services import gdrive


@pytest.fixture()
def drive(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    return client


def sign_in(monkeypatch, expires_in=3600):
    def fake_token(data):
        return {"access_token": "AT", "refresh_token": "RT", "expires_in": expires_in}

    monkeypatch.setattr(gdrive, "_token_request", fake_token)


def test_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    assert client.get("/api/drive/status").json() == {
        "enabled": True,
        "configured": False,
        "connected": False,
        "email": None,
    }
    assert client.get("/api/drive/auth-url").status_code == 503


def test_login_flow(drive, monkeypatch):
    url = drive.get("/api/drive/auth-url").json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["scope"] == [gdrive.SCOPE]
    assert q["code_challenge_method"] == ["S256"]
    assert q["redirect_uri"] == [settings.drive_redirect_uri]

    sign_in(monkeypatch)
    monkeypatch.setattr(
        gdrive, "api_get", lambda path, params, keys=None: {"user": {"emailAddress": "a@b.c"}}
    )
    r = drive.get(
        "/api/drive/callback", params={"code": "x", "state": q["state"][0]}, follow_redirects=False
    )
    assert r.headers["location"].endswith("?drive=connected")
    assert drive.get("/api/drive/status").json() == {
        "enabled": True,
        "configured": True,
        "connected": True,
        "email": "a@b.c",
    }
    drive.post("/api/drive/logout")
    assert drive.get("/api/drive/status").json()["connected"] is False


def test_drive_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "drive_enabled", False)
    assert client.get("/api/drive/status").json() == {
        "enabled": False,
        "configured": False,
        "connected": False,
        "email": None,
    }

    requests = [
        client.get("/api/drive/auth-url"),
        client.get("/api/drive/callback", params={"code": "x", "state": "y"}),
        client.post("/api/drive/logout"),
        client.get("/api/drive/files"),
        client.post("/api/drive/resolve", json={"url": "https://drive.google.com/file/d/x"}),
        client.post(
            "/api/drive/import",
            json={"project_id": 1, "items": [{"id": "x", "name": "x.jpg", "kind": "image"}]},
        ),
        client.get("/api/drive/imports/nope"),
        client.get("/api/drive/imported/1"),
    ]
    assert all(response.status_code == 503 for response in requests)


def test_callback_rejects_unknown_state(drive):
    r = drive.get(
        "/api/drive/callback", params={"code": "x", "state": "nope"}, follow_redirects=False
    )
    assert r.headers["location"].endswith("?drive=failed")
    r = drive.get("/api/drive/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert r.headers["location"].endswith("?drive=denied")


def test_files_require_sign_in(drive):
    assert drive.get("/api/drive/files").status_code == 401


def test_list_files(drive, monkeypatch):
    gdrive._save({"access_token": "AT", "refresh_token": "RT", "expires_at": 9e12})
    seen = {}

    def fake_get(path, params, keys=None):
        seen.update(path=path, params=params, keys=keys)
        return {
            "nextPageToken": "N",
            "files": [
                {"id": "f1", "name": "Trip", "mimeType": gdrive.FOLDER},
                {"id": "v1", "name": "a.mp4", "mimeType": "video/mp4", "size": "123"},
                {"id": "i1", "name": "b.jpg", "mimeType": "image/jpeg"},
            ],
        }

    monkeypatch.setattr(gdrive, "api_get", fake_get)
    body = drive.get("/api/drive/files", params={"parent": "folderX"}).json()
    assert [i["kind"] for i in body["items"]] == ["folder", "video", "image"]
    assert body["items"][1]["size"] == 123
    assert body["next_page_token"] == "N"
    assert "'folderX' in parents" in seen["params"]["q"]

    drive.get("/api/drive/files", params={"parent": "shared"})
    assert seen["params"]["q"].startswith("sharedWithMe=true")

    drive.get("/api/drive/files", params={"parent": "abc", "resource_key": "RK"})
    assert seen["keys"] == "abc/RK"


def test_parent_id_cannot_inject_query(drive, monkeypatch):
    gdrive._save({"access_token": "AT", "refresh_token": "RT", "expires_at": 9e12})
    seen = {}
    monkeypatch.setattr(
        gdrive, "api_get", lambda path, params, keys=None: seen.update(p=params) or {"files": []}
    )
    drive.get("/api/drive/files", params={"parent": "x' or 'a'='a"})
    assert "'x or a=a' in parents" in seen["p"]["q"]


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://drive.google.com/drive/folders/ABC_def-1?usp=sharing", ("ABC_def-1", None)),
        ("https://drive.google.com/drive/u/0/folders/ABC", ("ABC", None)),
        ("https://drive.google.com/file/d/XYZ/view?resourcekey=0-k", ("XYZ", "0-k")),
        ("https://drive.google.com/open?id=QQQ", ("QQQ", None)),
    ],
)
def test_parse_link(url, expected):
    assert gdrive.parse_link(url) == expected


def test_parse_link_rejects_other_hosts():
    with pytest.raises(gdrive.DriveError):
        gdrive.parse_link("https://example.com/folders/ABC")


def test_resolve_link(drive, monkeypatch):
    gdrive._save({"access_token": "AT", "refresh_token": "RT", "expires_at": 9e12})
    monkeypatch.setattr(
        gdrive,
        "api_get",
        lambda path, params, keys=None: {"id": "ABC", "name": "Shared", "mimeType": gdrive.FOLDER},
    )
    r = drive.post(
        "/api/drive/resolve",
        json={"url": "https://drive.google.com/drive/folders/ABC?resourcekey=0-k"},
    )
    assert r.json()["kind"] == "folder"
    assert r.json()["resource_key"] == "0-k"

    monkeypatch.setattr(
        gdrive,
        "api_get",
        lambda path, params, keys=None: {"id": "D", "name": "x.pdf", "mimeType": "application/pdf"},
    )
    r = drive.post("/api/drive/resolve", json={"url": "https://drive.google.com/file/d/D/view"})
    assert r.status_code == 422


def test_token_refresh(drive, monkeypatch):
    gdrive._save({"access_token": "OLD", "refresh_token": "RT", "expires_at": 0})
    calls = []

    def fake_token(data):
        calls.append(data["grant_type"])
        return {"access_token": "NEW", "expires_in": 3600}

    monkeypatch.setattr(gdrive, "_token_request", fake_token)
    assert gdrive._access_token() == "NEW"
    assert calls == ["refresh_token"]
    assert json.loads(gdrive._token_path().read_text())["access_token"] == "NEW"
    assert gdrive._access_token() == "NEW"
    assert calls == ["refresh_token"]


def test_download_can_be_cancelled_mid_stream(tmp_path, monkeypatch):
    cancel_event = threading.Event()
    destination = tmp_path / "download.part"

    class FakeResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def iter_bytes(self, _chunk_size):
            yield b"first"
            yield b"second"

    monkeypatch.setattr(gdrive.httpx, "stream", lambda *_args, **_kwargs: FakeResponse())

    def cancel_after_first_chunk(_count):
        cancel_event.set()

    with pytest.raises(gdrive.DownloadCancelled):
        gdrive.download(
            "file-id",
            destination,
            on_bytes=cancel_after_first_chunk,
            cancel_event=cancel_event,
        )
    assert destination.read_bytes() == b"first"


def _wait(client, job_id):
    import time

    for _ in range(100):
        job = client.get(f"/api/drive/imports/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError("import did not finish")


def _fake_ingest(monkeypatch):
    from app.models.media import MediaItem
    from app.services import drive_import

    def ingest(project_id, filename, kind, tmp_path, reservation_path=None):
        size = tmp_path.stat().st_size
        tmp_path.unlink()
        return MediaItem(project_id=project_id, filename=filename, kind=kind,
                         stored_name="x" + filename, size_bytes=size)

    monkeypatch.setattr(drive_import.storage, "ingest", ingest)


def test_import_folder_recursive_and_dedupe(drive, monkeypatch):
    sign_in(monkeypatch)
    _fake_ingest(monkeypatch)
    tree = {
        "F": {"items": [
            {"id": "a", "name": "a.jpg", "kind": "image", "mime": "image/jpeg", "size": 3},
            {"id": "SUB", "name": "sub", "kind": "folder", "mime": "", "size": None},
        ]},
        "SUB": {"items": [
            {"id": "b", "name": "b.mp4", "kind": "video", "mime": "video/mp4", "size": 3},
            {"id": "c", "name": "noext", "kind": "image", "mime": "image/png", "size": 3},
            {"id": "d", "name": "bad.mp4", "kind": "video", "mime": "video/mp4", "size": 3},
        ]},
    }
    monkeypatch.setattr(
        gdrive, "list_items",
        lambda parent, token=None, key=None: {**tree[parent], "next_page_token": None},
    )

    def fake_download(
        file_id, dest, resource_key=None, on_bytes=None, attempts=5, cancel_event=None
    ):
        if file_id == "d":
            raise gdrive.DriveError(403, "Google denied access to this file")
        dest.write_bytes(b"abc")
        if on_bytes:
            on_bytes(3)

    monkeypatch.setattr(gdrive, "download", fake_download)
    monkeypatch.setattr(gdrive, "status", lambda: {"connected": True})
    pid = drive.post("/api/projects", json={"name": "p"}).json()["id"]
    body = {"project_id": pid, "recursive": True, "items": [
        {"id": "F", "name": "F", "kind": "folder"},
        {"id": "a", "name": "a.jpg", "kind": "image", "mime": "image/jpeg", "size": 3},
    ]}
    job = _wait(drive, drive.post("/api/drive/import", json=body).json()["id"])
    assert (job["done"], job["failed"], job["skipped"]) == (3, 1, 1)
    assert job["errors"][0]["name"] == "bad.mp4"
    media = {m["filename"] for m in drive.get(f"/api/projects/{pid}/media").json()}
    assert media == {"a.jpg", "b.mp4", "noext.png"}
    assert sorted(drive.get(f"/api/drive/imported/{pid}").json()) == ["a", "b", "c"]

    again = _wait(drive, drive.post("/api/drive/import", json=body).json()["id"])
    assert (again["done"], again["skipped"], again["failed"]) == (0, 4, 1)


def test_import_validation(drive, monkeypatch):
    sign_in(monkeypatch)
    pid = drive.post("/api/projects", json={"name": "p"}).json()["id"]
    assert drive.post("/api/drive/import", json={"project_id": 999, "items": []}).status_code == 404
    assert drive.post("/api/drive/import", json={"project_id": pid, "items": []}).status_code == 422
    bad = {"project_id": pid, "items": [{"id": "x", "name": "x", "kind": "other"}]}
    assert drive.post("/api/drive/import", json=bad).status_code == 422
    assert drive.get("/api/drive/imports/nope").status_code == 404


def test_only_one_import_runs_and_active_import_can_be_cancelled(drive, monkeypatch):
    from app.services import drive_import

    _fake_ingest(monkeypatch)
    monkeypatch.setattr(gdrive, "status", lambda: {"connected": True})
    started = threading.Event()
    calls = 0

    def fake_download(_file_id, dest, *_args, cancel_event=None, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            dest.write_bytes(b"partial")
            started.set()
            assert cancel_event is not None
            cancel_event.wait(2)
            raise gdrive.DownloadCancelled
        dest.write_bytes(b"abc")

    monkeypatch.setattr(gdrive, "download", fake_download)
    pid = drive.post("/api/projects", json={"name": "p"}).json()["id"]
    body = {
        "project_id": pid,
        "items": [{"id": "file-1", "name": "a.jpg", "kind": "image", "size": 3}],
    }

    first = drive.post("/api/drive/import", json=body)
    assert first.status_code == 202
    job_id = first.json()["id"]
    assert started.wait(2)
    assert drive.get("/api/drive/imports/active").json()["id"] == job_id
    assert drive.post("/api/drive/import", json=body).status_code == 409

    cancel = drive.post(f"/api/drive/imports/{job_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["phase"] == "מבטל הורדה…"
    cancelled = _wait(drive, job_id)
    assert cancelled["status"] == "cancelled"
    assert drive.get("/api/drive/imports/active").json() is None
    assert not list(drive_import.storage.uploads_dir().glob("*.part"))

    next_job = drive.post("/api/drive/import", json=body)
    assert next_job.status_code == 202
    finished = _wait(drive, next_job.json()["id"])
    assert finished["status"] == "done" and finished["done"] == 1


def test_download_resumes_and_retries(tmp_path, monkeypatch):
    import httpx

    sign_in(monkeypatch)
    monkeypatch.setattr(gdrive.time, "sleep", lambda s: None)
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    gdrive._save({"access_token": "AT", "refresh_token": "RT", "expires_at": 9e12})
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.headers.get("range"))
        if len(calls) == 1:
            return httpx.Response(503)
        if len(calls) == 2:
            return httpx.Response(206, content=b"world")
        return httpx.Response(500)

    real = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        gdrive.httpx, "stream",
        lambda method, url, **kw: real.stream(method, url, **kw),
    )
    dest = tmp_path / "f.part"
    dest.write_bytes(b"hello")
    gdrive.download("id1", dest, "rk")
    assert calls == ["bytes=5-", "bytes=5-"]
    assert dest.read_bytes() == b"helloworld"


def test_import_not_recursive_skips_subfolders(drive, monkeypatch):
    sign_in(monkeypatch)
    _fake_ingest(monkeypatch)
    tree = {
        "F": [{"id": "a", "name": "a.jpg", "kind": "image", "mime": "image/jpeg", "size": 3},
              {"id": "SUB", "name": "sub", "kind": "folder", "mime": "", "size": None}],
        "SUB": [{"id": "b", "name": "b.jpg", "kind": "image", "mime": "image/jpeg", "size": 3}],
    }
    listed = []

    def list_items(parent, token=None, key=None):
        listed.append(parent)
        return {"items": tree[parent], "next_page_token": None}

    monkeypatch.setattr(gdrive, "list_items", list_items)
    monkeypatch.setattr(gdrive, "status", lambda: {"connected": True})
    monkeypatch.setattr(gdrive, "download", lambda fid, dest, *a, **k: dest.write_bytes(b"abc"))
    pid = drive.post("/api/projects", json={"name": "p"}).json()["id"]
    body = {"project_id": pid, "items": [{"id": "F", "name": "F", "kind": "folder"}]}
    job = _wait(drive, drive.post("/api/drive/import", json=body).json()["id"])
    assert job["done"] == 1 and listed == ["F"]