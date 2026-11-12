import json
import subprocess
import time
import wave

import pytest
from helpers import make_image, make_video, upload
from sqlmodel import Session

from app import db
from app.config import settings
from app.models.media import Detection
from app.services import clip as cs
from app.services import ffmpeg

# ---------- pure planning ----------


def det(mid, label, conf, start, end, species=None):
    return cs.PlanDet(mid, species or label, label, conf, start, end)


def test_merge_spans_merges_overlaps_and_keeps_best_label():
    got = cs.merge_spans([(0, 3, 0.5, "a"), (2, 5, 0.9, "b"), (8, 9, 0.4, "c")])
    assert got == [(0, 5, "b"), (8, 9, "c")]


def test_fit_to_length_scales_then_drops():
    pcs = [cs.Piece(1, 0, 10, "x"), cs.Piece(2, 5, 25, "y")]
    fit = cs.fit_to_length(pcs, 15)
    assert sum(p.duration for p in fit) <= 15 + 1e-6
    assert [p.media_id for p in fit] == [1, 2] and fit[1].start == 5
    assert cs.fit_to_length(pcs, 100) == pcs
    many = [cs.Piece(i, 0, 5) for i in range(10)]
    assert len(cs.fit_to_length(many, 3)) == 3


def test_plan_timeline_animals_only():
    media = [
        cs.PlanMedia(1, "video", 20.0),
        cs.PlanMedia(2, "image", None),
        cs.PlanMedia(3, "image", None),
        cs.PlanMedia(4, "video", 10.0),
    ]
    dets = [
        det(1, "תן זהוב", 0.9, 3.0, 5.0, "golden jackal"),
        det(1, "גירית", 0.5, 6.0, 7.0, "badger"),  # merges with the previous one after padding
        det(1, "אדם", 0.99, 15.0, 16.0, "human"),  # people are never used
        det(2, "דורבן מצוי", 0.8, None, None, "porcupine"),
        det(4, "אדם", 0.9, 0.0, 9.0, "human"),
    ]
    pcs, skipped = cs.plan_timeline(media, dets, length=60, animals_only=True, pad=1.0)
    assert [(p.media_id, p.start, p.end, p.label) for p in pcs] == [
        (1, 2.0, 8.0, "תן זהוב"),
        (2, 0.0, 3.0, "דורבן מצוי"),
    ]
    assert skipped == 2  # image 3 and video 4 have no animals

    pcs, skipped = cs.plan_timeline(media, dets, length=1000, animals_only=False)
    assert [(p.media_id, p.start, p.end) for p in pcs] == [(1, 0, 20), (2, 0, 3), (3, 0, 3), (4, 0, 10)]
    assert skipped == 0


# ---------- rendering via the API ----------


