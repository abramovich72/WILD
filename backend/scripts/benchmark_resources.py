"""Measure local CPU and RAM while running the real SpeciesNet detection service."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import threading
import time
from pathlib import Path
from typing import Any

import psutil

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import db
from app.config import settings
from app.models.media import MediaItem
from app.services import detect


def _processor_name() -> str:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def _process_tree_sample(root: psutil.Process) -> tuple[float, int]:
    processes = [root]
    try:
        processes.extend(root.children(recursive=True))
    except psutil.Error:
        pass

    cpu_seconds = 0.0
    rss_bytes = 0
    for process in processes:
        try:
            cpu = process.cpu_times()
            cpu_seconds += cpu.user + cpu.system
            rss_bytes += process.memory_info().rss
        except psutil.Error:
            continue
    return cpu_seconds, rss_bytes


def _measure(workload: Any, interval: float) -> dict[str, Any]:
    process = psutil.Process()
    before_cpu, before_rss = _process_tree_sample(process)
    before_available = psutil.virtual_memory().available
    peak_rss = before_rss
    min_available = before_available
    finished = threading.Event()

    def sample() -> None:
        nonlocal peak_rss, min_available
        while not finished.wait(interval):
            _, rss = _process_tree_sample(process)
            peak_rss = max(peak_rss, rss)
            min_available = min(min_available, psutil.virtual_memory().available)

    sampler = threading.Thread(target=sample, name="resource-sampler", daemon=True)
    start = time.perf_counter()
    sampler.start()
    try:
        result = workload()
    finally:
        finished.set()
        sampler.join()
    elapsed = time.perf_counter() - start

    after_cpu, after_rss = _process_tree_sample(process)
    peak_rss = max(peak_rss, after_rss)
    min_available = min(min_available, psutil.virtual_memory().available)
    cpu_cores = max(0.0, after_cpu - before_cpu) / elapsed
    logical_cpus = psutil.cpu_count(logical=True) or 1
    return {
        "elapsed_seconds": round(elapsed, 2),
        "average_cpu_cores": round(cpu_cores, 2),
        "average_machine_cpu_percent": round(cpu_cores / logical_cpus * 100, 1),
        "process_tree_peak_rss_gb": round(peak_rss / 1024**3, 2),
        "process_tree_rss_increase_gb": round(max(0, peak_rss - before_rss) / 1024**3, 2),
        "system_available_ram_min_gb": round(min_available / 1024**3, 2),
        "detections": len(result),
    }


def _resolve_media(media_id: int) -> tuple[Path, MediaItem]:
    with db.Session(db.engine) as session:
        item = session.get(MediaItem, media_id)
        if item is None:
            raise ValueError(f"Media ID {media_id} was not found in the local database")
        path = settings.storage_dir / "projects" / str(item.project_id) / "media" / item.stored_name
        if not path.is_file():
            raise FileNotFoundError(f"Media file for ID {media_id} is missing: {path}")
        return path, item


def _run_media(path: Path, item: MediaItem) -> list[Any]:
    if item.kind == "image":
        return detect.analyze_image(path)
    if item.kind == "video":
        return detect.analyze_video(path, item.duration, lambda _progress: None)
    raise ValueError(f"Unsupported media kind for ID {item.id}: {item.kind}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--media-id",
        type=int,
        required=True,
        help="ID of an existing local image or video in storage/wild.db",
    )
    parser.add_argument("--repeats", type=int, default=3, help="Runs per media item (default: 3)")
    parser.add_argument("--interval", type=float, default=0.2, help="Sampling interval in seconds")
    parser.add_argument("--output", type=Path, help="Optional path for the JSON report")
    args = parser.parse_args()
    if args.repeats < 1 or args.interval <= 0:
        parser.error("--repeats and --interval must be positive")

    path, item = _resolve_media(args.media_id)
    runs = []
    for index in range(args.repeats):
        run = _measure(lambda: _run_media(path, item), args.interval)
        run["run"] = index + 1
        run["model_warm"] = index > 0
        runs.append(run)

    report = {
        "machine": {
            "processor": _processor_name(),
            "logical_cpus": psutil.cpu_count(logical=True),
            "physical_cpus": psutil.cpu_count(logical=False),
            "ram_total_gb": round(psutil.virtual_memory().total / 1024**3, 2),
        },
        "benchmark": {
            "media_id": item.id,
            "kind": item.kind,
            "size_mb": round(item.size_bytes / 1024**2, 2),
            "duration_seconds": item.duration,
            "sample_interval_seconds": args.interval,
            "runs": runs,
        },
    }
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
