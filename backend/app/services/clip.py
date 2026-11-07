"""Timeline planning (pure) and ffmpeg rendering of clips (MP4, 1280x720, 30fps, no audio yet)."""

import subprocess
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from .ffmpeg import try_remux_corrupt_avi

WIDTH, HEIGHT, FPS = 1280, 720, 30
MIN_PIECE = 1.0
MIN_RENDER_PIECE = 0.2
FADE_SECONDS = 0.4
NON_ANIMALS = {"human", "vehicle"}


@dataclass
class PlanMedia:
    id: int
    kind: str  # "video" | "image"
    duration: float | None


@dataclass
class PlanDet:
    media_id: int
    species: str
    label: str  # display name shown as caption
    confidence: float
    start: float | None
    end: float | None


@dataclass
class Piece:
    media_id: int
    start: float
    end: float
    label: str | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


def merge_spans(spans: list[tuple[float, float, float, str]]) -> list[tuple[float, float, str]]:
    """Merge overlapping (start, end, confidence, label) spans; the label of the most confident wins."""
    out: list[list] = []
    for s, e, conf, label in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
            if conf > out[-1][3]:
                out[-1][2], out[-1][3] = label, conf
        else:
            out.append([s, e, label, conf])
    return [(s, e, label) for s, e, label, _ in out]


def fit_to_length(pieces: Sequence[Piece], length: float) -> list[Piece]:
    """Shrink pieces proportionally to fit `length`; drop trailing ones if even the minimum is too long."""
    pieces = list(pieces)
    while pieces:
        total = sum(p.duration for p in pieces)
        if total <= length + 1e-6:
            return pieces
        f = length / total
        scaled = [
            Piece(p.media_id, p.start, p.start + max(min(p.duration, MIN_PIECE), p.duration * f), p.label)
            for p in pieces
        ]
        if sum(p.duration for p in scaled) <= length + 1e-6:
            return scaled
        pieces.pop()
    return pieces


def plan_timeline(
    media: Sequence[PlanMedia],
    detections: Sequence[PlanDet],
    *,
    length: float,
    animals_only: bool = False,
    image_seconds: float = 3.0,
    pad: float = 1.0,
) -> tuple[list[Piece], int]:
    """Build a timeline from media (in the given order). Returns (pieces, skipped media count)."""
    by_media: dict[int, list[PlanDet]] = defaultdict(list)
    for d in detections:
        if d.species not in NON_ANIMALS:
            by_media[d.media_id].append(d)

    pieces: list[Piece] = []
    skipped = 0
    for m in media:
        dets = by_media.get(m.id, [])
        top = max(dets, key=lambda d: d.confidence).label if dets else None
        if m.kind == "image":
            if animals_only and not dets:
                skipped += 1
                continue
            pieces.append(Piece(m.id, 0.0, image_seconds, top))
            continue
        if not m.duration:
            skipped += 1
            continue
        if not animals_only:
            pieces.append(Piece(m.id, 0.0, m.duration, top))
            continue
        spans = [
            (max(0.0, d.start - pad), min(m.duration, (d.end if d.end is not None else d.start) + pad),
             d.confidence, d.label)
            for d in dets
            if d.start is not None
        ]
        if not spans:
            skipped += 1
            continue
        pieces += [Piece(m.id, round(s, 2), round(e, 2), label) for s, e, label in merge_spans(spans)]
    return fit_to_length(pieces, length), skipped


@dataclass
class Segment:
    path: Path
    kind: str
    start: float
    end: float
    label: str | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


def _filter_path(p: str | Path) -> str:
    return str(p).replace("\\", "/").replace(":", r"\:")


def segment_filter(
    duration: float, *, caption_file: Path | None, fade: bool, trim_start: float | None = None
) -> str:
    chain = []
    if trim_start is not None:
        # Trim inside the graph and re-zero timestamps: fade/drawtext use stream time, which
        # would otherwise still be the position in the source file.
        chain += [f"trim=start={trim_start:.3f}:duration={duration:.3f}", "setpts=PTS-STARTPTS"]
    chain += [
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease",
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2",
        "setsar=1",
        f"fps={FPS}",
        "format=yuv420p",
    ]
    if caption_file is not None:
        chain.append(
            f"drawtext=fontfile='{_filter_path(settings.caption_font)}':textfile='{_filter_path(caption_file)}'"
            ":fontsize=44:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=14"
            ":x=(w-text_w)/2:y=h-text_h-48:text_shaping=1"
        )
    if fade:
        d = min(FADE_SECONDS, duration / 3)
        chain.append(f"fade=t=in:st=0:d={d:.2f},fade=t=out:st={duration - d:.2f}:d={d:.2f}")
    return ",".join(chain)


