"""The production pipeline: topic -> finished, upload-ready video package."""
from __future__ import annotations

import json
import math
import random
import traceback

import numpy as np
import soundfile as sf

from . import claude_cli, prompts
from .config import PROJECTS, load_config
from .images import ImageGenError, credit_line, fetch_wikimedia, generate_image
from .project import STAGES, Project, normalize_script, validate_script, word_count
from .tts import SR, synth_scene

IDEAS_FILE = PROJECTS / "ideas.json"


# ------------------------------------------------------------------ ideas backlog
def load_ideas() -> list[dict]:
    if IDEAS_FILE.exists():
        return json.loads(IDEAS_FILE.read_text(encoding="utf-8"))
    return []


def save_ideas(ideas: list[dict]) -> None:
    PROJECTS.mkdir(parents=True, exist_ok=True)
    IDEAS_FILE.write_text(json.dumps(ideas, indent=2, ensure_ascii=False), encoding="utf-8")


def generate_ideas(n: int = 12, log=print) -> list[dict]:
    cfg = load_config()["channel"]
    ideas = load_ideas()
    existing = [i["title"] for i in ideas] + [p.meta.get("topic", "") for p in Project.all()]

    def check(d):
        if not isinstance(d, dict) or not isinstance(d.get("ideas"), list) or not d["ideas"]:
            raise ValueError("expected {'ideas': [...]} ")

    data = claude_cli.ask_json(prompts.ideas_prompt(n, cfg["categories"], existing), validate=check, log=log)
    new = [{**i, "used": False} for i in data["ideas"] if i.get("title")]
    save_ideas(ideas + new)
    log(f"  {len(new)} new ideas added to the backlog")
    return new


# ------------------------------------------------------------------ stages
def stage_research(p: Project, log) -> None:
    m = p.meta
    web = bool(load_config()["claude"]["web_research"])
    text = claude_cli.ask(prompts.research_prompt(m["topic"], m["category"], m.get("angle", "")), allow_web=web, log=log)
    p.path("research.md").write_text(text, encoding="utf-8")
    log(f"  research brief: {len(text.split())} words")


def stage_script(p: Project, log) -> None:
    m = p.meta
    sc = load_config()["script"]
    research = p.path("research.md").read_text(encoding="utf-8") if p.path("research.md").exists() else ""
    script = claude_cli.ask_json(
        prompts.script_prompt(m["topic"], m["category"], research, sc["target_words"], m.get("angle", "")),
        validate=validate_script, log=log,
    )
    for _ in range(2):
        wc = word_count(script)
        log(f"  script: {wc} words, {sum(len(c['scenes']) for c in script['chapters'])} scenes")
        if wc >= sc["min_words"]:
            break
        log("  script too short for 10+ minutes - asking Claude to expand it")
        script = claude_cli.ask_json(prompts.expand_prompt(script, wc, sc["target_words"]), validate=validate_script, log=log)
    script = normalize_script(script, m["category"])
    # Make sure every chapter after the first opens with a title card and the video ends on Zib.
    for ci, ch in enumerate(script["chapters"]):
        if ci > 0 and ch["scenes"][0]["visual"]["type"] != "title":
            ch["scenes"].insert(0, {"narration": "", "visual": {"type": "title", "text": ch["title"], "subtitle": ""}, "mascot": "none", "on_screen_text": ""})
    last = script["chapters"][-1]["scenes"][-1]
    if last["visual"]["type"] != "mascot":
        last["visual"] = {"type": "mascot", "line": ""}
        last["mascot"] = "happy"
    p.write_json("script.json", script)


def stage_metadata(p: Project, log) -> None:
    script = p.read_json("script.json")
    research = p.path("research.md").read_text(encoding="utf-8") if p.path("research.md").exists() else ""

    def check(d):
        for k in ("titles", "best_title", "description_hook", "tags", "thumbnails"):
            if k not in d:
                raise ValueError(f"missing '{k}'")
        if len(d["thumbnails"]) < 1:
            raise ValueError("need thumbnail concepts")

    meta = claude_cli.ask_json(prompts.metadata_prompt(script, research), validate=check, log=log)
    p.write_json("metadata.json", meta)
    log(f"  title: {meta['best_title']}")


