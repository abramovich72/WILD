import math
import os
import threading
import wave
from pathlib import Path

from ..config import settings

MODEL_ID = "facebook/musicgen-small"
MAX_GENERATED_SECONDS = 30
TOKENS_PER_SECOND = 50
STYLE_PROMPTS = {
    "electronic": "electronic",
    "acoustic": "acoustic",
    "ambient": "ambient",
}

_model_lock = threading.Lock()
_generation_lock = threading.Lock()
_loaded: tuple[object, object, object] | None = None


def _load_model():
    global _loaded
    with _model_lock:
        if _loaded is not None:
            return _loaded

        try:
            import torch
            from transformers import AutoProcessor, MusicgenForConditionalGeneration
        except ImportError as exc:
            raise RuntimeError(
                "Music generation dependencies are missing; install backend/requirements-ml.txt"
            ) from exc

        torch.set_num_threads(min(4, os.cpu_count() or 1))
        cache_dir = settings.storage_dir / "models" / "musicgen"
        cache_dir.mkdir(parents=True, exist_ok=True)
        processor = AutoProcessor.from_pretrained(MODEL_ID, cache_dir=cache_dir)
        model = MusicgenForConditionalGeneration.from_pretrained(
            MODEL_ID, cache_dir=cache_dir
        ).to("cpu")
        model.eval()
        _loaded = (torch, processor, model)
        return _loaded


def generate_music(
    output: Path, *, duration: float, prompt: str, style: str
) -> None:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Music duration must be positive")
    if not prompt.strip():
        raise ValueError("Music description cannot be empty")
    if style not in STYLE_PROMPTS:
        raise ValueError("Unsupported music style")

    torch, processor, model = _load_model()
    generation_duration = min(duration, MAX_GENERATED_SECONDS)
    max_new_tokens = max(1, math.ceil(generation_duration * TOKENS_PER_SECOND))
    description = (
        f"{prompt.strip()}, {STYLE_PROMPTS[style]} instrumental soundtrack, no vocals"
    )

    with _generation_lock, torch.inference_mode():
        inputs = processor(text=[description], padding=True, return_tensors="pt")
        generated = model.generate(
            **inputs,
            do_sample=True,
            guidance_scale=3.0,
            max_new_tokens=max_new_tokens,
        )

    audio = generated[0].detach().cpu().clamp(-1, 1).numpy()
    if audio.ndim == 1:
        audio = audio[None, :]
    if audio.ndim != 2 or audio.shape[0] not in (1, 2):
        raise RuntimeError("MusicGen returned audio with an unsupported channel layout")

    pcm = (audio.T * 32767).astype("<i2")
    sample_rate = int(model.config.audio_encoder.sampling_rate)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(audio.shape[0])
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
