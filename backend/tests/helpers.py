import subprocess

from app.config import settings


def make_video(path, seconds=2, color=False):
    src = f"testsrc=duration={seconds}:size=320x240:rate=10"
    subprocess.run(
        [settings.ffmpeg_path, "-y", "-v", "error", "-f", "lavfi", "-i", src,
         "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


def make_image(path):
    subprocess.run(
        [settings.ffmpeg_path, "-y", "-v", "error", "-f", "lavfi", "-i",
         "testsrc=size=320x240:rate=1", "-frames:v", "1", str(path)],
        check=True,
    )


def upload(client, pid, name, data, chunk=40000):
    r = client.post(f"/api/projects/{pid}/uploads", json={"filename": name, "size": len(data)})
    assert r.status_code == 201, r.text
    uid = r.json()["upload_id"]
    off = 0
    while off < len(data):
        r = client.put(f"/api/uploads/{uid}", params={"offset": off}, content=data[off:off + chunk])
        assert r.status_code == 200, r.text
        off = r.json()["offset"]
    return client.post(f"/api/uploads/{uid}/complete")
