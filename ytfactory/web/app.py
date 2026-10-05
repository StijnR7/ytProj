"""Local web dashboard (Flask). Runs only on your machine: http://127.0.0.1:7860"""
from __future__ import annotations

import json
import threading
import traceback
import webbrowser

from flask import Flask, abort, jsonify, request, send_from_directory

from ..config import CHANNEL_DIR, load_config
from ..project import STAGES, Project, normalize_script, validate_script, word_count
from .. import pipeline

app = Flask(__name__, static_folder="static", template_folder="templates")

_job_lock = threading.Lock()
JOB: dict = {"running": False, "label": "", "slug": None, "error": None}


def start_job(label: str, slug: str | None, fn) -> bool:
    with _job_lock:
        if JOB["running"]:
            return False
        JOB.update(running=True, label=label, slug=slug, error=None)

    def runner():
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            JOB["error"] = str(e)
            traceback.print_exc()
        finally:
            JOB["running"] = False

    threading.Thread(target=runner, daemon=True).start()
    return True


def _project(slug: str) -> Project:
    p = Project(slug)
    if not p.meta_path.exists():
        abort(404)
    return p


@app.get("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


@app.get("/api/state")
def state():
    cfg = load_config()
    projects = [{"slug": p.slug, "topic": p.meta["topic"], "category": p.meta.get("category"), "stages": p.meta["stages"]} for p in Project.all()]
    return jsonify(channel=cfg["channel"], ideas=pipeline.load_ideas(), projects=projects, stages=STAGES, job=JOB,
                   has_branding=(CHANNEL_DIR / "profile_picture.png").exists())


@app.post("/api/ideas/generate")
def ideas_generate():
    n = int((request.json or {}).get("n", 12))
    ok = start_job("Brainstorming ideas", None, lambda: pipeline.generate_ideas(n))
    return jsonify(ok=ok)


@app.post("/api/projects")
def create_project():
    d = request.json or {}
    if d.get("idea") is not None:
        ideas = pipeline.load_ideas()
        idea = ideas[int(d["idea"])]
        idea["used"] = True
        pipeline.save_ideas(ideas)
        p = Project.create(idea["title"], idea.get("category", ""), idea.get("angle", ""))
    else:
        if not d.get("topic"):
            return jsonify(error="topic required"), 400
        p = Project.create(d["topic"], d.get("category", ""), d.get("angle", ""))
    return jsonify(slug=p.slug)


@app.get("/api/projects/<slug>")
def project_detail(slug):
    p = _project(slug)
    script = p.read_json("script.json")
    log = p.path("log.txt").read_text(encoding="utf-8")[-6000:] if p.path("log.txt").exists() else ""
    out = p.path("output")
    files = sorted(f.name for f in out.iterdir()) if out.exists() else []
    texts = {}
    for name in ("title.txt", "description.txt", "tags.txt", "pinned_comment.txt"):
        if (out / name).exists():
            texts[name] = (out / name).read_text(encoding="utf-8")
    scenes = []
    if script:
        tl = p.read_json("timeline.json") or {}
        tls = tl.get("scenes", [])
        for s in p.scenes():
            i = s["index"]
            st = tls[i]["start"] if i < len(tls) else None
            shot_t = tls[i].get("shots", []) if i < len(tls) else []
            shots = []
            for j, sh in enumerate(s["shots"]):
                prev = p.path("storyboard", f"scene_{i:03d}_{j:02d}.jpg")
                img = next(iter(sorted(p.path("images").glob(f"s{i:03d}_{j:02d}*.*"))), None) if p.path("images").exists() else None
                shots.append({
                    "say": sh["say"], "visual": sh["visual"], "fx": sh.get("fx", "none"),
                    "start": (st + shot_t[j]) if st is not None and j < len(shot_t) else None,
                    "preview": f"storyboard/{prev.name}" if prev.exists() else None,
                    "image": f"images/{img.name}" if img else None,
                })
            scenes.append({"index": i, "chapter": s["chapter_title"], "narration": s["narration"], "mascot": s["mascot"], "start": st, "shots": shots})
    return jsonify(
        meta=p.meta, script=script, words=word_count(script) if script else 0, scenes=scenes, log=log, files=files,
        texts=texts, length=(p.read_json("timeline.json") or {}).get("total_seconds"),
        research=p.path("research.md").read_text(encoding="utf-8") if p.path("research.md").exists() else "",
    )


@app.post("/api/projects/<slug>/run")
def project_run(slug):
    p = _project(slug)
    d = request.json or {}
    start, stop, force = d.get("start"), d.get("stop"), bool(d.get("force"))
    ok = start_job(f"{p.meta['topic']}: {start or 'start'} -> {stop or 'end'}", slug, lambda: pipeline.run(p, start, stop, force))
    return jsonify(ok=ok)


@app.post("/api/projects/<slug>/script")
def save_script(slug):
    p = _project(slug)
    try:
        script = json.loads(request.json["script"])
        validate_script(script)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=str(e)), 400
    script = normalize_script(script, p.meta.get("category", ""))
    p.write_json("script.json", script)
    m = p.meta
    for s in STAGES[STAGES.index("voice"):]:
        if m["stages"].get(s) == "done":
            m["stages"][s] = "stale"
    p.save_meta(m)
    return jsonify(ok=True, words=word_count(script))


@app.post("/api/projects/<slug>/scene/<int:idx>/shot/<int:shot>/reroll")
def reroll(slug, idx, shot):
    p = _project(slug)
    for f in p.path("images").glob(f"s{idx:03d}_{shot:02d}*.*"):
        f.unlink()
    credits = p.read_json("credits.json", {}) or {}
    for k in [k for k in credits if k.startswith(f"{idx}:{shot}")]:
        credits.pop(k)
    p.write_json("credits.json", credits)
    script = p.read_json("script.json")
    k = 0
    for ch in script["chapters"]:
        for sc in ch["scenes"]:
            if k == idx and shot < len(sc["shots"]):
                v = sc["shots"][shot]["visual"]
                v["seed_bump"] = int(v.get("seed_bump", 0)) + 1
                new_prompt = (request.json or {}).get("prompt")
                if new_prompt:
                    if v["type"] == "closeup" or v["type"] == "kinetic":  # upgrade to a real illustration
                        sc["shots"][shot]["visual"] = v = {"type": "illustration", "prompt": new_prompt, "camera": "zoom_in", "seed_bump": v["seed_bump"]}
                    else:
                        v["prompt"] = new_prompt
            k += 1
    p.write_json("script.json", script)
    ok = start_job(f"Re-rolling image for scene {idx} shot {shot}", slug, lambda: pipeline.run(p, "visuals", "storyboard"))
    return jsonify(ok=ok)


@app.post("/api/branding")
def branding():
    from ..thumbnails import make_branding

    ok = start_job("Generating channel art", None, make_branding)
    return jsonify(ok=ok)


@app.get("/files/<slug>/<path:sub>")
def files(slug, sub):
    p = _project(slug)
    return send_from_directory(p.dir, sub)


@app.get("/channel/<path:sub>")
def channel_files(sub):
    return send_from_directory(CHANNEL_DIR, sub)


def serve(port: int = 7860, open_browser: bool = True) -> None:
    url = f"http://127.0.0.1:{port}"
    print(f"Dashboard running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
