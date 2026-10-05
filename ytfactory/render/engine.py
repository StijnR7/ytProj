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

RENDER_VERSION = "4"

_IMG_CACHE: dict = {}


def _load(path: Path | None) -> Image.Image | None:
    if path is None:
        return None
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _IMG_CACHE:
        if len(_IMG_CACHE) > 24:
            _IMG_CACHE.clear()
        _IMG_CACHE[key] = Image.open(path).convert("RGB")
    return _IMG_CACHE[key]


def shot_image(project: Project, scene: int, shot: int, side: str = "") -> Path | None:
    for ext in ("png", "jpg"):
        p = project.path("images", f"s{scene:03d}_{shot:02d}{side}.{ext}")
        if p.exists():
            return p
    if not side and shot == 0:  # projects made before shots existed
        for ext in ("png", "jpg"):
            p = project.path("images", f"scene_{scene:03d}.{ext}")
            if p.exists():
                return p
    return None


def previous_image(project: Project, scenes: list[dict], scene: int, shot: int) -> Path | None:
    """Most recent image at or before (scene, shot) - used by closeups and kinetic backgrounds."""
    i, j = scene, shot
    while i >= 0:
        while j >= 0:
            if scenes[i]["shots"][j]["visual"]["type"] in ("broll", "illustration", "archive", "split"):
                p = shot_image(project, i, j) or shot_image(project, i, j, "a")
                if p:
                    return p
            j -= 1
        i -= 1
        if i >= 0:
            j = len(scenes[i]["shots"]) - 1
    return None


def shot_images(project: Project, scenes: list[dict], idx: int) -> list[tuple[Path | None, Path | None]]:
    out = []
    for j, sh in enumerate(scenes[idx]["shots"]):
        t = sh["visual"]["type"]
        if t in ("broll", "illustration", "archive"):
            out.append((shot_image(project, idx, j), None))
        elif t == "split":
            out.append((shot_image(project, idx, j, "a"), shot_image(project, idx, j, "b")))
        elif t in ("closeup", "kinetic"):
            out.append((previous_image(project, scenes, idx, j - 1) if j else previous_image(project, scenes, idx - 1, len(scenes[idx - 1]["shots"]) - 1) if idx else None, None))
        else:
            out.append((None, None))
    return out


def shot_video(project: Project, scene: int, shot: int) -> Path | None:
    p = project.path("images", f"s{scene:03d}_{shot:02d}.mp4")
    return p if p.exists() else None


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
        pad = np.zeros(int(tl["voice_offset"] * sr), dtype=np.float32)
        env = mouth_envelope(np.concatenate([pad, a]), sr, fps, frames)
    starts = tl.get("shots") or [0.0]
    shots = []
    for j, (sh, (im1, im2)) in enumerate(zip(scenes[idx]["shots"], shot_images(project, scenes, idx))):
        vid = shot_video(project, idx, j) if sh["visual"]["type"] in ("broll", "archive") else None
        shots.append({"spec": sh, "start": starts[j] if j < len(starts) else starts[-1], "image": _load(im1), "image2": _load(im2),
                      "video": str(vid) if vid else None})
    return SceneContext(
        size=(v["width"], v["height"]), fps=fps, duration=frames / fps, theme=project.theme, seed=idx * 7 + 3,
        image=shots[0]["image"] if shots else None, envelope=env, sentences=tl.get("sentences", []),
        chapter_number=scenes[idx]["chapter_index"] + 1, is_last=idx == len(scenes) - 1,
        channel_name=cfg["channel"]["name"], burn_captions=bool(v.get("burn_captions")), shots=shots,
    )


def scene_hash(project: Project, scenes: list[dict], timeline: dict, idx: int) -> str:
    cfg = load_config()
    parts = [RENDER_VERSION, json.dumps(cfg["video"], sort_keys=True), project.theme]
    for j in (idx - 1, idx):
        if j < 0:
            continue
        parts.append(json.dumps({k: scenes[j].get(k) for k in ("shots", "mascot")}, sort_keys=True))
        parts.append(json.dumps(timeline["scenes"][j], sort_keys=True))
        for k, pair in enumerate(shot_images(project, scenes, j)):
            for im in (*pair, shot_video(project, j, k)):
                if im is not None:
                    parts.append(f"{im.name}:{im.stat().st_mtime_ns}")
        w = project.path("audio", f"scene_{j:03d}.wav")
        if w.exists():
            parts.append(f"{w.stat().st_mtime_ns}")
    parts.append(str(idx == len(scenes) - 1))
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _whip(prev: Image.Image, cur: Image.Image, p: float) -> Image.Image:
    """Fast whip-pan: old frame slides out left, new slides in, with motion blur."""
    W, H = cur.size
    e = ease_in_out_sine(p)
    x = int(e * W)
    out = Image.new("RGB", (W, H))
    out.paste(prev.crop((x, 0, W, H)), (0, 0))
    out.paste(cur.crop((0, 0, x, H)), (W - x, 0))
    blur = 1 - abs(0.5 - p) * 2  # strongest in the middle
    if blur > 0.05:
        k = max(2, int(48 * blur))
        out = out.resize((max(1, W // k), H), Image.BILINEAR).resize((W, H), Image.BILINEAR)
    return out


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

    if preview:  # one still per shot
        out_dir = Path(out_path)
        for j, sh in enumerate(ctx.shots):
            st = sh["start"]
            en = ctx.shots[j + 1]["start"] if j + 1 < len(ctx.shots) else ctx.duration
            t = min(st + (en - st) * 0.6, ctx.duration - 0.05)
            scene.frame(t).resize((640, 360), Image.LANCZOS).save(out_dir / f"scene_{idx:03d}_{j:02d}.jpg", quality=85)
        return out_path

    prev_last = None
    kind = scenes[idx]["shots"][0]["visual"]["type"]
    if idx > 0:
        pctx = build_context(project, scenes, timeline, idx - 1)
        prev_last = make_scene(scenes[idx - 1], pctx).frame(pctx.duration - 1 / fps)
    # chapter titles get the brand wipe; every 3rd paragraph a whip-pan; otherwise a hard cut
    trans = 0.5 if kind == "title" else (0.25 if idx % 3 == 1 else 0.0)

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
                f = _wipe(prev_last, f, p) if kind == "title" else _whip(prev_last, f, p)
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
            jobs.append(ex.submit(render_scene, project.slug, i, str(out_dir), True))
        for k, fut in enumerate(as_completed(jobs)):
            fut.result()
    log(f"  storyboard: {sum(len(s['shots']) for s in scenes)} preview frames")


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
        shot_t = tl.get("shots") or [0.0]
        for j, sh in enumerate(scenes[i]["shots"]):
            st_ = tl["start"] + shot_t[min(j, len(shot_t) - 1)]
            kind, fx = sh["visual"]["type"], sh.get("fx", "none")
            if kind == "title":
                sfx.append((st_, "whoosh"))
            elif j == 0 and i % 3 == 1:
                sfx.append((max(0.0, st_ - 0.05), "whoosh"))  # whip-pan
            if kind in ("kinetic", "stat", "mascot") and (i or j):
                sfx.append((st_ + 0.05, "pop"))
            if fx in ("shake", "flash", "punch"):
                sfx.append((st_, "impact"))
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
