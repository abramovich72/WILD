from helpers import make_video as _make_video
from helpers import upload as _upload

from app.config import settings  # noqa: F401


def test_full_flow(client, tmp_path):
    pid = client.post("/api/projects", json={"name": "x"}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"name": "y"}).json()["name"] == "y"

    vid = tmp_path / "v.mp4"
    _make_video(vid)
    data = vid.read_bytes()
    r = _upload(client, pid, "v.mp4", data)
    assert r.status_code == 201
    item = r.json()
    assert item["kind"] == "video" and round(item["duration"]) == 2
    assert item["width"] == 320 and item["thumb_name"]

    assert client.get(f"/api/media/{item['id']}/thumb").status_code == 200
    assert client.get(f"/api/media/{item['id']}/file").content == data
    part = client.get(f"/api/media/{item['id']}/file", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100

    assert len(client.get(f"/api/projects/{pid}/media").json()) == 1
    from app.services import storage

    stored = storage.media_dir(pid) / item["stored_name"]
    thumb = storage.thumbs_dir(pid) / item["thumb_name"]
    assert stored.exists() and thumb.exists()
    assert client.delete(f"/api/media/{item['id']}").status_code == 204
    assert not stored.exists() and not thumb.exists()
    assert client.delete(f"/api/media/{item['id']}").status_code == 404
    assert client.get(f"/api/projects/{pid}/media").json() == []


def test_rejects_bad_type_and_offset(client):
    pid = client.post("/api/projects", json={"name": "x"}).json()["id"]
    assert client.post(f"/api/projects/{pid}/uploads",
                       json={"filename": "a.exe", "size": 5}).status_code == 415
    uid = client.post(f"/api/projects/{pid}/uploads",
                      json={"filename": "a.jpg", "size": 5}).json()["upload_id"]
    assert client.put(f"/api/uploads/{uid}", params={"offset": 3}, content=b"ab").status_code == 409
    assert client.get("/api/uploads/not-a-uuid").status_code == 404


def test_avi_gets_mp4_preview(client, tmp_path):
    pid = client.post("/api/projects", json={"name": "x"}).json()["id"]
    avi = tmp_path / "v.avi"
    _make_video(avi)
    item = _upload(client, pid, "v.avi", avi.read_bytes()).json()
    r = client.get(f"/api/media/{item['id']}/preview")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    assert r.content[4:8] == b"ftyp"
    mp4 = tmp_path / "v.mp4"
    _make_video(mp4)
    item2 = _upload(client, pid, "v.mp4", mp4.read_bytes()).json()
    assert client.get(f"/api/media/{item2['id']}/preview").content == mp4.read_bytes()
    assert client.delete(f"/api/media/{item['id']}").status_code == 204