def stage_voice(p: Project, log) -> None:
    v = load_config()["voice"]
    fps = load_config()["video"]["fps"]
    scenes = p.scenes()
    adir = p.path("audio")
    adir.mkdir(exist_ok=True)
    timeline = {"scenes": [], "chapters": []}
    t = 0.0
    lead = 0.15
    for s in scenes:
        wav = adir / f"scene_{s['index']:03d}.wav"
        sj = adir / f"scene_{s['index']:03d}.json"
        cached = sj.exists() and json.loads(sj.read_text(encoding="utf-8")).get("text") == s["narration"] and wav.exists()
        if cached:
            sentences = json.loads(sj.read_text(encoding="utf-8"))["sentences"]
            audio, _ = sf.read(str(wav), dtype="float32")
        elif s["narration"].strip():
            audio, sentences = synth_scene(s["narration"])
            sf.write(str(wav), audio, SR, subtype="PCM_16")
            sj.write_text(json.dumps({"text": s["narration"], "sentences": sentences}), encoding="utf-8")
        else:
            audio, sentences = np.zeros(int(SR * 0.1), dtype=np.float32), []
            sf.write(str(wav), audio, SR, subtype="PCM_16")
            sj.write_text(json.dumps({"text": "", "sentences": []}), encoding="utf-8")
        dur = len(audio) / SR
        pause = v["pause_after_chapter"] if s["last_in_chapter"] else v["pause_after_scene"]
        length = lead + dur + pause
        kind = s["visual"]["type"]
        if kind == "title":
            length = max(length, 3.0)
        if s["index"] == len(scenes) - 1:
            length = max(length, 20.0)  # YouTube end screen needs 5-20s
        frames = math.ceil(length * fps)
        if s["first_in_chapter"]:
            timeline["chapters"].append({"title": s["chapter_title"], "start": round(t, 3)})
        timeline["scenes"].append({
            "index": s["index"], "start": round(t, 4), "frames": frames, "voice_offset": lead,
            "audio_seconds": round(dur, 3),
            "sentences": [{**x, "start": x["start"] + lead, "end": x["end"] + lead} for x in sentences],
        })
        t += frames / fps
        if (s["index"] + 1) % 10 == 0:
            log(f"  voiced {s['index'] + 1}/{len(scenes)} scenes")
    timeline["total_seconds"] = round(t, 3)
    p.write_json("timeline.json", timeline)
    mins = t / 60
    log(f"  narration done: video length {int(mins)}:{int(t % 60):02d}")
    if mins < load_config()["script"]["min_video_minutes"]:
        log(f"  !! WARNING: video is under {load_config()['script']['min_video_minutes']} minutes. Re-run the script stage to expand it.")


def stage_visuals(p: Project, log) -> None:
    cfg = load_config()["images"]
    scenes = p.scenes()
    idir = p.path("images")
    idir.mkdir(exist_ok=True)
    credits = p.read_json("credits.json", {}) or {}
    backend = cfg["backend"]
    need = [s for s in scenes if s["visual"]["type"] in ("illustration", "archive")]
    log(f"  {len(need)} scenes need images (AI backend: {backend}, Wikimedia: {cfg['wikimedia']})")
    for k, s in enumerate(need, 1):
        i, v = s["index"], s["visual"]
        if any(idir.glob(f"scene_{i:03d}.*")):
            continue
        if v["type"] == "archive" and cfg["wikimedia"]:
            c = fetch_wikimedia(v.get("query", ""), idir / f"scene_{i:03d}.jpg")
            if c:
                credits[str(i)] = c
                p.write_json("credits.json", credits)
                log(f"  [{k}/{len(need)}] archive: {c['title']}")
                continue
            log(f"  [{k}/{len(need)}] no free archive image for '{v.get('query')}', illustrating instead")
        try:
            if generate_image(v.get("prompt", s["narration"]), idir / f"scene_{i:03d}.png", seed=1000 + i + 7919 * int(v.get("seed_bump", 0))):
                log(f"  [{k}/{len(need)}] illustrated scene {i}")
        except ImageGenError as e:
            raise ImageGenError(f"{e}\n\nTip: set images.backend to 'none' in config.yaml to render with built-in art instead.") from e


