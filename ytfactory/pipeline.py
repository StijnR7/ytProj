"""The production pipeline: topic -> finished, upload-ready video package."""
from __future__ import annotations

import json
import math
import random
import traceback
from pathlib import Path

import numpy as np
import soundfile as sf

from . import claude_cli, prompts
from .config import PROJECTS, load_config
from .images import ImageGenError, credit_line, fetch_wikimedia, generate_image
from .project import IMAGE_TYPES, STAGES, Project, normalize_script, validate_script, word_count
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
    if load_config()["script"].get("hook_doctor", True):
        try:
            script = hook_doctor(script, research, log)
        except Exception as e:  # noqa: BLE001 - the original hook is still usable
            log(f"  hook doctor skipped: {e}")
    script = normalize_script(script, m["category"])
    # Every chapter after the first opens with a title card; the video ends on Zib.
    for ci, ch in enumerate(script["chapters"]):
        if ci > 0 and ch["scenes"][0]["shots"][0]["visual"]["type"] != "title":
            ch["scenes"].insert(0, {"mascot": "none", "shots": [{"say": "", "visual": {"type": "title", "text": ch["title"], "subtitle": ""}, "fx": "none", "label": ""}]})
    last = script["chapters"][-1]["scenes"][-1]
    if last["shots"][-1]["visual"]["type"] != "mascot":
        last["shots"][-1]["visual"] = {"type": "mascot", "line": ""}
    last["mascot"] = "happy"
    script = normalize_script(script, m["category"])
    n_shots = sum(len(sc["shots"]) for c in script["chapters"] for sc in c["scenes"])
    log(f"  final script: {word_count(script)} words, {n_shots} shots")
    p.write_json("script.json", script)


def hook_doctor(script: dict, research: str, log) -> dict:
    """Second pass that rewrites only the opening chapter for a harder hook."""
    log("  hook doctor: rewriting the first 30 seconds for maximum retention")
    tmp = normalize_script(json.loads(json.dumps(script)), script.get("category", ""))

    def check(d):
        if not isinstance(d, dict) or not isinstance(d.get("scenes"), list) or not d["scenes"]:
            raise ValueError("expected a chapter object with scenes")
        validate_script({"chapters": [{"title": d.get("title") or "Hook", "scenes": d["scenes"]}]})

    ch = claude_cli.ask_json(prompts.hook_doctor_prompt(tmp, research), validate=check, log=log)
    ch["title"] = ch.get("title") or script["chapters"][0]["title"]
    script["chapters"][0] = ch
    first = ch["scenes"][0]
    line = (first.get("shots") or [{}])[0].get("say") or first.get("narration", "")
    log(f"  new opening line: {line}")
    return script


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


def shot_starts(shots: list[dict], sentences: list[dict], narration: str) -> list[float]:
    """Map each shot's first word to a time in the scene audio (via sentence timings)."""
    spans, cur = [], 0
    for x in sentences:  # character span of every sentence inside the narration
        i = narration.find(x["text"][:20], cur)
        i = cur if i < 0 else i
        spans.append((i, i + len(x["text"]), x["start"], x["end"]))
        cur = i + len(x["text"])
    out, off = [], 0
    for sh in shots:
        if not sh["say"]:
            out.append(None)
            continue
        t = 0.0
        for a, b, st, en in spans:
            if off < b or (a, b, st, en) == spans[-1]:
                frac = min(1.0, max(0.0, (off - a) / max(1, b - a)))
                t = st + frac * (en - st)
                break
        out.append(t)
        off += len(sh["say"]) + 1
    return out


def stage_voice(p: Project, log) -> None:
    v = load_config()["voice"]
    fps = load_config()["video"]["fps"]
    scenes = p.scenes()
    adir = p.path("audio")
    adir.mkdir(exist_ok=True)
    timeline = {"scenes": [], "chapters": []}
    t = 0.0
    lead = 0.1
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
        dur = len(audio) / SR if s["narration"].strip() else 0.0
        shots = s["shots"]
        # a leading silent title card gets a short beat before the voice starts
        pre = 1.3 if shots[0]["visual"]["type"] == "title" and not shots[0]["say"] else 0.0
        offset = lead + pre
        pause = v["pause_after_chapter"] if s["last_in_chapter"] else v["pause_after_scene"]
        length = offset + dur + pause
        if shots[0]["visual"]["type"] == "title":
            length = max(length, 1.8)
        if s["index"] == len(scenes) - 1:
            length = max(length, 20.0)  # YouTube end screen needs 5-20s
        frames = math.ceil(length * fps)
        starts = shot_starts(shots, sentences, s["narration"])
        shot_t, first_spoken = [], True
        for st in starts:
            if st is None:
                shot_t.append(0.0 if not shot_t else shot_t[-1])
            elif first_spoken:
                shot_t.append(pre if pre else 0.0)
                first_spoken = False
            else:
                shot_t.append(round(offset + st - 0.05, 3))
        shot_t = [max(a, shot_t[i - 1] if i else 0.0) for i, a in enumerate(shot_t)]
        if s["first_in_chapter"]:
            timeline["chapters"].append({"title": s["chapter_title"], "start": round(t, 3)})
        timeline["scenes"].append({
            "index": s["index"], "start": round(t, 4), "frames": frames, "voice_offset": offset,
            "audio_seconds": round(dur, 3), "shots": shot_t,
            "sentences": [{**x, "start": x["start"] + offset, "end": x["end"] + offset} for x in sentences],
        })
        t += frames / fps
        if (s["index"] + 1) % 10 == 0:
            log(f"  voiced {s['index'] + 1}/{len(scenes)} scenes")
    timeline["total_seconds"] = round(t, 3)
    p.write_json("timeline.json", timeline)
    mins = t / 60
    n = sum(len(x["shots"]) for x in timeline["scenes"])
    log(f"  narration done: video length {int(mins)}:{int(t % 60):02d}, {n} shots (a cut every {t / max(1, n):.1f}s on average)")
    if mins < load_config()["script"]["min_video_minutes"]:
        log(f"  !! WARNING: video is under {load_config()['script']['min_video_minutes']} minutes. Re-run the script stage to expand it.")


