"""Configuration loading and project-wide paths."""
from __future__ import annotations

import copy
import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
PROJECTS = ROOT / "projects"
CHANNEL_DIR = ROOT / "channel"
CACHE = ROOT / ".cache"
MODELS = ROOT / "models"
TOOLS = ROOT / "tools"

DEFAULTS: dict = {
    "channel": {
        "name": "Probe Into It",
        "handle": "@ProbeIntoIt",
        "tagline": "Every rabbit hole, fully explored.",
        "mascot_name": "Zib",
        "categories": ["history", "space", "animals", "hypotheticals"],
        "description_footer": "",
    },
    "claude": {"command": "claude", "model": "", "web_research": True, "timeout_minutes": 20},
    "script": {"target_words": 2000, "min_words": 1750, "min_video_minutes": 10},
    "voice": {
        "engine": "kokoro",
        "kokoro_voice": "am_michael",
        "speed": 1.0,
        "edge_voice": "en-US-AndrewNeural",
        "pause_after_scene": 0.35,
        "pause_after_chapter": 0.8,
    },
    "images": {
        "backend": "none",
        "width": 1344,
        "height": 768,
        "style": "flat 2D vector illustration, no text",
        "negative": "text, watermark",
        "sdcpp": {
            "exe": "tools/sd/sd.exe",
            "model": "",
            "vae": "",
            "lora_dir": "",
            "lora": "",
            "steps": 8,
            "cfg": 1.0,
            "sampler": "euler",
            "extra_args": [],
        },
        "comfyui": {
            "url": "http://127.0.0.1:8188",
            "checkpoint": "",
            "steps": 25,
            "cfg": 6.0,
            "sampler": "dpmpp_2m",
            "scheduler": "karras",
        },
        "wikimedia": True,
    },
    "video": {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "crf": 20,
        "preset": "veryfast",
        "workers": 0,
        "burn_captions": False,
    },
    "music": {"folder": "assets/music", "volume_db": -20},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


@lru_cache(maxsize=1)
def load_config() -> dict:
    path = Path(os.environ.get("YTF_CONFIG", ROOT / "config.yaml"))
    data = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = _merge(DEFAULTS, data)
    # Test/CI overrides, e.g. YTF_VOICE_ENGINE=dummy
    if os.environ.get("YTF_VOICE_ENGINE"):
        cfg["voice"]["engine"] = os.environ["YTF_VOICE_ENGINE"]
    if os.environ.get("YTF_IMAGE_BACKEND"):
        cfg["images"]["backend"] = os.environ["YTF_IMAGE_BACKEND"]
    return cfg


def resolve(p: str | Path) -> Path:
    """Resolve a config path relative to the repo root."""
    p = Path(p)
    return p if p.is_absolute() else ROOT / p
