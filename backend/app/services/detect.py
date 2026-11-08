"""Animal detection: frame sampling, SpeciesNet inference and event merging."""

import logging
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from .ffmpeg import try_remux_corrupt_avi

log = logging.getLogger("uvicorn.error")

_SKIP_LABELS = {"blank", "no cv result", "empty"}


@dataclass
class FrameDet:
    species: str
    conf: float
    box: tuple[float, float, float, float] | None


@dataclass
class Event:
    species: str
    conf: float
    start: float | None
    end: float | None
    box: tuple[float, float, float, float] | None


# ---------- pure logic (unit-tested without the model) ----------


def common_name(taxon: str) -> str:
    """'uuid;class;order;family;genus;species;common' -> common name (or last latin rank)."""
    parts = taxon.split(";")
    if len(parts) >= 7 and parts[6]:
        return parts[6]
    latin = [p for p in parts[1:6] if p]
    return latin[-1] if latin else "animal"


def parse_prediction(pred: dict, min_conf: float) -> list[FrameDet]:
    if pred.get("failures"):
        return []
    out: list[FrameDet] = []
    for d in pred.get("detections", []):
        conf = float(d.get("conf", 0))
        if conf < min_conf:
            continue
        box = tuple(d["bbox"]) if d.get("bbox") else None
        cat = str(d.get("category"))
        if cat == "2":
            out.append(FrameDet("human", conf, box))
        elif cat == "3":
            out.append(FrameDet("vehicle", conf, box))
        else:
            pc = d.get("processed_classification")
            if pc:
                name = common_name(pc["class"])
                if name.lower() in _SKIP_LABELS:
                    continue
                out.append(FrameDet(name, float(pc.get("score", conf)), box))
            else:
                out.append(FrameDet("animal", conf, box))
    return out


def merge_events(
    frames: list[tuple[float, list[FrameDet]]], gap: float, step: float, duration: float | None
) -> list[Event]:
    """Join same-species detections on consecutive sampled frames into one event."""
    by_species: dict[str, list[tuple[float, FrameDet]]] = {}
    for t, dets in sorted(frames, key=lambda f: f[0]):
        for d in dets:
            by_species.setdefault(d.species, []).append((t, d))
    events: list[Event] = []
    for species, items in by_species.items():
        group: list[tuple[float, FrameDet]] = []
        for item in items + [None]:  # type: ignore[list-item]
            if group and (item is None or item[0] - group[-1][0] > gap):
                best = max(group, key=lambda g: g[1].conf)[1]
                end = group[-1][0] + step
                if duration:
                    end = min(end, duration)
                events.append(Event(species, best.conf, group[0][0], end, best.box))
                group = []
            if item is not None:
                group.append(item)
    return sorted(events, key=lambda e: (e.start or 0, e.species))


def image_events(dets: list[FrameDet]) -> list[Event]:
    return [Event(d.species, d.conf, None, None, d.box) for d in dets]


def select_frames(
    frames: list[tuple[float, Path]],
    diff_fn: Callable[[Path, Path], float],
    threshold: float,
    max_skip: float,
) -> list[tuple[float, Path]]:
    """Drop frames with (almost) no change since the last kept frame."""
    kept: list[tuple[float, Path]] = []
    for t, path in frames:
        if not kept:
            kept.append((t, path))
            continue
        last_t, last_path = kept[-1]
        if t - last_t >= max_skip or diff_fn(last_path, path) >= threshold:
            kept.append((t, path))
    return kept


def events_overlap(a: Event, b: Event) -> bool:
    if a.start is not None and b.start is not None:
        return a.start < (b.end or b.start) and b.start < (a.end or a.start)
    if a.box and b.box:
        ax, ay, aw, ah = a.box
        bx, by, bw, bh = b.box
        iw = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
        ih = max(0.0, min(ay + ah, by + bh) - max(ay, by))
        inter = iw * ih
        union = aw * ah + bw * bh - inter
        return union > 0 and inter / union > 0.3
    return False