def stage_storyboard(p: Project, log) -> None:
    from .render.engine import render_storyboard

    render_storyboard(p, log)
    scenes, tl = p.scenes(), p.read_json("timeline.json")
    rows = []
    for s, t in zip(scenes, tl["scenes"]):
        mm, ss = divmod(int(t["start"]), 60)
        v = s["visual"]
        detail = v.get("prompt") or v.get("query") or v.get("text") or v.get("line") or v.get("label") or v.get("heading") or ""
        rows.append(
            f"<div class=card><img src='storyboard/scene_{s['index']:03d}.jpg'><div><b>#{s['index']} {mm}:{ss:02d} - {v['type']}</b>"
            f" <i>{s['chapter_title']}</i><p>{s['narration']}</p><small>{detail}</small></div></div>"
        )
    html = ("<html><head><meta charset=utf-8><title>Storyboard</title><style>body{font-family:sans-serif;background:#0f1b3d;color:#fff}"
            ".card{display:flex;gap:16px;margin:10px;background:#1c2f66;padding:10px;border-radius:12px}img{width:320px;border-radius:8px}"
            "small{color:#9fb3e8}</style></head><body>" + "".join(rows) + "</body></html>")
    p.path("storyboard.html").write_text(html, encoding="utf-8")


def stage_render(p: Project, log) -> None:
    from .render.engine import render_video

    out = render_video(p, log)
    log(f"  video: {out}")


def stage_thumbnails(p: Project, log) -> None:
    from PIL import Image

    from .thumbnails import contact_sheet, make_thumbnail

    meta = p.read_json("metadata.json")
    out_dir = p.path("output")
    out_dir.mkdir(exist_ok=True)
    paths = []
    for n, c in enumerate(meta["thumbnails"][:3], 1):
        bg = None
        bgp = p.path("images", f"thumb_bg_{n}.png")
        if bgp.exists():
            bg = Image.open(bgp).convert("RGB")
        else:
            if c.get("archive_query") and load_config()["images"]["wikimedia"]:
                jp = p.path("images", f"thumb_bg_{n}.jpg")
                if jp.exists() or fetch_wikimedia(c["archive_query"], jp):
                    bg = Image.open(jp).convert("RGB")
            if bg is None:
                try:
                    if generate_image(c.get("prompt", meta["best_title"]), bgp, seed=77 + n):
                        bg = Image.open(bgp).convert("RGB")
                except ImageGenError as e:
                    log(f"  thumbnail bg generation failed ({e}); using built-in art")
            if bg is None:
                # reuse the most striking scene image if any
                imgs = sorted(p.path("images").glob("scene_*.*"))
                if imgs:
                    bg = Image.open(imgs[min(len(imgs) - 1, n * 3)]).convert("RGB")
        paths.append(make_thumbnail(c, bg, p.theme, out_dir / f"thumbnail_{n}.jpg"))
    contact_sheet(paths, out_dir / "thumbnails_compare.jpg")
    log(f"  {len(paths)} thumbnails (use YouTube 'Test & compare' to A/B them)")


