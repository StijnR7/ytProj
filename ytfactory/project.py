"""A video project = one folder under projects/ holding every stage's output."""
from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from .config import PROJECTS

STAGES = [
    "research",
    "script",
    "metadata",
    "voice",
    "visuals",
    "storyboard",
    "render",
    "thumbnails",
    "package",
]

VISUAL_TYPES = {"illustration", "archive", "title", "stat", "timeline", "list", "comparison", "quote", "mascot"}
MASCOT_EXPRESSIONS = {"none", "happy", "surprised", "thinking", "excited", "worried", "pointing"}
THEMES = {"space", "history", "animals", "hypotheticals", "brand"}


def slugify(text: str, maxlen: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:maxlen].strip("-") or "video"


def theme_for(category: str) -> str:
    c = (category or "").lower()
    for key in ("space", "history", "animal", "hypothetical"):
        if key in c:
            return {"animal": "animals", "hypothetical": "hypotheticals"}.get(key, key)
    return "brand"


class Project:
    def __init__(self, slug: str):
        self.slug = slug
        self.dir = PROJECTS / slug
        self.meta_path = self.dir / "project.json"

    # ------------------------------------------------------------- creation
    @classmethod
    def create(cls, topic: str, category: str = "", angle: str = "") -> "Project":
        PROJECTS.mkdir(parents=True, exist_ok=True)
        base = slugify(topic)
        slug, i = base, 2
        while (PROJECTS / slug).exists():
            slug, i = f"{base}-{i}", i + 1
        p = cls(slug)
        p.dir.mkdir(parents=True)
        p.save_meta(
            {
                "topic": topic,
                "category": category or "general",
                "angle": angle,
                "created": time.strftime("%Y-%m-%d %H:%M"),
                "stages": {s: "pending" for s in STAGES},
            }
        )
        return p

    @classmethod
    def all(cls) -> list["Project"]:
        if not PROJECTS.exists():
            return []
        ps = [cls(d.name) for d in PROJECTS.iterdir() if (d / "project.json").exists()]
        return sorted(ps, key=lambda p: p.meta.get("created", ""), reverse=True)

    # ------------------------------------------------------------- metadata
    @property
    def meta(self) -> dict:
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def save_meta(self, meta: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    def set_stage(self, stage: str, status: str) -> None:
        m = self.meta
        m.setdefault("stages", {})[stage] = status
        self.save_meta(m)

    def stage_status(self, stage: str) -> str:
        return self.meta.get("stages", {}).get(stage, "pending")

    def reset_from(self, stage: str) -> None:
        m = self.meta
        for s in STAGES[STAGES.index(stage):]:
            m["stages"][s] = "pending"
        self.save_meta(m)

    @property
    def theme(self) -> str:
        return theme_for(self.meta.get("category", ""))

    # ------------------------------------------------------------- files
    def path(self, *parts: str) -> Path:
        return self.dir.joinpath(*parts)

    def read_json(self, name: str, default: Any = None) -> Any:
        p = self.path(name)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))

    def write_json(self, name: str, data: Any) -> None:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(self.path("log.txt"), "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ------------------------------------------------------------- script helpers
    def scenes(self) -> list[dict]:
        """Flattened scene list with chapter info attached."""
        script = self.read_json("script.json")
        out = []
        for ci, ch in enumerate(script["chapters"]):
            for si, sc in enumerate(ch["scenes"]):
                s = dict(sc)
                s["chapter_index"] = ci
                s["chapter_title"] = ch["title"]
                s["first_in_chapter"] = si == 0
                s["last_in_chapter"] = si == len(ch["scenes"]) - 1
                s["index"] = len(out)
                out.append(s)
        return out


# ----------------------------------------------------------------- validation

def word_count(script: dict) -> int:
    return sum(len(s.get("narration", "").split()) for c in script.get("chapters", []) for s in c.get("scenes", []))


def validate_script(script: Any) -> None:
    if not isinstance(script, dict) or not isinstance(script.get("chapters"), list) or not script["chapters"]:
        raise ValueError("script must be an object with a non-empty 'chapters' list")
    for ci, ch in enumerate(script["chapters"]):
        if not ch.get("title") or not isinstance(ch.get("scenes"), list) or not ch["scenes"]:
            raise ValueError(f"chapter {ci} needs a title and scenes")
        for si, sc in enumerate(ch["scenes"]):
            if not str(sc.get("narration", "")).strip():
                raise ValueError(f"chapter {ci} scene {si} has no narration")
            v = sc.get("visual")
            if not isinstance(v, dict) or v.get("type") not in VISUAL_TYPES:
                raise ValueError(f"chapter {ci} scene {si} has an invalid visual: {v}")


def normalize_script(script: dict, category: str) -> dict:
    """Fill defaults and repair small mistakes so the renderer never crashes."""
    for ch in script["chapters"]:
        for sc in ch["scenes"]:
            sc["narration"] = " ".join(str(sc["narration"]).split())
            m = str(sc.get("mascot") or "none").lower()
            sc["mascot"] = m if m in MASCOT_EXPRESSIONS else "none"
            sc["on_screen_text"] = str(sc.get("on_screen_text") or "")[:60]
            v = sc["visual"]
            t = v["type"]
            if v.get("theme") not in THEMES:
                v.pop("theme", None)
            if t in ("illustration", "archive"):
                v.setdefault("prompt", sc["narration"][:200])
                if v.get("camera") not in ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down"):
                    v["camera"] = "zoom_in"
            if t == "archive":
                v.setdefault("query", v.get("prompt", "")[:80])
                v.setdefault("caption", "")
            if t == "title":
                v["text"] = str(v.get("text") or ch["title"])
                v.setdefault("subtitle", "")
            if t == "stat":
                try:
                    v["value"] = float(str(v.get("value", 0)).replace(",", ""))
                except ValueError:
                    v["value"] = 0.0
                v.setdefault("prefix", "")
                v.setdefault("suffix", "")
                v.setdefault("label", "")
                v["decimals"] = int(v.get("decimals") or (0 if v["value"] == int(v["value"]) else 1))
            if t == "timeline":
                ev = [e for e in v.get("events", []) if isinstance(e, dict)][:6]
                v["events"] = ev or [{"year": "?", "label": ch["title"]}]
            if t == "list":
                v["items"] = [str(i) for i in v.get("items", [])][:5] or [ch["title"]]
                v.setdefault("heading", "")
            if t == "comparison":
                items = []
                for it in v.get("items", [])[:5]:
                    try:
                        items.append({"label": str(it["label"]), "value": float(it["value"]), "unit": str(it.get("unit", ""))})
                    except (KeyError, ValueError, TypeError):
                        pass
                if len(items) < 2:
                    sc["visual"] = {"type": "mascot", "line": v.get("heading") or ch["title"]}
                else:
                    v["items"] = items
                    v.setdefault("heading", "")
            if t == "quote":
                v.setdefault("text", "")
                v.setdefault("author", "")
            if t == "mascot":
                v["line"] = str(v.get("line") or "")
    script.setdefault("category", category)
    return script
