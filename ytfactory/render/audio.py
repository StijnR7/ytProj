"""Audio: mouth-sync envelopes, procedural music + sfx, and the final mix."""
from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import soundfile as sf

from ..tts import decode_audio

MIX_SR = 48000


def mouth_envelope(samples: np.ndarray, sr: int, fps: int, n_frames: int) -> np.ndarray:
    """Per-video-frame mouth level 0..4 from voice loudness."""
    hop = sr / fps
    levels = np.zeros(n_frames, dtype=np.int8)
    if len(samples) == 0:
        return levels
    rms = np.array([
        np.sqrt(np.mean(samples[int(i * hop): int((i + 1) * hop)] ** 2)) if int(i * hop) < len(samples) else 0.0
        for i in range(n_frames)
    ])
    ref = np.percentile(rms[rms > 0], 90) if np.any(rms > 0) else 1.0
    norm = np.clip(rms / max(ref, 1e-6), 0, 1)
    sm = np.convolve(norm, [0.25, 0.5, 0.25], mode="same")
    levels[:] = np.clip(np.round(sm * 4.4 - 0.4), 0, 4).astype(np.int8)
    return levels


# ------------------------------------------------------------------ procedural music
NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
PROGRESSIONS = {
    "space": [("A", "m"), ("F", ""), ("C", ""), ("G", "")],
    "history": [("D", "m"), ("A#", ""), ("F", ""), ("C", "")],
    "animals": [("C", ""), ("G", ""), ("A", "m"), ("F", "")],
    "hypotheticals": [("E", "m"), ("C", ""), ("G", ""), ("D", "")],
    "brand": [("F", ""), ("C", ""), ("D", "m"), ("A#", "")],
}


def _freq(semitone_from_a4: float) -> float:
    return 440.0 * 2 ** (semitone_from_a4 / 12)


def ambient_music(duration: float, mood: str = "brand", seed: int = 0, sr: int = MIX_SR) -> np.ndarray:
    """Soft evolving pad + gentle plucks. Royalty free because Zib wrote it."""
    rng = random.Random(seed)
    prog = PROGRESSIONS.get(mood, PROGRESSIONS["brand"])
    chord_len = 8.0
    n = int(duration * sr) + sr
    out = np.zeros(n, dtype=np.float32)
    seg_n = int(chord_len * sr)
    fade = int(2.0 * sr)
    t = np.arange(seg_n + fade) / sr
    env = np.ones_like(t)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    k = 0
    pos = 0
    while pos < n:
        root, quality = prog[k % len(prog)]
        r = NOTE[root] - 9 - 12  # relative to A4, one octave down
        third = 3 if quality == "m" else 4
        notes = [r, r + third + 12, r + 7, r + 12, r + 19]
        seg = np.zeros_like(t)
        for i, s in enumerate(notes):
            f = _freq(s)
            for det in (-0.12, 0.12):
                ff = f * 2 ** (det / 12)
                ph = rng.uniform(0, 6.28)
                seg += 0.5 * np.sin(2 * np.pi * ff * t + ph) + 0.12 * np.sin(4 * np.pi * ff * t + ph)
        seg += 0.9 * np.sin(2 * np.pi * _freq(r - 12) * t)  # bass
        seg *= 0.5 + 0.1 * np.sin(2 * np.pi * 0.11 * t)
        # plucks
        for j in range(4):
            if rng.random() < 0.7:
                st = int((j * 2.0 + rng.uniform(0, 0.4)) * sr)
                pn = rng.choice(notes) + 24
                pl_t = np.arange(int(1.6 * sr)) / sr
                pl = 0.6 * np.sin(2 * np.pi * _freq(pn) * pl_t) * np.exp(-pl_t * 3.2)
                e = min(len(seg), st + len(pl))
                seg[st:e] += pl[: e - st]
        seg *= env
        e = min(n, pos + len(seg))
        out[pos:e] += seg[: e - pos].astype(np.float32)
        pos += seg_n
        k += 1
    # cheap echo for space
    for delay, g in ((0.37, 0.35), (0.74, 0.18)):
        d = int(delay * sr)
        out[d:] += g * out[:-d]
    out /= max(1e-6, np.max(np.abs(out)))
    return out[: int(duration * sr)] * 0.5


