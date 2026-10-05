"""Text-to-speech engines. All free: Kokoro runs locally, Edge uses Microsoft's free voices."""
from __future__ import annotations

import asyncio
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np

from .config import MODELS, load_config

SR = 24000
KOKORO_MODEL = MODELS / "kokoro" / "kokoro-v1.0.int8.onnx"
KOKORO_VOICES = MODELS / "kokoro" / "voices-v1.0.bin"

_ABBR = r"(?:Mr|Mrs|Ms|Dr|St|Jr|Sr|vs|etc|e\.g|i\.e|Mt|No)\."


def split_sentences(text: str) -> list[str]:
    protected = re.sub(_ABBR, lambda m: m.group(0).replace(".", "<DOT>"), text)
    parts = re.split(r"(?<=[.!?])[\"')\]]?\s+(?=[\"'(\[]?[A-Z0-9])", protected)
    out = [p.replace("<DOT>", ".").strip() for p in parts if p.strip()]
    # merge very short fragments into their neighbour
    merged: list[str] = []
    for s in out:
        if merged and len(s.split()) < 3:
            merged[-1] += " " + s
        else:
            merged.append(s)
    return merged or [text]


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def decode_audio(path: Path, sr: int = SR) -> np.ndarray:
    """Decode any audio file to mono float32 at `sr` using ffmpeg."""
    proc = subprocess.run(
        [ffmpeg_exe(), "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


class TTS:
    def synth(self, text: str) -> np.ndarray:  # float32 mono @ SR
        raise NotImplementedError


class KokoroTTS(TTS):
    def __init__(self, voice: str, speed: float):
        if not KOKORO_MODEL.exists():
            raise RuntimeError(f"Kokoro model missing at {KOKORO_MODEL}. Run setup (python -m ytfactory setup).")
        from kokoro_onnx import Kokoro

        self.k = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
        self.voice, self.speed = voice, speed

    def synth(self, text: str) -> np.ndarray:
        samples, sr = self.k.create(text, voice=self.voice, speed=self.speed, lang="en-us")
        samples = np.asarray(samples, dtype=np.float32)
        if sr != SR:
            idx = np.linspace(0, len(samples) - 1, int(len(samples) * SR / sr))
            samples = np.interp(idx, np.arange(len(samples)), samples).astype(np.float32)
        return samples


class EdgeTTS(TTS):
    def __init__(self, voice: str, speed: float):
        import edge_tts  # noqa: F401

        self.voice = voice
        pct = int(round((speed - 1.0) * 100))
        self.rate = f"{pct:+d}%"

    def synth(self, text: str) -> np.ndarray:
        import edge_tts

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "a.mp3"

            async def run():
                await edge_tts.Communicate(text, self.voice, rate=self.rate).save(str(out))

            asyncio.run(run())
            return decode_audio(out)


class DummyTTS(TTS):
    """Silent-ish placeholder audio (soft hum) - for testing the pipeline without a voice model."""

    def synth(self, text: str) -> np.ndarray:
        n = int(SR * max(0.8, len(text.split()) * 0.38))
        t = np.arange(n) / SR
        env = 0.5 + 0.5 * np.sin(2 * np.pi * 3.1 * t) ** 2
        return (0.05 * np.sin(2 * np.pi * 180 * t) * env).astype(np.float32)


@lru_cache(maxsize=1)
def get_tts() -> TTS:
    v = load_config()["voice"]
    eng = v["engine"].lower()
    if eng == "kokoro":
        return KokoroTTS(v["kokoro_voice"], float(v["speed"]))
    if eng == "edge":
        return EdgeTTS(v["edge_voice"], float(v["speed"]))
    return DummyTTS()


def synth_scene(text: str, gap: float = 0.12) -> tuple[np.ndarray, list[dict]]:
    """Synthesise sentence by sentence so we get exact caption timings."""
    tts = get_tts()
    chunks, sentences, t = [], [], 0.0
    silence = np.zeros(int(SR * gap), dtype=np.float32)
    for sent in split_sentences(text):
        audio = tts.synth(sent)
        # trim leading/trailing near-silence
        nz = np.where(np.abs(audio) > 0.01)[0]
        if len(nz):
            audio = audio[max(0, nz[0] - 240) : nz[-1] + 1200]
        dur = len(audio) / SR
        sentences.append({"text": sent, "start": round(t, 3), "end": round(t + dur, 3)})
        chunks += [audio, silence]
        t += dur + gap
    audio = np.concatenate(chunks[:-1]) if chunks else np.zeros(SR, dtype=np.float32)
    return audio, sentences