def shot_image_path(p: Project, scene: int, shot: int, side: str = "") -> Path | None:
    for ext in ("png", "jpg"):
        f = p.path("images", f"s{scene:03d}_{shot:02d}{side}.{ext}")
        if f.exists():
            return f
    return None


def _shot_durations(p: Project) -> dict[tuple[int, int], float]:
    tl = p.read_json("timeline.json") or {"scenes": []}
    fps = load_config()["video"]["fps"]
    out = {}
    for sc in tl["scenes"]:
        starts = sc.get("shots") or [0.0]
        end = sc["frames"] / fps
        for j, st in enumerate(starts):
            out[(sc["index"], j)] = max(0.5, (starts[j + 1] if j + 1 < len(starts) else end) - st)
    return out


def stage_visuals(p: Project, log) -> None:
    from . import stock

    icfg = load_config()["images"]
    scfg = load_config().get("stock", {})
    idir = p.path("images")
    idir.mkdir(exist_ok=True)
    credits = p.read_json("credits.json", {}) or {}
    used = {c.get("source_id") for c in credits.values() if c.get("source_id")}
    durs = _shot_durations(p)
    ai_budget = int(icfg.get("max_ai_images", 25))
    ai_used = sum(1 for f in idir.glob("s*_*.png"))
    fps = load_config()["video"]["fps"]

    def have(i, j, side=""):
        return shot_image_path(p, i, j, side) is not None or p.path("images", f"s{i:03d}_{j:02d}{side}.mp4").exists()

    def try_ai(i, j, side, prompt, v) -> bool:
        nonlocal ai_used
        if icfg["backend"] == "none" or ai_used >= ai_budget:
            return False
        seed = 1000 + i * 37 + j * 7 + (13 if side == "b" else 0) + 7919 * int(v.get("seed_bump", 0))
        try:
            if generate_image(prompt, idir / f"s{i:03d}_{j:02d}{side}.png", seed=seed):
                ai_used += 1
                return True
        except ImageGenError as e:
            log(f"    AI image failed ({str(e).splitlines()[0]}) - continuing without it")
        return False

    # ---- collect the work
    stock_jobs, ai_jobs = [], []
    for s in p.scenes():
        for j, sh in enumerate(s["shots"]):
            v, i = sh["visual"], s["index"]
            if v["type"] in ("broll", "archive") and not have(i, j):
                stock_jobs.append({"id": f"{i}:{j}", "i": i, "j": j, "side": "", "v": v, "say": sh["say"],
                                   "kind": v["type"], "query": v.get("query") or v.get("prompt", "")[:60]})
            elif v["type"] == "split":
                for side, key in (("a", "left"), ("b", "right")):
                    if not have(i, j, side):
                        sd = v[key]
                        stock_jobs.append({"id": f"{i}:{j}{side}", "i": i, "j": j, "side": side, "v": v, "say": sd.get("label") or sh["say"],
                                           "kind": "split", "query": sd.get("query") or sd.get("label") or sd["prompt"][:60], "prompt": sd["prompt"]})
            elif v["type"] == "illustration" and not have(i, j):
                ai_jobs.append((i, j, v, sh["say"]))
    log(f"  {len(stock_jobs)} shots from stock/archive, {len(ai_jobs)} AI illustrations "
        f"(AI: {icfg['backend']}, cap {ai_budget}; Pexels {'on' if stock.key('pexels_key') else 'off'}, Pixabay {'on' if stock.key('pixabay_key') else 'off'})")

    # ---- stock: search, let Claude pick, download
    n_c = int(scfg.get("candidates", 6))
    batch = []

    def flush():
        if not batch:
            return
        if scfg.get("vision_pick", True):
            picks = stock.claude_pick([{"id": b["id"], "say": b["say"], "query": b["query"], "cands": b["cands"]} for b in batch], log)
        else:
            picks = {b["id"]: 0 for b in batch}
        for b in batch:
            k = picks.get(b["id"], 0)
            ok = False
            if k >= 0:
                order = [k] + [x for x in range(len(b["cands"])) if x != k] if not scfg.get("vision_pick", True) else [k]
                for idx in order:
                    c = b["cands"][idx]
                    base = idir / f"s{b['i']:03d}_{b['j']:02d}{b['side']}"
                    if c["kind"] == "video":
                        ok = stock.download_clip(c["url"], base.with_suffix(".mp4"), durs.get((b["i"], b["j"]), 4.0) + 0.3, fps=fps)
                    else:
                        ok = stock.download_image(c["url"], base.with_suffix(".jpg"))
                    if ok:
                        credits[b["id"]] = {**c["credit"], "source_id": c["id"]}
                        used.add(c["id"])
                        log(f"    shot {b['id']}: {c['kind']} - {c['credit']['title'][:60]}")
                        break
            if not ok:
                prompt = b.get("prompt") or b["v"].get("prompt") or b["say"]
                if try_ai(b["i"], b["j"], b["side"], prompt, b["v"]):
                    log(f"    shot {b['id']}: no good stock match -> AI illustration")
                else:
                    log(f"    shot {b['id']}: no good match -> animated caption")
        p.write_json("credits.json", credits)
        batch.clear()

    for k, job in enumerate(stock_jobs, 1):
        exclude = used | set(job["v"].get("reject", []))
        try:
            cands = stock.candidates(job["query"], "archive" if job["kind"] == "archive" else "broll",
                                     job["v"].get("prefer", "any") if job["kind"] == "broll" else "photo", n_c, exclude, log)
        except Exception as e:  # noqa: BLE001
            log(f"    search failed for '{job['query']}': {e}")
            cands = []
        if not cands:
            batch.append({**job, "cands": []})
        else:
            batch.append({**job, "cands": cands})
        if len(batch) >= 6:
            log(f"  [{k}/{len(stock_jobs)}] picking the best footage...")
            flush()
    flush()

    # ---- AI illustrations (only for things no camera could capture)
    for k, (i, j, v, say) in enumerate(ai_jobs, 1):
        if try_ai(i, j, "", v.get("prompt") or say, v):
            log(f"  [{k}/{len(ai_jobs)}] AI illustration for shot {i}:{j}")
            continue
        # no AI available or over budget: try a real photo instead
        try:
            cands = stock.candidates(v.get("query") or v.get("prompt", "")[:60], "broll", "photo", 1, used, log)
        except Exception:  # noqa: BLE001
            cands = []
        if cands and stock.download_image(cands[0]["url"], idir / f"s{i:03d}_{j:02d}.jpg"):
            credits[f"{i}:{j}"] = {**cands[0]["credit"], "source_id": cands[0]["id"]}
            used.add(cands[0]["id"])
    p.write_json("credits.json", credits)
    log(f"  visuals done ({ai_used} AI images used)")