def load_music(folder: Path, duration: float, mood: str, seed: int) -> np.ndarray:
    files = sorted([p for p in folder.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a", ".flac")]) if folder.exists() else []
    if not files:
        return ambient_music(duration, mood, seed)
    rng = random.Random(seed)
    rng.shuffle(files)
    parts, total, i = [], 0, 0
    xf = int(3 * MIX_SR)
    while total < duration * MIX_SR + MIX_SR:
        a = decode_audio(files[i % len(files)], MIX_SR)
        a /= max(1e-6, np.max(np.abs(a)))
        if parts and len(a) > xf and len(parts[-1]) > xf:
            ramp = np.linspace(0, 1, xf, dtype=np.float32)
            parts[-1][-xf:] = parts[-1][-xf:] * (1 - ramp) + a[:xf] * ramp
            a = a[xf:]
        parts.append(a)
        total += len(a)
        i += 1
    return np.concatenate(parts)[: int(duration * MIX_SR)] * 0.5


# ------------------------------------------------------------------ sfx
def whoosh(sr: int = MIX_SR) -> np.ndarray:
    n = int(0.7 * sr)
    noise = np.random.default_rng(1).normal(0, 1, n)
    k = np.ones(24) / 24
    noise = np.convolve(noise, k, mode="same")
    t = np.linspace(0, 1, n)
    env = np.sin(np.pi * t) ** 2 * np.exp(-t * 1.5)
    return (noise * env * 0.5).astype(np.float32)


def pop(sr: int = MIX_SR) -> np.ndarray:
    n = int(0.12 * sr)
    t = np.arange(n) / sr
    f = np.linspace(900, 300, n)
    return (0.4 * np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 40)).astype(np.float32)


def impact(sr: int = MIX_SR) -> np.ndarray:
    n = int(0.35 * sr)
    t = np.arange(n) / sr
    f = np.linspace(120, 45, n)
    thump = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 9)
    noise = np.random.default_rng(3).normal(0, 1, n) * np.exp(-t * 30) * 0.3
    return (0.7 * thump + noise).astype(np.float32)


def upsample(a: np.ndarray, src: int, dst: int = MIX_SR) -> np.ndarray:
    if src == dst:
        return a
    n = int(len(a) * dst / src)
    return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)


def build_mix(narration: np.ndarray, narr_sr: int, sfx_events: list[tuple[float, str]], duration: float,
              music_folder: Path, mood: str, music_db: float, seed: int, out: Path) -> None:
    n = int(duration * MIX_SR)
    voice = np.zeros(n, dtype=np.float32)
    v = upsample(narration, narr_sr)[:n]
    voice[: len(v)] = v
    # duck music under the voice
    win = int(0.25 * MIX_SR)
    active = np.convolve(np.abs(voice) > 0.02, np.ones(win) / win, mode="same")
    active = np.clip(active * 3, 0, 1)
    duck = 1 - 0.55 * np.convolve(active, np.ones(win) / win, mode="same")
    music = load_music(music_folder, duration, mood, seed)
    m = np.zeros(n, dtype=np.float32)
    m[: len(music)] = music[:n]
    gain = 10 ** (music_db / 20) * 2.2
    # fade music in/out
    f = int(2 * MIX_SR)
    m[:f] *= np.linspace(0, 1, f)
    m[-f:] *= np.linspace(1, 0, f)
    mix = voice + m * duck.astype(np.float32) * gain
    sounds = {"whoosh": whoosh() * 0.45, "pop": pop() * 0.35, "impact": impact() * 0.5}
    for t, kind in sfx_events:
        s = sounds.get(kind)
        st = int(t * MIX_SR)
        if s is None or st >= n:
            continue
        e = min(n, st + len(s))
        mix[st:e] += s[: e - st]
    peak = np.max(np.abs(mix))
    if peak > 0.98:
        mix *= 0.98 / peak
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), mix, MIX_SR, subtype="PCM_16")
