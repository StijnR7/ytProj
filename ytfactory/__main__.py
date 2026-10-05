"""Command line: python -m ytfactory <command>"""
from __future__ import annotations

import argparse
import sys

from .project import STAGES, Project


def cmd_check(args) -> None:
    import subprocess

    from .claude_cli import find_claude
    from .config import load_config
    from .images import find_sd_exe
    from .tts import KOKORO_MODEL, ffmpeg_exe

    cfg = load_config()
    ok = True

    def row(name, good, hint=""):
        nonlocal ok
        ok &= bool(good)
        print(f"  [{'OK' if good else '!!'}] {name}" + (f"  -> {hint}" if not good and hint else ""))

    print("Environment check")
    claude = find_claude()
    row("Claude Code CLI", claude, "install: https://claude.ai/code  (then run `claude` once and log in)")
    try:
        subprocess.run([ffmpeg_exe(), "-version"], capture_output=True, check=True)
        row("ffmpeg", True)
    except Exception:  # noqa: BLE001
        row("ffmpeg", False, "pip install imageio-ffmpeg")
    eng = cfg["voice"]["engine"]
    row(f"voice engine '{eng}'", eng != "kokoro" or KOKORO_MODEL.exists(), "python -m ytfactory setup")
    be = cfg["images"]["backend"]
    if be == "sdcpp":
        from .config import resolve
        row("stable-diffusion.cpp", find_sd_exe(), "python -m ytfactory setup --images")
        row("SDXL model", resolve(cfg["images"]["sdcpp"]["model"]).exists(), "python -m ytfactory setup --images")
    elif be == "comfyui":
        import requests
        try:
            requests.get(cfg["images"]["comfyui"]["url"], timeout=3)
            row("ComfyUI server", True)
        except Exception:  # noqa: BLE001
            row("ComfyUI server", False, f"start ComfyUI at {cfg['images']['comfyui']['url']}")
    else:
        print("  [--] AI images disabled (built-in art will be used)")
    if args.test_image and be in ("sdcpp", "comfyui"):
        from pathlib import Path

        from .images import generate_image
        out = Path("test_image.png")
        print("  generating a test image...")
        generate_image("a tiny friendly robot probe floating above a glowing alien jungle", out, seed=42)
        print(f"  -> {out.resolve()}")
    print("All good!" if ok else "Fix the items marked !! (see README).")


def cmd_setup(args) -> None:
    from .setup_tools import run_setup

    run_setup(images=args.images)


def cmd_ideas(args) -> None:
    from .pipeline import generate_ideas, load_ideas

    if args.generate:
        generate_ideas(args.n)
    for i, idea in enumerate(load_ideas()):
        mark = "x" if idea.get("used") else " "
        print(f"[{mark}] {i:3d}  ({idea.get('category', '?'):13s}) {idea['title']}")


def cmd_new(args) -> None:
    from .pipeline import load_ideas, save_ideas

    if args.idea is not None:
        ideas = load_ideas()
        idea = ideas[args.idea]
        idea["used"] = True
        save_ideas(ideas)
        p = Project.create(idea["title"], idea.get("category", ""), idea.get("angle", ""))
    else:
        p = Project.create(args.topic, args.category or "", args.angle or "")
    print(f"Created project: {p.slug}\n  run it: python -m ytfactory run {p.slug}")


def cmd_run(args) -> None:
    from .pipeline import run

    p = Project(args.slug)
    if not p.meta_path.exists():
        sys.exit(f"No project '{args.slug}'. See: python -m ytfactory list")
    ok = run(p, start=args.start, stop=args.stop, force=args.force)
    sys.exit(0 if ok else 1)


def cmd_list(args) -> None:
    for p in Project.all():
        st = p.meta["stages"]
        done = sum(1 for s in STAGES if st.get(s) == "done")
        print(f"{p.slug:50s} {done}/{len(STAGES)}  {p.meta['topic']}")


def cmd_branding(args) -> None:
    from .thumbnails import make_branding

    make_branding()


def cmd_voices(args) -> None:
    """Render a sample of several Kokoro voices so you can pick Zib's voice."""
    from pathlib import Path

    import numpy as np
    import soundfile as sf

    from .tts import SR, KokoroTTS

    out = Path("voice_samples")
    out.mkdir(exist_ok=True)
    text = "In fourteen fifty-three, a city that had stood for over a thousand years finally fell. But the real story starts with a chain."
    for v in args.voices.split(","):
        a = KokoroTTS(v.strip(), 1.0).synth(text)
        sf.write(str(out / f"{v.strip()}.wav"), np.asarray(a), SR)
        print(f"  {out / (v.strip() + '.wav')}")
    print("Set your favourite as voice.kokoro_voice in config.yaml")


def cmd_dashboard(args) -> None:
    from .web.app import serve

    serve(args.port, open_browser=not args.no_browser)


def main() -> None:
    ap = argparse.ArgumentParser(prog="ytfactory", description="Probe Into It - free local YouTube documentary factory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="download the voice model (and image tools with --images)")
    s.add_argument("--images", action="store_true", help="also download stable-diffusion.cpp + SDXL (~7.5 GB)")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("check", help="verify everything is installed")
    s.add_argument("--test-image", action="store_true")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("ideas", help="list / generate video ideas")
    s.add_argument("--generate", action="store_true")
    s.add_argument("-n", type=int, default=12)
    s.set_defaults(fn=cmd_ideas)

    s = sub.add_parser("new", help="create a video project")
    s.add_argument("topic", nargs="?", default="")
    s.add_argument("--category", default="")
    s.add_argument("--angle", default="")
    s.add_argument("--idea", type=int, help="use idea number N from the backlog")
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("run", help="run the pipeline for a project")
    s.add_argument("slug")
    s.add_argument("--from", dest="start", choices=STAGES)
    s.add_argument("--to", dest="stop", choices=STAGES)
    s.add_argument("--force", action="store_true", help="redo stages even if done")
    s.set_defaults(fn=cmd_run)

    sub.add_parser("list", help="list projects").set_defaults(fn=cmd_list)
    sub.add_parser("branding", help="(re)generate channel art").set_defaults(fn=cmd_branding)

    s = sub.add_parser("voices", help="render voice samples")
    s.add_argument("--voices", default="am_michael,am_puck,am_fenrir,bm_george,bm_fable,af_heart,af_bella,bf_emma")
    s.set_defaults(fn=cmd_voices)

    s = sub.add_parser("dashboard", help="open the web app")
    s.add_argument("--port", type=int, default=7860)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(fn=cmd_dashboard)

    args = ap.parse_args()
    if args.cmd == "new" and not args.topic and args.idea is None:
        ap.error("give a topic or --idea N")
    args.fn(args)


if __name__ == "__main__":
    main()