def _ts(sec: float) -> str:
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _srt_time(x: float) -> str:
    ms = int(round(x * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def make_srt(timeline: dict) -> str:
    out, n = [], 1
    for sc in timeline["scenes"]:
        for s in sc["sentences"]:
            words = s["text"].split()
            chunks, cur = [], []
            for w in words:
                if len(" ".join(cur + [w])) > 84 and cur:
                    chunks.append(cur)
                    cur = []
                cur.append(w)
            if cur:
                chunks.append(cur)
            total = sum(len(" ".join(c)) for c in chunks) or 1
            t0 = sc["start"] + s["start"]
            span = s["end"] - s["start"]
            for c in chunks:
                txt = " ".join(c)
                d = span * len(txt) / total
                if len(txt) > 42:  # two lines
                    mid = len(c) // 2
                    txt = " ".join(c[:mid]) + "\n" + " ".join(c[mid:])
                out.append(f"{n}\n{_srt_time(t0)} --> {_srt_time(t0 + d)}\n{txt}\n")
                n += 1
                t0 += d
    return "\n".join(out)


def stage_package(p: Project, log) -> None:
    cfg = load_config()["channel"]
    meta = p.read_json("metadata.json")
    tl = p.read_json("timeline.json")
    credits = p.read_json("credits.json", {}) or {}
    out = p.path("output")
    out.mkdir(exist_ok=True)

    chapters = [c for c in tl["chapters"]]
    chapters[0]["start"] = 0
    ch_lines = [f"{_ts(c['start'])} {c['title']}" for c in chapters]
    if len(chapters) >= 3:
        chapters_txt = "CHAPTERS\n" + "\n".join(ch_lines)
    else:
        chapters_txt = ""
    src = "\n".join(f"- {u}" for u in meta.get("sources", []))
    cred = "\n".join(f"- {credit_line(c)}" for c in credits.values())
    desc = "\n\n".join(x for x in [
        meta["description_hook"],
        meta.get("description_body", ""),
        chapters_txt,
        ("SOURCES\n" + src) if src else "",
        ("IMAGE CREDITS (Wikimedia Commons)\n" + cred) if cred else "",
        cfg.get("description_footer", "").strip(),
        " ".join(meta.get("hashtags", [])[:3]),
    ] if x)
    (out / "description.txt").write_text(desc, encoding="utf-8")

    tags, total = [], 0
    for t in meta["tags"]:
        t = t.replace(",", " ").strip()
        if total + len(t) + 1 > 480:
            break
        tags.append(t)
        total += len(t) + 1
    (out / "tags.txt").write_text(", ".join(tags), encoding="utf-8")
    (out / "title.txt").write_text(meta["best_title"] + "\n\nAlternatives:\n" + "\n".join(meta["titles"]), encoding="utf-8")
    (out / "captions.srt").write_text(make_srt(tl), encoding="utf-8")
    (out / "pinned_comment.txt").write_text(meta.get("pinned_comment", ""), encoding="utf-8")
    mins = tl["total_seconds"] / 60
    checklist = f"""# Upload checklist - {meta['best_title']}

Length: {int(mins)}:{int(tl['total_seconds'] % 60):02d}

1. YouTube Studio -> Create -> Upload video -> `video.mp4`
2. Title: paste from `title.txt` (alternatives listed there too)
3. Description: paste `description.txt` (chapters are already timestamped)
4. Thumbnail: upload `thumbnail_1.jpg`, then use **Test & compare** with thumbnail_2/3
5. Show more -> Tags: paste `tags.txt`
6. Category: **Education**. Made for kids: **No**. Language: English.
7. Altered or synthetic content: this is an animated, clearly illustrated video narrated by a cartoon robot,
   so it normally does not need the label. Tick it if you use realistic AI imagery of real people or events.
8. Subtitles -> Upload file -> With timing -> `captions.srt`
9. End screen (last 20s are reserved): Import from video / add 1-2 videos + subscribe in the two frames.
10. After publishing: pin the comment from `pinned_comment.txt`.

Shorts ideas to promote it:
""" + "\n".join(f"- {s}" for s in meta.get("shorts_ideas", [])) + """

Before publishing, WATCH IT ONCE and fact-check the claims marked in research.md as [DISPUTED]/[UNVERIFIED].
"""
    (out / "UPLOAD_CHECKLIST.md").write_text(checklist, encoding="utf-8")
    log(f"  upload package ready in {out}")


STAGE_FUNCS = {
    "research": stage_research,
    "script": stage_script,
    "metadata": stage_metadata,
    "voice": stage_voice,
    "visuals": stage_visuals,
    "storyboard": stage_storyboard,
    "render": stage_render,
    "thumbnails": stage_thumbnails,
    "package": stage_package,
}

# what must be redone if a stage is re-run
DOWNSTREAM = {
    "research": STAGES[1:],
    "script": STAGES[2:],
    "metadata": ["thumbnails", "package"],
    "voice": ["storyboard", "render", "package"],
    "visuals": ["storyboard", "render"],
    "storyboard": [],
    "render": ["package"],
    "thumbnails": ["package"],
    "package": [],
}


def run(p: Project, start: str | None = None, stop: str | None = None, force: bool = False, log=None) -> bool:
    log = log or p.log
    i0 = STAGES.index(start) if start else 0
    i1 = STAGES.index(stop) if stop else len(STAGES) - 1
    for stage in STAGES[i0: i1 + 1]:
        if not force and p.stage_status(stage) == "done" and stage != start:
            continue
        log(f"== {stage.upper()} ==")
        p.set_stage(stage, "running")
        try:
            STAGE_FUNCS[stage](p, log)
        except Exception as e:  # noqa: BLE001
            p.set_stage(stage, "error")
            log(f"!! {stage} failed: {e}")
            with open(p.path("log.txt"), "a", encoding="utf-8") as f:
                f.write(traceback.format_exc() + "\n")
            return False
        p.set_stage(stage, "done")
        m = p.meta
        for d in DOWNSTREAM[stage]:
            if m["stages"].get(d) == "done" and d in STAGES[STAGES.index(stage) + 1:]:
                m["stages"][d] = "stale"
        p.save_meta(m)
    log("== finished ==")
    return True


def random_idea() -> dict | None:
    unused = [i for i in load_ideas() if not i.get("used")]
    return random.choice(unused) if unused else None