# ---------- ffmpeg / image helpers ----------


def frame_diff(a: Path, b: Path) -> float:
    import numpy as np
    from PIL import Image

    def load(p: Path):
        with Image.open(p) as im:
            return np.asarray(im.convert("L").resize((64, 36)), dtype="float32")

    return float(np.abs(load(a) - load(b)).mean())


def extract_frames(video: Path, out_dir: Path, fps: float) -> list[tuple[float, Path]]:
    pattern = out_dir / "f_%05d.jpg"
    target = video
    cmd = [
        settings.ffmpeg_path, "-y", "-v", "error", "-i", str(target),
        "-vf", f"fps={fps},scale='min(1280,iw)':-2,format=yuvj420p",
        "-q:v", "3", str(pattern),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=600, check=True)
    except (subprocess.SubprocessError, OSError):
        fixed = try_remux_corrupt_avi(video)
        if fixed:
            fallback_cmd = [
                settings.ffmpeg_path, "-y", "-v", "error", "-i", str(fixed),
                "-vf", f"fps={fps},scale='min(1280,iw)':-2,format=yuvj420p",
                "-q:v", "3", str(pattern),
            ]
            subprocess.run(fallback_cmd, capture_output=True, timeout=600, check=True)
        else:
            raise
    files = sorted(out_dir.glob("f_*.jpg"))
    return [(i / fps, p) for i, p in enumerate(files)]


# ---------- SpeciesNet ----------

_model = None
_model_lock = threading.Lock()
_predict_lock = threading.Lock()


def _get_model():
    global _model
    with _model_lock:
        if _model is None:
            from speciesnet import DEFAULT_MODEL, SpeciesNet

            _model = SpeciesNet(DEFAULT_MODEL)
        return _model


def preload_model() -> None:
    def run():
        try:
            _get_model()
            log.info("SpeciesNet model preloaded")
        except Exception:
            log.exception("SpeciesNet preload failed; it will load on first detection")

    threading.Thread(target=run, name="model-preload", daemon=True).start()


def classify(paths: list[Path]) -> list[dict]:
    """Run SpeciesNet on image files; returns one prediction dict per path, in order."""
    model = _get_model()
    with _predict_lock:
        res = model.predict(
            filepaths=[str(p) for p in paths],
            country=settings.detect_country,
            run_mode="single_thread",
            batch_size=settings.detect_batch_size,
        )
    by_path = {Path(p["filepath"]).name: p for p in res["predictions"]}
    return [by_path.get(p.name, {"failures": ["missing"]}) for p in paths]


def analyze_image(
    path: Path, classify_fn: Callable[[list[Path]], list[dict]] | None = None
) -> list[Event]:
    classify_fn = classify_fn or classify
    pred = classify_fn([path])[0]
    detections = parse_prediction(pred, settings.detect_min_conf)
    if not detections:
        return []
    return image_events([max(detections, key=lambda detection: detection.conf)])


def analyze_video(
    path: Path,
    duration: float | None,
    on_progress: Callable[[float], None],
    classify_fn: Callable[[list[Path]], list[dict]] | None = None,
) -> list[Event]:
    classify_fn = classify_fn or classify
    with tempfile.TemporaryDirectory(prefix="wild_frames_") as tmp:
        frames = extract_frames(path, Path(tmp), settings.detect_fps)
        frames = select_frames(
            frames, frame_diff, settings.detect_motion_threshold, settings.detect_max_skip_seconds
        )
        results: list[tuple[float, list[FrameDet]]] = []
        n = settings.detect_batch_size
        for i in range(0, len(frames), n):
            chunk = frames[i : i + n]
            preds = classify_fn([p for _, p in chunk])
            for (t, _), pred in zip(chunk, preds, strict=True):
                results.append((t, parse_prediction(pred, settings.detect_min_conf)))
            on_progress(min(1.0, (i + len(chunk)) / max(1, len(frames))))
    return merge_events(
        results, settings.detect_merge_gap_seconds, 1.0 / settings.detect_fps, duration
    )
