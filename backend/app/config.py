import shutil
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _find(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    winget = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    if winget.exists():
        for p in winget.rglob(f"{name}.exe"):
            return str(p)
    return name


def _find_font() -> str:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    return next((c for c in candidates if Path(c).exists()), "")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    storage_dir: Path = BACKEND_DIR.parent / "storage"
    device: str = "cpu"
    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    mkvmerge_path: str = ""
    max_upload_bytes: int = 50_000_000
    max_storage_bytes: int = 0
    upload_ttl_seconds: int = 0

    detect_country: str = "ISR"
    detect_fps: float = 1.0
    detect_min_conf: float = 0.2
    detect_batch_size: int = 8
    # Frames that barely differ from the last analysed frame are skipped, but never for
    # longer than detect_max_skip_seconds so a stationary animal is still sampled.
    detect_motion_threshold: float = 2.0
    detect_max_skip_seconds: float = 4.0
    detect_merge_gap_seconds: float = 5.0

    # Google Drive import (OAuth web client; see IMPLEMENTATION_PLAN stage 6).
    drive_enabled: bool = True
    google_client_id: str = ""
    google_client_secret: str = ""
    drive_redirect_uri: str = "http://localhost:8010/api/drive/callback"
    frontend_url: str = "http://localhost:5180/"
    # Load SpeciesNet in a background thread at startup so the first detection is fast.
    preload_model: bool = True

    # Clip rendering. caption_font defaults to a system font with Hebrew glyphs.
    caption_font: str = ""
    max_clip_seconds: float = 600.0
    image_seconds: float = 3.0
    animal_pad_seconds: float = 1.0

    def model_post_init(self, _ctx) -> None:
        self.storage_dir = Path(self.storage_dir).resolve()
        self.ffmpeg_path = self.ffmpeg_path or _find("ffmpeg")
        self.ffprobe_path = self.ffprobe_path or _find("ffprobe")
        self.mkvmerge_path = self.mkvmerge_path or _find("mkvmerge")
        self.caption_font = self.caption_font or _find_font()


settings = Settings()
