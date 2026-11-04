import json
import subprocess
from pathlib import Path

from ..config import settings

VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm", ".mts", ".3gp"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def detect_kind(filename: str) -> str | None:
    ext = Path(filename).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    return None


def probe(path: Path) -> dict:
    """Return duration/width/height; missing values are None."""
    cmd = [
        settings.ffprobe_path, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration",
        "-of", "json", str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True).stdout
        data = json.loads(out)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return {"duration": None, "width": None, "height": None}
    stream = (data.get("streams") or [{}])[0]
    dur = (data.get("format") or {}).get("duration")
    return {
        "duration": float(dur) if dur not in (None, "N/A") else None,
        "width": stream.get("width"),
        "height": stream.get("height"),
    }


BROWSER_VIDEO_EXT = {".mp4", ".m4v", ".webm"}


def make_preview(src: Path, dest: Path) -> bool:
    """Transcode to a small H.264/AAC MP4 that every browser can play."""
    tmp = dest.with_suffix(".tmp.mp4")
    cmd = [
        settings.ffmpeg_path, "-y", "-v", "error", "-i", str(src),
        "-vf", "scale='min(960,iw)':-2,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(tmp),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=1800, check=True)
    except (subprocess.SubprocessError, OSError):
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(dest)
    return True


def make_thumbnail(src: Path, dest: Path, kind: str, duration: float | None) -> bool:
    # Output-side seek (-ss after -i) is slower but reliable on files with odd keyframes;
    # exit code 0 can still mean "no frame written", so check the file and retry from 0.
    seeks = [min((duration or 0) / 2, 5), 0.0] if kind == "video" else [0.0]
    for seek in seeks:
        dest.unlink(missing_ok=True)
        cmd = [settings.ffmpeg_path, "-y", "-v", "error", "-i", str(src)]
        if seek:
            cmd += ["-ss", f"{seek:.2f}"]
        cmd += ["-frames:v", "1", "-vf", "scale=480:-2,format=yuvj420p", "-q:v", "4", str(dest)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120, check=True)
        except (subprocess.SubprocessError, OSError):
            continue
        if dest.exists():
            return True
    return False