def segment_cmd(seg: Segment, out: Path, *, caption_file: Path | None, fade: bool) -> list[str]:
    cmd = [settings.ffmpeg_path, "-y", "-v", "error"]
    src_path = seg.path
    if seg.kind == "image":
        cmd += ["-loop", "1", "-framerate", str(FPS), "-i", str(src_path), "-t", f"{seg.duration:.3f}"]
    else:
        # Check if corrupt AVI and use fixed MKV if available
        if src_path.suffix.lower() == ".avi":
            fixed = src_path.with_suffix(".fixed.mkv")
            if not fixed.exists():
                fixed = try_remux_corrupt_avi(src_path)
            if fixed and fixed.exists():
                src_path = fixed
        # -t before -i stops reading right after the segment instead of decoding the whole file.
        cmd += ["-t", f"{seg.end + 1:.3f}", "-i", str(src_path)]
    cmd += [
        "-vf",
        segment_filter(
            seg.duration, caption_file=caption_file, fade=fade,
            trim_start=seg.start if seg.kind == "video" else None,
        ),
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-r", str(FPS), str(out),
    ]
    return cmd


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(
        cmd, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "ffmpeg failed").strip()[-400:])


def title_card_cmd(
    title_file: Path, duration: float, out: Path, *, fade: bool
) -> list[str]:
    if not settings.caption_font:
        raise RuntimeError("No font is configured for title cards")
    vf = (
        f"drawtext=fontfile='{_filter_path(settings.caption_font)}':"
        f"textfile='{_filter_path(title_file)}':expansion=none:fontsize=56:fontcolor=white:"
        "x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=12:text_shaping=1"
    )
    if fade:
        d = min(FADE_SECONDS, duration / 3)
        vf += f",fade=t=in:st=0:d={d:.2f},fade=t=out:st={duration - d:.2f}:d={d:.2f}"
    vf += ",format=yuv420p"
    return [
        settings.ffmpeg_path, "-y", "-v", "error", "-f", "lavfi", "-i",
        f"color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration:.3f}",
        "-vf", vf, "-t", f"{duration:.3f}", "-an", "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-r", str(FPS), str(out),
    ]


def render(
    segments: Sequence[Segment],
    out: Path,
    tmp: Path,
    *,
    captions: bool,
    transition: str,
    opening_title: str = "",
    opening_title_seconds: float = 3.0,
    closing_title: str = "",
    closing_title_seconds: float = 3.0,
    on_progress: Callable[[float], None] = lambda _f: None,
) -> None:
    if not segments:
        raise ValueError("empty timeline")
    opening_title = opening_title.strip()
    closing_title = closing_title.strip()
    if opening_title and not 1 <= opening_title_seconds <= 60:
        raise ValueError("opening title duration must be between 1 and 60 seconds")
    if closing_title and not 1 <= closing_title_seconds <= 60:
        raise ValueError("closing title duration must be between 1 and 60 seconds")
    tmp.mkdir(parents=True, exist_ok=True)
    total = sum(s.duration for s in segments)
    total += opening_title_seconds if opening_title else 0
    total += closing_title_seconds if closing_title else 0
    done = 0.0
    parts: list[Path] = []

    def add_title(title: str, seconds: float, name: str) -> None:
        nonlocal done
        title_file = tmp / f"{name}.txt"
        title_file.write_text(title, encoding="utf-8")
        part = tmp / f"{name}.mp4"
        _run(title_card_cmd(title_file, seconds, part, fade=transition == "fade"))
        if not part.exists() or part.stat().st_size == 0:
            raise RuntimeError(f"{name} title produced no output")
        parts.append(part)
        done += seconds
        on_progress(min(done / total, 0.98))

    if opening_title:
        add_title(opening_title, opening_title_seconds, "opening-title")

    for i, seg in enumerate(segments):
        caption_file = None
        if captions and seg.label and settings.caption_font:
            caption_file = tmp / f"cap{i}.txt"
            caption_file.write_text(seg.label, encoding="utf-8")
        part = tmp / f"seg{i}.mp4"
        _run(segment_cmd(seg, part, caption_file=caption_file, fade=transition == "fade"))
        if not part.exists() or part.stat().st_size == 0:
            raise RuntimeError(f"segment {i + 1} produced no output")
        parts.append(part)
        done += seg.duration
        on_progress(min(done / total, 0.98))

    if closing_title:
        add_title(closing_title, closing_title_seconds, "closing-title")

    listing = tmp / "list.txt"
    listing.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([
        settings.ffmpeg_path, "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(out),
    ])
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError("render produced no output")
