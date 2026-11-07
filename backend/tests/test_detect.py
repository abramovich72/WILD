import time

import pytest
from helpers import make_image, make_video, upload

from app.services import detect
from app.services.detect import FrameDet, common_name, merge_events, parse_prediction

JACKAL = "u;mammalia;carnivora;canidae;canis;aureus;golden jackal"


def pred(path, species=JACKAL, conf=0.9, score=0.8, box=(0.1, 0.2, 0.3, 0.4)):
    return {
        "filepath": str(path),
        "detections": [
            {"category": "1", "label": "animal", "conf": conf, "bbox": list(box),
             "processed_classification": {"class": species, "score": score}}
        ],
    }


# ---------- pure logic ----------


def test_common_name():
    assert common_name(JACKAL) == "golden jackal"
    assert common_name("u;mammalia;carnivora;canidae;;;") == "canidae"
    assert common_name("u;;;;;;") == "animal"


def test_parse_prediction_categories_and_threshold():
    p = {
        "detections": [
            {"category": "1", "conf": 0.05, "bbox": [0, 0, 1, 1]},  # below threshold
            {"category": "2", "conf": 0.9, "bbox": [0, 0, 1, 1]},
            {"category": "3", "conf": 0.9, "bbox": [0, 0, 1, 1]},
            {"category": "1", "conf": 0.9, "bbox": [0, 0, 1, 1]},  # no classification
            {"category": "1", "conf": 0.9, "bbox": [0, 0, 1, 1],
             "processed_classification": {"class": "u;;;;;;blank", "score": 0.9}},
        ]
    }
    got = [d.species for d in parse_prediction(p, 0.2)]
    assert got == ["human", "vehicle", "animal"]
    assert parse_prediction({"failures": ["x"], "detections": [{"conf": 1}]}, 0.2) == []


def test_merge_events_groups_by_gap_and_species():
    fox = FrameDet("fox", 0.5, (0, 0, 1, 1))
    best = FrameDet("fox", 0.9, (0.5, 0.5, 0.1, 0.1))
    frames = [(0, [fox]), (1, [best]), (2, [fox]), (10, [fox]), (3, [FrameDet("boar", 0.7, None)])]
    ev = merge_events(frames, gap=5, step=1, duration=None)
    fox_ev = [e for e in ev if e.species == "fox"]
    assert [(e.start, e.end) for e in fox_ev] == [(0, 3), (10, 11)]
    assert fox_ev[0].conf == 0.9 and fox_ev[0].box == (0.5, 0.5, 0.1, 0.1)
    assert [e.species for e in ev] == ["fox", "boar", "fox"]
    capped = merge_events([(9, [fox])], gap=5, step=1, duration=9.4)
    assert capped[0].end == 9.4


def test_select_frames_skips_static_but_not_forever():
    frames = [(float(i), f"f{i}") for i in range(8)]
    kept = detect.select_frames(frames, lambda a, b: 0.0, threshold=2.0, max_skip=4.0)
    assert [t for t, _ in kept] == [0.0, 4.0]
    kept = detect.select_frames(frames, lambda a, b: 9.0, threshold=2.0, max_skip=4.0)
    assert len(kept) == 8


def test_events_overlap():
    a = detect.Event("x", 1, 0, 5, None)
    assert detect.events_overlap(a, detect.Event("y", 1, 4, 8, None))
    assert not detect.events_overlap(a, detect.Event("y", 1, 5, 8, None))
    i1 = detect.Event("x", 1, None, None, (0, 0, 0.5, 0.5))
    assert detect.events_overlap(i1, detect.Event("y", 1, None, None, (0.05, 0, 0.5, 0.5)))
    assert not detect.events_overlap(i1, detect.Event("y", 1, None, None, (0.6, 0.6, 0.3, 0.3)))


# ---------- API with a fake model ----------


@pytest.fixture()
def fake_model(monkeypatch):
    state = {"fail": False, "calls": 0}

    def fake_classify(paths):
        state["calls"] += 1
        if state["fail"]:
            raise RuntimeError("model exploded")
        return [pred(p) for p in paths]

    monkeypatch.setattr(detect, "classify", fake_classify)
    return state