def wait_clip(client, pid, cid, wanted=("done", "failed"), timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        clips = {c["id"]: c for c in client.get(f"/api/projects/{pid}/clips").json()}
        if clips[cid]["status"] in wanted:
            return clips[cid]
        time.sleep(0.2)
    raise AssertionError(f"clip stuck: {clips[cid]['status']}")


@pytest.fixture()
def project(client, tmp_path):
    pid = client.post("/api/projects", json={"name": "p"}).json()["id"]
    ids = {}
    for name, maker in (("v.mp4", lambda p: make_video(p, seconds=4)), ("a.jpg", make_image)):
        f = tmp_path / name
        maker(f)
        r = upload(client, pid, name, f.read_bytes())
        assert r.status_code == 201
        ids[name] = r.json()["id"]
    return pid, ids


def test_render_clip_with_caption_and_fade(client, project):
    pid, ids = project
    body = {
        "name": "בדיקה",
        "captions": True,
        "transition": "fade",
        "items": [
            {"media_id": ids["v.mp4"], "start": 1.5, "end": 3.5, "label": "תן זהוב"},
            {"media_id": ids["a.jpg"], "end": 1.5, "label": "דורבן מצוי"},
        ],
    }
    r = client.post(f"/api/projects/{pid}/clips", json=body)
    assert r.status_code == 201 and r.json()["name"] == "בדיקה"
    clip = wait_clip(client, pid, r.json()["id"])
    assert clip["status"] == "done", clip["error"]
    assert clip["duration"] == pytest.approx(3.5, abs=0.2)
    assert clip["spec"]["items"][1]["start"] == 0

    f = client.get(f"/api/clips/{clip['id']}/file")
    assert f.status_code == 200 and f.headers["content-type"] == "video/mp4"
    assert "attachment" in client.get(f"/api/clips/{clip['id']}/file?download=true").headers[
        "content-disposition"
    ]
    out = settings.storage_dir / "projects" / str(pid) / "clips"
    mp4 = next(out.glob("*.mp4"))
    meta = ffmpeg.probe(mp4)
    assert (meta["width"], meta["height"]) == (1280, 720)
    # middle of the faded video segment must still show picture, not black
    frame = out / "mid.png"
    subprocess.run(
        [settings.ffmpeg_path, "-y", "-v", "error", "-i", str(mp4), "-ss", "1.0",
         "-frames:v", "1", str(frame)],
        check=True,
    )
    assert frame.stat().st_size > 20000
    frame.unlink()
    assert not list(out.glob(".tmp-*"))  # temp files are cleaned up

    assert client.delete(f"/api/clips/{clip['id']}").status_code == 204
    assert not list(out.glob("*.mp4"))
    assert client.get(f"/api/projects/{pid}/clips").json() == []


def test_render_clip_with_opening_and_closing_titles(client, project):
    pid, ids = project
    r = client.post(
        f"/api/projects/{pid}/clips",
        json={
            "items": [{"media_id": ids["v.mp4"], "start": 0, "end": 2}],
            "opening_title": "חיות הבר בישראל",
            "opening_title_seconds": 1.5,
            "closing_title": "תודה שצפיתם",
            "closing_title_seconds": 2,
            "transition": "fade",
        },
    )
    assert r.status_code == 201
    clip = wait_clip(client, pid, r.json()["id"])
    assert clip["status"] == "done", clip["error"]
    assert clip["duration"] == pytest.approx(5.5, abs=0.2)
    assert clip["spec"]["opening_title"] == "חיות הבר בישראל"
    assert clip["spec"]["opening_title_seconds"] == 1.5
    assert clip["spec"]["closing_title"] == "תודה שצפיתם"
    assert clip["spec"]["closing_title_seconds"] == 2


def test_render_clip_with_generated_music(client, project, monkeypatch):
    from app.services import musicgen

    pid, ids = project

    def fake_generate_music(path, *, duration, prompt, style):
        assert duration == pytest.approx(2)
        assert prompt == "calm wildlife soundtrack"
        assert style == "ambient"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(32000)
            wav.writeframes(b"\x00\x00" * (32000 * 2))

    monkeypatch.setattr(musicgen, "generate_music", fake_generate_music)
    response = client.post(
        f"/api/projects/{pid}/clips",
        json={
            "items": [{"media_id": ids["v.mp4"], "start": 0, "end": 2}],
            "music": {
                "enabled": True,
                "prompt": "calm wildlife soundtrack",
                "style": "ambient",
                "volume": 0.75,
            },
        },
    )
    assert response.status_code == 201
    clip = wait_clip(client, pid, response.json()["id"])
    assert clip["status"] == "done", clip["error"]
    assert clip["spec"]["music"] == {
        "enabled": True,
        "prompt": "calm wildlife soundtrack",
        "style": "ambient",
        "volume": 0.75,
    }

    output = client.get(f"/api/clips/{clip['id']}/file")
    assert output.status_code == 200
    mp4 = next((settings.storage_dir / "projects" / str(pid) / "clips").glob("*.mp4"))
    streams = json.loads(
        subprocess.run(
            [settings.ffprobe_path, "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "json", str(mp4)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )["streams"]
    assert any(stream["codec_type"] == "audio" for stream in streams)


def test_create_clip_validation(client, project):
    pid, ids = project
    url = f"/api/projects/{pid}/clips"
    assert client.post(url, json={"items": []}).status_code == 422
    assert client.post(
        url,
        json={
            "items": [{"media_id": ids["v.mp4"]}],
            "opening_title": "פתיחה",
            "opening_title_seconds": 61,
        },
    ).status_code == 422
    assert client.post(
        url,
        json={
            "items": [{"media_id": ids["v.mp4"], "start": 0, "end": 2}],
            "music": {"enabled": True, "prompt": "   "},
        },
    ).status_code == 422
    assert client.post(url, json={"items": [{"media_id": 999}]}).status_code == 422
    short = {"items": [{"media_id": ids["v.mp4"], "start": 1, "end": 1.05}]}
    assert client.post(url, json=short).status_code == 422
    too_long = {"items": [{"media_id": ids["a.jpg"], "end": 5000}]}
    assert client.post(url, json=too_long).status_code == 422
    assert client.post("/api/projects/999/clips", json=short).status_code == 404
    # an end beyond the video is clamped, not rejected
    r = client.post(url, json={"items": [{"media_id": ids["v.mp4"], "start": 3, "end": 99}]})
    assert r.status_code == 201 and r.json()["spec"]["items"][0]["end"] == pytest.approx(4, abs=0.1)
    wait_clip(client, pid, r.json()["id"])


def test_render_failure_is_reported(client, project, monkeypatch):
    pid, ids = project

    def boom(*a, **k):
        raise RuntimeError("encoder exploded")

    monkeypatch.setattr(cs, "render", boom)
    r = client.post(f"/api/projects/{pid}/clips", json={"items": [{"media_id": ids["a.jpg"]}]})
    clip = wait_clip(client, pid, r.json()["id"])
    assert clip["status"] == "failed" and "exploded" in clip["error"]
    assert client.delete(f"/api/clips/{clip['id']}").status_code == 204
    assert client.get("/api/clips/999/file").status_code == 404


def test_render_fails_when_media_deleted(client, project):
    pid, ids = project
    r = client.post(f"/api/projects/{pid}/clips", json={"items": [{"media_id": ids["a.jpg"]}]})
    wait_clip(client, pid, r.json()["id"])
    # a second clip whose media disappears before rendering
    client.delete(f"/api/media/{ids['a.jpg']}")
    from app.services import renders

    r2 = client.post(f"/api/projects/{pid}/clips", json={"items": [{"media_id": ids["v.mp4"]}]})
    wait_clip(client, pid, r2.json()["id"])
    client.delete(f"/api/media/{ids['v.mp4']}")
    # re-running a stored spec against deleted media must fail cleanly
    renders.run_job(r2.json()["id"])
    clip = wait_clip(client, pid, r2.json()["id"])
    assert clip["status"] == "failed" and "deleted" in clip["error"]


def test_auto_timeline_endpoint(client, project):
    pid, ids = project
    with Session(db.engine) as s:
        s.add(Detection(media_id=ids["v.mp4"], species="golden jackal", confidence=0.9,
                        start_time=1.0, end_time=2.0))
        s.commit()
    url = f"/api/projects/{pid}/timeline/auto"
    r = client.post(url, json={"animals_only": True, "length": 30}).json()
    assert r["items"] == [{"media_id": ids["v.mp4"], "start": 0.0, "end": 3.0, "label": "תן זהוב"}]
    assert r["skipped"] == 1 and r["total"] == 3.0

    r = client.post(url, json={"length": 5, "media_ids": [ids["a.jpg"], ids["v.mp4"]]}).json()
    assert [i["media_id"] for i in r["items"]] == [ids["a.jpg"], ids["v.mp4"]]
    assert r["total"] <= 5.0
    assert client.post("/api/projects/999/timeline/auto", json={}).status_code == 404