def stage_storyboard(p: Project, log) -> None:
    from .render.engine import render_storyboard

    render_storyboard(p, log)
    scenes, tl = p.scenes(), p.read_json("timeline.json")
    rows = []
    for s, t in zip(scenes, tl["scenes"]):
        for j, sh in enumerate(s["shots"]):
            st = t["start"] + t["shots"][j]
            mm, ss = divmod(int(st), 60)
            v = sh["visual"]
            detail = v.get("prompt") or v.get("query") or v.get("text") or v.get("line") or v.get("label") or v.get("heading") or ""
            rows.append(
                f"<div class=card><img src='storyboard/scene_{s['index']:03d}_{j:02d}.jpg'><div><b>#{s['index']}.{j} {mm}:{ss:02d} - {v['type']}</b>"
                f" <i>{s['chapter_title']}</i><p>{sh['say']}</p><small>{detail}</small></div></div>"
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
            if bg is None and c.get("query"):
                from . import stock

                jp = p.path("images", f"thumb_bg_{n}.jpg")
                try:
                    cands = stock.candidates(c["query"], "broll", "photo", 1, set(), log)
                except Exception:  # noqa: BLE001
                    cands = []
                if jp.exists() or (cands and stock.download_image(cands[0]["url"], jp)):
                    bg = Image.open(jp).convert("RGB")
            if bg is None:
                try:
                    if generate_image(c.get("prompt", meta["best_title"]), bgp, seed=77 + n):
                        bg = Image.open(bgp).convert("RGB")
                except ImageGenError as e:
                    log(f"  thumbnail bg generation failed ({e}); using built-in art")
            if bg is None:
                # reuse the most striking scene image if any
                imgs = sorted(f for f in p.path("images").glob("s[0-9]*_*.*") if f.suffix in (".jpg", ".png"))
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
