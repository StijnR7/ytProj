"""Turns a project (script + audio + images) into the final MP4."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image

from ..config import load_config, resolve
from ..project import Project
from ..tts import SR, ffmpeg_exe
from .audio import build_mix, mouth_envelope
from .common import ORANGE, ease_in_out_sine
from .scenes import SceneContext, make_scene

RENDER_VERSION = "1"


def scene_image(project: Project, idx: int) -> Image.Image | None:
    for ext in ("png", "jpg"):
        p = project.path("images", f"scene_{idx:03d}.{ext}")
        if p.exists():
            return Image.open(p).convert("RGB")
    return None


def build_context(project: Project, scenes: list[dict], timeline: dict, idx: int) -> SceneContext:
    cfg = load_config()
    v = cfg["video"]
    fps = v["fps"]
    tl = timeline["scenes"][idx]
    frames = tl["frames"]
    env = None
    wav = project.path("audio", f"scene_{idx:03d}.wav")
    if wav.exists():
        a, sr = sf.read(str(wav), dtype="float32")
        env = mouth_envelope(a, sr, fps, frames)
    return SceneContext(
        size=(v["width"], v["height"]), fps=fps, duration=frames / fps, theme=project.theme, seed=idx * 7 + 3,
        image=scene_image(project, idx), envelope=env, sentences=tl.get("sentences", []),
        chapter_number=scenes[idx]["chapter_index"] + 1, is_last=idx == len(scenes) - 1,
        channel_name=cfg["channel"]["name"], burn_captions=bool(v.get("burn_captions")),
    )


def scene_hash(project: Project, scenes: list[dict], timeline: dict, idx: int) -> str:
    cfg = load_config()
    parts = [RENDER_VERSION, json.dumps(cfg["video"], sort_keys=True), project.theme]
    for j in (idx - 1, idx):
        if j < 0:
            continue
        parts.append(json.dumps({k: scenes[j].get(k) for k in ("visual", "mascot", "on_screen_text")}, sort_keys=True))
        parts.append(str(timeline["scenes"][j]["frames"]))
        for ext in ("png", "jpg"):
            p = project.path("images", f"scene_{j:03d}.{ext}")
            if p.exists():
                parts.append(f"{p.stat().st_mtime_ns}")
        w = project.path("audio", f"scene_{j:03d}.wav")
        if w.exists():
            parts.append(f"{w.stat().st_mtime_ns}")
    parts.append(str(idx == len(scenes) - 1))
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _wipe(prev: Image.Image, cur: Image.Image, p: float) -> Image.Image:
    """Brand-coloured panel sweeps across: prev -> panel -> new."""
    W, H = cur.size
    band = int(W * 0.5)
    x0 = int(-band + p * (W + band))  # panel left edge
    out = prev.copy()
    if x0 > 0:
        out.paste(cur.crop((0, 0, min(W, x0), H)), (0, 0))
    l, r = max(0, x0), min(W, x0 + band)
    if r > l:
        out.paste(ORANGE, (l, 0, r, H))
    return out


def render_scene(slug: str, idx: int, out_path: str, preview: bool = False) -> str:
    """Render one scene to an MP4 (worker process entry point)."""
    project = Project(slug)
    scenes = project.scenes()
    timeline = project.read_json("timeline.json")
    ctx = build_context(project, scenes, timeline, idx)
    scene = make_scene(scenes[idx], ctx)
    v = load_config()["video"]
    fps = v["fps"]
    frames = timeline["scenes"][idx]["frames"]

    if preview:
        scene.frame(min(ctx.duration * 0.6, ctx.duration - 0.05)).resize((640, 360), Image.LANCZOS).save(out_path, quality=85)
        return out_path

    prev_last = None
    kind = scenes[idx]["visual"]["type"]
    if idx > 0:
        pctx = build_context(project, scenes, timeline, idx - 1)
        prev_last = make_scene(scenes[idx - 1], pctx).frame(pctx.duration - 1 / fps)
    trans = 0.5 if kind == "title" else 0.3

    tmp = out_path + ".part.mp4"
    cmd = [
        ffmpeg_exe(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{v['width']}x{v['height']}",
        "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", v["preset"], "-crf", str(v["crf"]),
        "-pix_fmt", "yuv420p", "-r", str(fps), "-video_track_timescale", str(fps * 1000), tmp,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(frames):
            t = i / fps
            f = scene.frame(t)
            if prev_last is not None and t < trans:
                p = t / trans
                f = _wipe(prev_last, f, p) if kind == "title" else Image.blend(prev_last, f, ease_in_out_sine(p))
            proc.stdin.write(f.tobytes())
    finally:
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed rendering scene {idx}")
    os.replace(tmp, out_path)
    return out_path


def _workers() -> int:
    w = int(load_config()["video"].get("workers") or 0)
    return w if w > 0 else max(1, (os.cpu_count() or 2) // 2)


def render_storyboard(project: Project, log=print) -> None:
    scenes = project.scenes()
    out_dir = project.path("storyboard")
    out_dir.mkdir(exist_ok=True)
    jobs = []
    with ProcessPoolExecutor(_workers()) as ex:
        for i in range(len(scenes)):
            jobs.append(ex.submit(render_scene, project.slug, i, str(out_dir / f"scene_{i:03d}.jpg"), True))
        for k, fut in enumerate(as_completed(jobs)):
            fut.result()
    log(f"  storyboard: {len(scenes)} preview frames")


def render_video(project: Project, log=print) -> Path:
    cfg = load_config()
    scenes = project.scenes()
    timeline = project.read_json("timeline.json")
    sdir = project.path("render", "scenes")
    sdir.mkdir(parents=True, exist_ok=True)

    todo = []
    for i in range(len(scenes)):
        h = scene_hash(project, scenes, timeline, i)
        out = sdir / f"scene_{i:03d}_{h}.mp4"
        if not out.exists():
            for old in sdir.glob(f"scene_{i:03d}_*.mp4"):
                old.unlink()
            todo.append((i, out))
    log(f"  rendering {len(todo)} of {len(scenes)} scenes with {_workers()} workers (others cached)")
    if todo:
        with ProcessPoolExecutor(_workers()) as ex:
            futs = {ex.submit(render_scene, project.slug, i, str(out)): i for i, out in todo}
            for k, fut in enumerate(as_completed(futs), 1):
                fut.result()
                if k % 5 == 0 or k == len(todo):
                    log(f"    {k}/{len(todo)} scenes done")

    files = [next(sdir.glob(f"scene_{i:03d}_*.mp4")) for i in range(len(scenes))]
    lst = project.path("render", "concat.txt")
    lst.write_text("".join(f"file '{f.resolve().as_posix()}'\n" for f in files), encoding="utf-8")

    # ---- audio
    total = timeline["total_seconds"]
    narr = np.zeros(int(total * SR) + SR, dtype=np.float32)
    sfx = []
    for i, tl in enumerate(timeline["scenes"]):
        a, sr = sf.read(str(project.path("audio", f"scene_{i:03d}.wav")), dtype="float32")
        st = int((tl["start"] + tl["voice_offset"]) * SR)
        narr[st: st + len(a)] += a[: len(narr) - st]
        kind = scenes[i]["visual"]["type"]
        if kind == "title":
            sfx.append((tl["start"], "whoosh"))
        elif kind in ("stat", "mascot") and i > 0:
            sfx.append((tl["start"] + 0.35, "pop"))
    mix = project.path("render", "mix.wav")
    build_mix(narr, SR, sfx, total, resolve(cfg["music"]["folder"]), project.theme, float(cfg["music"]["volume_db"]), len(scenes), mix)

    out_dir = project.path("output")
    out_dir.mkdir(exist_ok=True)
    final = out_dir / "video.mp4"
    log("  muxing + loudness normalising (-14 LUFS, YouTube standard)")
    subprocess.run([
        ffmpeg_exe(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(mix),
        "-map", "0:v", "-map", "1:a", "-c:v", "copy",
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-shortest", str(final),
    ], check=True)
    return final
