"""Image sources: local AI generation (free, on your GPU) and Wikimedia Commons (public domain / CC)."""
from __future__ import annotations

import io
import json
import random
import re
import subprocess
import time
import uuid
from pathlib import Path

import requests
from PIL import Image

from .config import load_config, resolve

UA = "ProbeIntoItVideoFactory/1.0 (personal educational video tool)"
OK_LICENSES = ("public domain", "pd", "cc0", "cc by", "cc-by", "cc by-sa", "cc-by-sa", "no restrictions")


class ImageGenError(RuntimeError):
    pass


# ------------------------------------------------------------------ AI backends

def full_prompt(prompt: str) -> str:
    style = load_config()["images"]["style"]
    return f"{prompt.strip().rstrip('.')}, {style}"


def find_sd_exe() -> Path | None:
    cfg = load_config()["images"]["sdcpp"]
    p = resolve(cfg["exe"])
    if p.exists():
        return p
    base = resolve("tools/sd")
    for name in ("sd.exe", "sd-cli.exe", "sd", "sd-cli"):
        for cand in base.rglob(name):
            return cand
    return None


def gen_sdcpp(prompt: str, out: Path, seed: int, width: int, height: int) -> None:
    cfg = load_config()["images"]
    sd = cfg["sdcpp"]
    exe = find_sd_exe()
    if not exe:
        raise ImageGenError("stable-diffusion.cpp not found in tools/sd. Run: python -m ytfactory setup --images")
    model = resolve(sd["model"])
    if not model.exists():
        raise ImageGenError(f"Image model not found: {model}")
    p = full_prompt(prompt)
    if sd.get("lora") and sd.get("lora_dir"):
        p += f" <lora:{sd['lora']}:1>"
    args = [
        str(exe), "-m", str(model), "-p", p, "-n", cfg["negative"],
        "-W", str(width), "-H", str(height), "--steps", str(sd["steps"]),
        "--cfg-scale", str(sd["cfg"]), "--sampling-method", str(sd["sampler"]),
        "-s", str(seed), "-o", str(out),
    ]
    if sd.get("vae") and resolve(sd["vae"]).exists():
        args += ["--vae", str(resolve(sd["vae"]))]
    if sd.get("lora") and sd.get("lora_dir"):
        args += ["--lora-model-dir", str(resolve(sd["lora_dir"]))]
    args += [str(a) for a in sd.get("extra_args", [])]
    proc = subprocess.run(args, capture_output=True, text=True, errors="replace", cwd=str(exe.parent))
    if proc.returncode != 0 or not out.exists():
        tail = (proc.stdout + proc.stderr)[-1500:]
        raise ImageGenError(f"stable-diffusion.cpp failed:\n{tail}")


def _comfy_workflow(prompt: str, seed: int, width: int, height: int) -> dict:
    cfg = load_config()["images"]
    c = cfg["comfyui"]
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": c["checkpoint"]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": full_prompt(prompt), "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": cfg["negative"], "clip": ["4", 1]}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": c["steps"], "cfg": c["cfg"], "sampler_name": c["sampler"],
                "scheduler": c["scheduler"], "denoise": 1.0, "model": ["4", 0],
                "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ytf", "images": ["8", 0]}},
    }


def gen_comfyui(prompt: str, out: Path, seed: int, width: int, height: int) -> None:
    url = load_config()["images"]["comfyui"]["url"].rstrip("/")
    client = str(uuid.uuid4())
    try:
        r = requests.post(f"{url}/prompt", json={"prompt": _comfy_workflow(prompt, seed, width, height), "client_id": client}, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        raise ImageGenError(f"ComfyUI not reachable at {url}: {e}") from e
    pid = r.json()["prompt_id"]
    deadline = time.time() + 600
    while time.time() < deadline:
        h = requests.get(f"{url}/history/{pid}", timeout=30).json()
        if pid in h:
            for node in h[pid]["outputs"].values():
                for img in node.get("images", []):
                    data = requests.get(f"{url}/view", params=img, timeout=60).content
                    Image.open(io.BytesIO(data)).convert("RGB").save(out)
                    return
            raise ImageGenError("ComfyUI finished without an image")
        time.sleep(1.0)
    raise ImageGenError("ComfyUI timed out")


def generate_image(prompt: str, out: Path, seed: int | None = None, width: int | None = None, height: int | None = None) -> bool:
    """Generate an AI image. Returns False when the backend is 'none' (caller uses a fallback)."""
    cfg = load_config()["images"]
    backend = cfg["backend"].lower()
    seed = seed if seed is not None else random.randint(1, 2**31 - 1)
    w, h = width or cfg["width"], height or cfg["height"]
    out.parent.mkdir(parents=True, exist_ok=True)
    if backend == "sdcpp":
        gen_sdcpp(prompt, out, seed, w, h)
        return True
    if backend == "comfyui":
        gen_comfyui(prompt, out, seed, w, h)
        return True
    return False


# ------------------------------------------------------------------ Wikimedia Commons

def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def wikimedia_search(query: str, limit: int = 12) -> list[dict]:
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": limit,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 2400,
    }
    r = requests.get("https://commons.wikimedia.org/w/api.php", params=params, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages") or {}
    results = []
    for p in sorted(pages.values(), key=lambda p: p.get("index", 99)):
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = _strip_html((meta.get("LicenseShortName") or {}).get("value", ""))
        if not any(lic.lower().startswith(ok) for ok in OK_LICENSES):
            continue
        if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        if min(info.get("width", 0), info.get("height", 0)) < 500:
            continue
        results.append({
            "title": p.get("title", ""),
            "url": info.get("thumburl") or info.get("url"),
            "page": info.get("descriptionurl", ""),
            "license": lic,
            "artist": _strip_html((meta.get("Artist") or {}).get("value", ""))[:120] or "Unknown",
            "width": info.get("width"), "height": info.get("height"),
        })
    return results


def fetch_wikimedia(query: str, out: Path) -> dict | None:
    """Download the best matching freely-licensed image. Returns credit info or None."""
    try:
        results = wikimedia_search(query)
    except requests.RequestException:
        return None
    for res in results[:4]:
        try:
            r = requests.get(res["url"], headers={"User-Agent": UA}, timeout=60)
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            out.parent.mkdir(parents=True, exist_ok=True)
            img.save(out, quality=95)
            return {k: res[k] for k in ("title", "page", "license", "artist")}
        except Exception:  # noqa: BLE001
            continue
    return None


def credit_line(c: dict) -> str:
    name = c["title"].replace("File:", "")
    return f"{name} - {c['artist']} - {c['license']} - {c['page']}"


def save_credits(path: Path, credits: dict) -> None:
    path.write_text(json.dumps(credits, indent=2, ensure_ascii=False), encoding="utf-8")