def wait_status(client, pid, mid, wanted, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        items = {m["id"]: m for m in client.get(f"/api/projects/{pid}/media").json()}
        if items[mid]["detect_status"] in wanted:
            return items[mid]
        time.sleep(0.2)
    raise AssertionError(f"status never reached {wanted}: {items[mid]['detect_status']}")


def project_with(client, tmp_path, name, maker):
    pid = client.post("/api/projects", json={"name": "p"}).json()["id"]
    f = tmp_path / name
    maker(f)
    r = upload(client, pid, name, f.read_bytes())
    assert r.status_code == 201
    return pid, r.json()["id"]


def test_image_detection_rerun_and_corrections(client, tmp_path, fake_model):
    pid, mid = project_with(client, tmp_path, "a.jpg", make_image)
    assert client.get(f"/api/projects/{pid}/media").json()[0]["detect_status"] == "pending"

    r = client.post(f"/api/projects/{pid}/detect", json={})
    assert r.json() == {"queued": 1, "skipped": 0, "queued_ids": [mid]}
    wait_status(client, pid, mid, {"done"})
    dets = client.get(f"/api/projects/{pid}/detections").json()
    assert len(dets) == 1
    d = dets[0]
    assert d["species"] == "golden jackal" and d["display"] == "תן זהוב"
    assert d["start_time"] is None and d["corrected"] is False
    assert (d["box_x"], d["box_w"]) == (0.1, 0.3)

    # already done -> skipped, model not called again
    calls = fake_model["calls"]
    assert client.post(f"/api/projects/{pid}/detect", json={}).json() == {
        "queued": 0,
        "skipped": 1,
        "queued_ids": [],
    }
    assert fake_model["calls"] == calls

    # manual correction survives a forced re-run without duplicating
    fixed = client.patch(f"/api/detections/{d['id']}", json={"species": "red fox"}).json()
    assert fixed["corrected"] is True and fixed["display"] == "שועל אדום"
    from app.services.species_names import display_name

    assert display_name("Indian Crested Porcupine") == "דורבן מצוי"
    assert display_name("unknown thing") == "unknown thing"
    client.post(f"/api/projects/{pid}/detect", json={"force": True})
    wait_status(client, pid, mid, {"done"})
    dets = client.get(f"/api/projects/{pid}/detections").json()
    assert [(x["species"], x["corrected"]) for x in dets] == [("red fox", True)]

    # ... but can be discarded explicitly
    client.post(f"/api/projects/{pid}/detect", json={"force": True, "keep_corrections": False})
    wait_status(client, pid, mid, {"done"})
    dets = client.get(f"/api/projects/{pid}/detections").json()
    assert [(x["species"], x["corrected"]) for x in dets] == [("golden jackal", False)]

    assert client.delete(f"/api/detections/{dets[0]['id']}").status_code == 204
    assert client.get(f"/api/projects/{pid}/detections").json() == []
    assert client.patch("/api/detections/999", json={"species": "x"}).status_code == 404


def test_video_events_and_delete_cascade(client, tmp_path, fake_model):
    pid, mid = project_with(client, tmp_path, "v.mp4", lambda p: make_video(p, seconds=6))
    client.post(f"/api/projects/{pid}/detect", json={"media_ids": [mid]})
    item = wait_status(client, pid, mid, {"done"})
    assert item["detect_error"] is None
    dets = client.get(f"/api/projects/{pid}/detections").json()
    assert len(dets) == 1
    assert dets[0]["start_time"] == 0 and 5 <= dets[0]["end_time"] <= 6.1

    assert client.delete(f"/api/media/{mid}").status_code == 204
    assert client.get(f"/api/projects/{pid}/detections").json() == []


def test_failure_keeps_old_results_and_allows_retry(client, tmp_path, fake_model):
    pid, mid = project_with(client, tmp_path, "a.jpg", make_image)
    client.post(f"/api/projects/{pid}/detect", json={})
    wait_status(client, pid, mid, {"done"})

    fake_model["fail"] = True
    client.post(f"/api/projects/{pid}/detect", json={"force": True})
    item = wait_status(client, pid, mid, {"failed"})
    assert "exploded" in item["detect_error"]
    assert len(client.get(f"/api/projects/{pid}/detections").json()) == 1

    fake_model["fail"] = False
    assert client.post(f"/api/projects/{pid}/detect", json={}).json()["queued"] == 1
    wait_status(client, pid, mid, {"done"})


def test_sse_ends_with_idle(client, tmp_path, fake_model):
    pid, mid = project_with(client, tmp_path, "a.jpg", make_image)
    client.post(f"/api/projects/{pid}/detect", json={})
    wait_status(client, pid, mid, {"done"})
    r = client.get(f"/api/projects/{pid}/detect/events")
    assert r.status_code == 200
    assert '"status": "done"' in r.text and "event: idle" in r.text
    assert client.post("/api/projects/999/detect", json={}).status_code == 404
