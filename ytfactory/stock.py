"""Free stock media: photos + video clips from Pexels / Pixabay (free API keys), and keyless
public sources (Openverse, Wikimedia Commons, NASA). Claude looks at the candidates and picks
the one that actually shows what the narration says.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import requests
from PIL import Image, ImageDraw

from .config import load_config
from .images import UA, wikimedia_search
from .tts import ffmpeg_exe

TIMEOUT = 30
OK_OPENVERSE = {"by", "by-sa", "cc0", "pdm"}  # commercial use + modification allowed


def _cfg() -> dict:
    return load_config().get("stock", {})


def key(name: str) -> str:
    env = {"pexels_key": "PEXELS_API_KEY", "pixabay_key": "PIXABAY_API_KEY"}[name]
    return os.environ.get(env) or str(_cfg().get(name) or "")


def _get(url: str, **kw) -> dict:
    r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA, **kw.pop("headers", {})}, **kw)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------ providers
# Every provider returns candidates:
# {"id", "kind": "photo"|"video", "preview": url, "url": full-res url, "width", "height",
#  "duration" (video), "credit": {"title","artist","license","page"}}

def pexels_photos(q: str, n: int = 6) -> list[dict]:
    if not key("pexels_key"):
        return []
    d = _get("https://api.pexels.com/v1/search", params={"query": q, "orientation": "landscape", "per_page": n, "size": "large"},
             headers={"Authorization": key("pexels_key")})
    return [{
        "id": f"pexels-photo-{p['id']}", "kind": "photo", "preview": p["src"].get("medium") or p["src"]["small"],
        "url": p["src"].get("large2x") or p["src"]["original"], "width": p["width"], "height": p["height"],
        "credit": {"title": p.get("alt") or f"Pexels photo {p['id']}", "artist": p.get("photographer", "Pexels"),
                   "license": "Pexels License", "page": p.get("url", "")},
    } for p in d.get("photos", [])]


def pexels_videos(q: str, n: int = 4) -> list[dict]:
    if not key("pexels_key"):
        return []
    d = _get("https://api.pexels.com/videos/search", params={"query": q, "orientation": "landscape", "per_page": n, "size": "medium"},
             headers={"Authorization": key("pexels_key")})
    out = []
    for v in d.get("videos", []):
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and (f.get("width") or 0) >= 1280]
        if not files:
            continue
        best = min(files, key=lambda f: abs((f.get("width") or 0) - 1920))
        out.append({
            "id": f"pexels-video-{v['id']}", "kind": "video", "preview": v.get("image", ""), "url": best["link"],
            "width": best.get("width"), "height": best.get("height"), "duration": v.get("duration", 0),
            "credit": {"title": f"Pexels video {v['id']}", "artist": (v.get("user") or {}).get("name", "Pexels"),
                       "license": "Pexels License", "page": v.get("url", "")},
        })
    return out


def pixabay_photos(q: str, n: int = 6) -> list[dict]:
    if not key("pixabay_key"):
        return []
    d = _get("https://pixabay.com/api/", params={"key": key("pixabay_key"), "q": q[:100], "image_type": "photo",
                                                 "orientation": "horizontal", "per_page": max(3, n), "safesearch": "true", "min_width": 1280})
    return [{
        "id": f"pixabay-photo-{h['id']}", "kind": "photo", "preview": h.get("webformatURL") or h["previewURL"],
        "url": h.get("largeImageURL") or h["webformatURL"], "width": h.get("imageWidth"), "height": h.get("imageHeight"),
        "credit": {"title": h.get("tags", "Pixabay image"), "artist": h.get("user", "Pixabay"), "license": "Pixabay License",
                   "page": h.get("pageURL", "")},
    } for h in d.get("hits", [])[:n]]


def pixabay_videos(q: str, n: int = 4) -> list[dict]:
    if not key("pixabay_key"):
        return []
    d = _get("https://pixabay.com/api/videos/", params={"key": key("pixabay_key"), "q": q[:100], "per_page": max(3, n), "safesearch": "true"})
    out = []
    for h in d.get("hits", [])[:n]:
        vids = h.get("videos", {})
        f = vids.get("large") if (vids.get("large") or {}).get("url") else vids.get("medium")
        if not f or not f.get("url") or (f.get("width") or 0) < 1280:
            continue
        out.append({
            "id": f"pixabay-video-{h['id']}", "kind": "video", "preview": f.get("thumbnail") or (vids.get("tiny") or {}).get("thumbnail", ""),
            "url": f["url"], "width": f.get("width"), "height": f.get("height"), "duration": h.get("duration", 0),
            "credit": {"title": h.get("tags", "Pixabay video"), "artist": h.get("user", "Pixabay"), "license": "Pixabay License",
                       "page": h.get("pageURL", "")},
        })
    return out


def openverse_photos(q: str, n: int = 6) -> list[dict]:
    if not _cfg().get("openverse", True):
        return []
    d = _get("https://api.openverse.org/v1/images/", params={"q": q, "license_type": "commercial,modification",
                                                            "aspect_ratio": "wide", "size": "large", "mature": "false", "page_size": n})
    out = []
    for r in d.get("results", []):
        if (r.get("license") or "").lower() not in OK_OPENVERSE:
            continue
        lic = r.get("license", "").upper()
        lic = "Public domain" if lic == "PDM" else ("CC0" if lic == "CC0" else f"CC {lic} {r.get('license_version', '')}".strip())
        out.append({
            "id": f"openverse-{r['id']}", "kind": "photo", "preview": r.get("thumbnail") or r["url"], "url": r["url"],
            "width": r.get("width"), "height": r.get("height"),
            "credit": {"title": r.get("title") or "Untitled", "artist": r.get("creator") or "Unknown", "license": lic,
                       "page": r.get("foreign_landing_url", "")},
        })
    return out


def wikimedia_photos(q: str, n: int = 6) -> list[dict]:
    if not load_config()["images"].get("wikimedia", True):
        return []
    return [{
        "id": f"wikimedia-{r['title']}", "kind": "photo", "preview": r["url"], "url": r["url"],
        "width": r.get("width"), "height": r.get("height"),
        "credit": {k: r[k] for k in ("title", "artist", "license", "page")},
    } for r in wikimedia_search(q, limit=n * 2)[:n]]


def nasa_photos(q: str, n: int = 6) -> list[dict]:
    if not _cfg().get("nasa", True):
        return []
    d = _get("https://images-api.nasa.gov/search", params={"q": q, "media_type": "image", "page_size": n})
    out = []
    for it in (d.get("collection") or {}).get("items", [])[:n]:
        data = (it.get("data") or [{}])[0]
        thumb = next((l["href"] for l in it.get("links", []) if l.get("render") == "image"), None)
        if not thumb:
            continue
        out.append({
            "id": f"nasa-{data.get('nasa_id')}", "kind": "photo", "preview": thumb, "url": thumb.replace("~thumb", "~large"),
            "width": None, "height": None,
            "credit": {"title": data.get("title", "NASA image"), "artist": data.get("center") or "NASA",
                       "license": "Public domain (NASA)", "page": f"https://images.nasa.gov/details/{data.get('nasa_id')}"},
        })
    return out


PHOTO_PROVIDERS: dict[str, Callable] = {
    "pexels": pexels_photos, "pixabay": pixabay_photos, "openverse": openverse_photos,
    "wikimedia": wikimedia_photos, "nasa": nasa_photos,
}
VIDEO_PROVIDERS: dict[str, Callable] = {"pexels": pexels_videos, "pixabay": pixabay_videos}


def candidates(query: str, kind: str = "broll", prefer: str = "any", n: int = 6, exclude: set | None = None,
               log: Callable = print) -> list[dict]:
    """Gather up to n candidates for a shot. kind: broll | archive."""
    exclude = exclude or set()
    order = (["wikimedia", "nasa", "openverse", "pexels", "pixabay"] if kind == "archive"
             else ["pexels", "pixabay", "openverse", "wikimedia", "nasa"])
    want_video = kind == "broll" and prefer != "photo" and _cfg().get("video", True)
    out: list[dict] = []
    if want_video:
        for name in ("pexels", "pixabay"):
            try:
                out += [c for c in VIDEO_PROVIDERS[name](query, 3) if c["id"] not in exclude]
            except Exception as e:  # noqa: BLE001 - one provider failing must not stop the video
                log(f"    ({name} video search failed: {e})")
    for name in order:
        if len(out) >= n + (2 if want_video else 0):
            break
        try:
            got = PHOTO_PROVIDERS[name](query, n)
        except Exception as e:  # noqa: BLE001
            log(f"    ({name} search failed: {e})")
            continue
        for c in got:
            w, h = c.get("width") or 0, c.get("height") or 0
            if kind == "broll" and w and h and (w < 1000 or w / h < 1.2):
                continue  # too small or portrait - looks bad full screen
            if c["id"] not in exclude:
                out.append(c)
    return out[: n + (2 if want_video else 0)]


# ------------------------------------------------------------------ downloads
def download_image(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        if img.width > 2600:
            img = img.resize((2600, int(img.height * 2600 / img.width)), Image.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, quality=92)
        return True
    except Exception:  # noqa: BLE001
        return False


def download_clip(url: str, dest: Path, duration: float, size=(1920, 1080), fps: int = 30) -> bool:
    """Download a stock clip and normalise it: cropped to 16:9, exact fps, just as long as the shot needs.
    Also writes a poster frame next to it (dest.jpg) for closeups/thumbnails."""
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "raw.mp4"
        try:
            with requests.get(url, headers={"User-Agent": UA}, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(raw, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
        except Exception:  # noqa: BLE001
            return False
        return normalize_clip(raw, dest, duration, size, fps)


def normalize_clip(src: Path, dest: Path, duration: float, size=(1920, 1080), fps: int = 30, start: float | None = None) -> bool:
    W, H = size
    if start is None:
        start = 1.0  # skip the first second: stock clips often start with a fade or shaky frame
        total = probe_duration(src)
        if total and total < duration + start:
            start = max(0.0, total - duration)
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    ok = subprocess.run([ffmpeg_exe(), "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{duration + 0.5:.2f}",
                         "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(dest)],
                        capture_output=True).returncode == 0 and dest.exists()
    if ok:
        subprocess.run([ffmpeg_exe(), "-y", "-v", "error", "-ss", "0.3", "-i", str(dest), "-frames:v", "1", str(dest.with_suffix(".jpg"))],
                       capture_output=True)
    return ok


def probe_duration(path: Path) -> float | None:
    proc = subprocess.run([ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True, errors="replace")
    import re

    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


# ------------------------------------------------------------------ Claude picks the best candidate
def _thumb(url_or_img, size=(400, 225)) -> Image.Image:
    if isinstance(url_or_img, Image.Image):
        img = url_or_img
    else:
        r = requests.get(url_or_img, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content))
    img = img.convert("RGB")
    k = max(size[0] / img.width, size[1] / img.height)
    img = img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS)
    x, y = (img.width - size[0]) // 2, (img.height - size[1]) // 2
    return img.crop((x, y, x + size[0], y + size[1]))


def contact_sheet(cands: list[dict], out: Path) -> list[int]:
    """Numbered grid (3 columns) of candidate previews. Returns indices that loaded."""
    from .render.common import font

    tiles, ok = [], []
    for i, c in enumerate(cands):
        try:
            tiles.append(_thumb(c.get("preview_img") or c["preview"]))
            ok.append(i)
        except Exception:  # noqa: BLE001
            continue
    if not tiles:
        return []
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 410 + 10, rows * 235 + 10), (20, 20, 28))
    d = ImageDraw.Draw(sheet)
    f = font("heading", 40)
    for n, (t, i) in enumerate(zip(tiles, ok)):
        x, y = 10 + (n % cols) * 410, 10 + (n // cols) * 235
        sheet.paste(t, (x, y))
        tag = f"{n + 1}" + (" VIDEO" if cands[i]["kind"] == "video" else "")
        d.rectangle([x, y, x + 24 + f.getlength(tag), y + 50], fill=(0, 0, 0))
        d.text((x + 10, y + 2), tag, font=f, fill=(255, 210, 63))
    sheet.save(out, quality=88)
    return ok


def claude_pick(shots: list[dict], log: Callable = print) -> dict[str, int]:
    """shots: [{"id", "say", "query", "cands"}]. Returns {id: chosen index into cands, or -1 for none}."""
    from . import claude_cli

    picks: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="ytf_pick_") as td:
        lines, maps = [], {}
        for s in shots:
            fn = f"{s['id'].replace(':', '_')}.jpg"
            ok = contact_sheet(s["cands"], Path(td) / fn)
            if not ok:
                picks[s["id"]] = -1
                continue
            maps[s["id"]] = ok
            lines.append(f'- shot "{s["id"]}": narration "{s["say"]}" (searched: {s["query"]}) -> image file {fn}, {len(ok)} options')
        if not lines:
            return picks
        prompt = (
            "You are the picture editor of a documentary YouTube channel. For each shot below, open its image file with the "
            "Read tool. It is a grid of numbered stock options (top-left = 1, left to right, row by row; 'VIDEO' = a moving clip, "
            "shown by its first frame). Pick the option that best SHOWS what the narration says at that moment.\n"
            "Rules: must clearly match the subject (right animal/object/place - be strict); high quality, sharp, well lit; "
            "no watermarks, no big text, logos or collages; no gore; prefer VIDEO when it matches equally well. "
            "Answer 0 if none of them fits - an off-topic image is worse than none.\n\n"
            + "\n".join(lines)
            + '\n\nReturn ONLY JSON in a ```json block: {"picks": {"<shot id>": <number or 0>, ...}}'
        )
        def check(d):
            if not isinstance(d, dict) or not isinstance(d.get("picks"), dict):
                raise ValueError("expected {'picks': {...}}")

        try:
            data = claude_cli.ask_json(prompt, allow_read=True, workdir=Path(td), log=log, validate=check)
        except Exception as e:  # noqa: BLE001
            log(f"    (Claude picture pick failed: {e}; using first results)")
            data = {"picks": {}}
        for sid, ok in maps.items():
            n = data["picks"].get(sid)
            try:
                n = int(n)
            except (TypeError, ValueError):
                n = 1
            picks[sid] = ok[n - 1] if 1 <= n <= len(ok) else -1
    return picks


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
