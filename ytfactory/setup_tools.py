"""One-time downloads: voice model, stable-diffusion.cpp (Vulkan, works on AMD) and SDXL weights."""
from __future__ import annotations

import platform
import shutil
import zipfile
from pathlib import Path

import requests

from .config import MODELS, TOOLS, resolve

KOKORO_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
HF = "https://huggingface.co/"
SDXL_FILES = {
    "models/sd_xl_base_1.0.safetensors": HF + "stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors",
    "models/sdxl_vae_fp16_fix.safetensors": HF + "madebyollin/sdxl-vae-fp16-fix/resolve/main/sdxl.vae.safetensors",
    "models/lora/sdxl_lightning_8step_lora.safetensors": HF + "ByteDance/SDXL-Lightning/resolve/main/sdxl_lightning_8step_lora.safetensors",
}


def download(url: str, dest: Path, log=print) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        log(f"  already have {dest.name}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    log(f"  downloading {dest.name} ...")
    with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "ytfactory"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done, last = 0, -1
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = int(done * 100 / total)
                    if pct // 10 != last:
                        last = pct // 10
                        log(f"    {pct}% of {total / 1e6:.0f} MB")
    tmp.replace(dest)


def setup_voice(log=print) -> None:
    for name in ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin"):
        download(KOKORO_BASE + name, MODELS / "kokoro" / name, log)


def setup_sdcpp(log=print) -> None:
    """Fetch the latest stable-diffusion.cpp release build for this OS (Vulkan on Windows/Linux)."""
    if platform.system() == "Windows":
        want = ("win", "vulkan", "x64")
    elif platform.system() == "Darwin":
        want = ("osx", "arm64") if platform.machine() == "arm64" else ("osx",)
    else:
        want = ("linux", "vulkan")
    rel = requests.get("https://api.github.com/repos/leejet/stable-diffusion.cpp/releases/latest", timeout=30).json()
    assets = [a for a in rel.get("assets", []) if all(w in a["name"].lower() for w in want) and a["name"].endswith(".zip")]
    if not assets:
        log(f"  !! no matching stable-diffusion.cpp build for {want}; download one manually into tools/sd")
        return
    asset = assets[0]
    z = TOOLS / asset["name"]
    download(asset["browser_download_url"], z, log)
    out = TOOLS / "sd"
    if out.exists():
        shutil.rmtree(out)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(out)
    z.unlink()
    log(f"  stable-diffusion.cpp extracted to {out} ({rel.get('tag_name')})")


def setup_sdxl(log=print) -> None:
    for rel, url in SDXL_FILES.items():
        download(url, resolve(rel), log)


def run_setup(images: bool = False, log=print) -> None:
    log("== Voice (Kokoro, ~120 MB) ==")
    setup_voice(log)
    if images:
        log("== stable-diffusion.cpp (Vulkan) ==")
        setup_sdcpp(log)
        log("== SDXL model + Lightning LoRA (~7.5 GB) ==")
        setup_sdxl(log)
    log("Setup complete. Next: python -m ytfactory check")
