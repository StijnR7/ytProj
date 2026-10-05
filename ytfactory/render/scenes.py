"""Scene renderers. Each scene is a pure function of time: frame(t) -> RGB image."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .backgrounds import Backdrop, get_theme
from .common import (
    CREAM, INK, ORANGE, WHITE, YELLOW, apply_vignette, clamp, cover, drop_shadow, ease_in_out_sine,
    ease_out_back, ease_out_cubic, fit_text, font, format_number, paste, progress, rounded_box,
    scale_sprite, text_sprite,
)
from .mascot import ZibActor


@dataclass
class SceneContext:
    size: tuple = (1920, 1080)
    fps: int = 30
    duration: float = 5.0
    theme: str = "brand"
    seed: int = 0
    image: Image.Image | None = None
    envelope: np.ndarray | None = None          # Zib mouth level (0-4) per frame
    sentences: list = field(default_factory=list)  # [{text,start,end}] relative to scene start
    chapter_number: int = 1
    is_last: bool = False
    channel_name: str = "Probe Into It"
    burn_captions: bool = False
    image2: Image.Image | None = None             # right-hand image of a split shot
    shots: list = field(default_factory=list)     # [{spec, start, image, image2, video}] for multi-shot scenes
    video: str | None = None                      # stock clip, already normalised to output size/fps


class Scene:
    corner_mascot = True

    def __init__(self, spec: dict, ctx: SceneContext):
        self.spec, self.ctx = spec, ctx
        self.v = spec.get("visual", {})
        self.W, self.H = ctx.size
        self.theme = get_theme(self.v.get("theme") or ctx.theme)
        self._backdrop = None
        self.prepare()
        expr = self.spec.get("mascot", "none")
        self.corner = None
        if self.corner_mascot and expr and expr != "none":
            self.corner = ZibActor(int(self.H * 0.22), expr, seed=ctx.seed, envelope=ctx.envelope, fps=ctx.fps, enter_at=0.5)
        label = spec.get("on_screen_text") or ""
        self.label = self._label_sprite(label) if label and self.v.get("type") in ("illustration", "archive") else None

    # ---- hooks
    def prepare(self) -> None:
        pass

    def render(self, t: float) -> Image.Image:
        return self.backdrop.frame(t)

    @property
    def backdrop(self) -> Backdrop:
        if self._backdrop is None:
            self._backdrop = Backdrop(self.theme.name, self.ctx.size, self.ctx.seed)
        return self._backdrop

    # ---- shared overlays
    def _label_sprite(self, text: str) -> Image.Image:
        txt = text_sprite(text.upper(), "heading", int(self.H * 0.042), fill=INK)
        box = rounded_box((txt.width + 70, txt.height + 18), 22, (*CREAM, 245))
        bar = rounded_box((14, txt.height - 6), 7, (*ORANGE, 255))
        box.alpha_composite(bar, (22, 12))
        box.alpha_composite(txt, (48, 9))
        return drop_shadow(box, 14, 0.35, (0, 6))

    def frame(self, t: float) -> Image.Image:
        f = self.render(t)
        d = self.ctx.duration
        if self.label is not None:
            p = ease_out_cubic(progress(t, 0.45, 0.5))
            out = ease_out_cubic(progress(t, d - 0.5, 0.4))
            x = 60 - (1 - p) * (self.label.width + 80) - out * (self.label.width + 80)
            paste(f, self.label, (x, self.H - self.label.height - 60), opacity=p)
        if self.corner is not None:
            self.corner.draw(f, self.W - self.H * 0.16, self.H - 20, t)
        if self.ctx.burn_captions:
            self._caption(f, t)
        return f

    def _caption(self, f: Image.Image, t: float) -> None:
        for s in self.ctx.sentences:
            if s["start"] <= t <= s["end"] + 0.1:
                spr = text_sprite(s["text"], "body", int(self.H * 0.04), fill=WHITE, stroke=5, stroke_fill=(10, 10, 20), max_w=int(self.W * 0.75))
                paste(f, spr, (self.W / 2, self.H - 40), anchor="bc")
                return


# ------------------------------------------------------------------ image scenes
class IllustrationScene(Scene):
    ZOOM = 1.24

    def prepare(self):
        self.no_image = self.ctx.image is None
        img = self.ctx.image or Backdrop(self.theme.name, (1344, 768), self.ctx.seed).frame(0)
        self.src = cover(img, self.ctx.size, self.ZOOM)
        if self.no_image:
            # No illustration available: become a kinetic-caption scene so the screen is never empty.
            if self.spec.get("mascot", "none") == "none":
                self.spec = {**self.spec, "mascot": ("thinking", "happy", "pointing", "surprised")[self.ctx.seed % 4]}
            self._caps = {}

    def _caption_sprite(self, i: int, text: str) -> Image.Image:
        if i not in self._caps:
            fnt, lines, lh = fit_text(text, "heading", int(self.W * 0.66), int(self.H * 0.5), int(self.H * 0.075), 30)
            spr = Image.new("RGBA", (int(self.W * 0.66) + 40, lh * len(lines) + 40), (0, 0, 0, 0))
            d = ImageDraw.Draw(spr)
            words = text.split()
            key = max(words, key=lambda w: len(w.strip(".,!?;:")) if w[:1].isalnum() else 0) if words else ""
            for li, line in enumerate(lines):
                x = (spr.width - fnt.getlength(line)) / 2
                for w in line.split():
                    col = self.theme.accent if w == key else self.theme.fg
                    d.text((x, 20 + li * lh), w, font=fnt, fill=col, stroke_width=3, stroke_fill=(0, 0, 0, 90))
                    x += fnt.getlength(w + " ")
            self._caps[i] = drop_shadow(spr, 14, 0.5, (0, 6))
        return self._caps[i]

    def _box(self, t):
        W, H, Z = self.W, self.H, self.ZOOM
        p = ease_out_cubic(t / max(0.1, self.ctx.duration)) if self.ctx.duration < 6 else ease_in_out_sine(t / max(0.1, self.ctx.duration))
        cam = self.v.get("camera", "zoom_in")
        SW, SH = self.src.width, self.src.height
        if cam in ("zoom_in", "zoom_out"):
            z = (Z + (1 - Z) * p) if cam == "zoom_in" else (1 + (Z - 1) * p)
            w, h = min(SW, W * z), min(SH, H * z)
            return ((SW - w) / 2, (SH - h) / 2, (SW + w) / 2, (SH + h) / 2)
        w, h = W * 1.04, H * 1.04
        mx, my = SW - w, SH - h
        x, y = mx / 2, my / 2
        if cam == "pan_left":
            x = mx * (1 - p)
        elif cam == "pan_right":
            x = mx * p
        elif cam == "pan_up":
            y = my * (1 - p)
        elif cam == "pan_down":
            y = my * p
        return (x, y, x + w, y + h)

    def render(self, t):
        f = self.src.resize(self.ctx.size, Image.BILINEAR, box=self._box(t))
        f = apply_vignette(f, 0.35)
        if not self.no_image:
            self.backdrop.draw_particles(f, t, 0.45)
        if self.no_image and self.ctx.sentences:
            sents = self.ctx.sentences
            i = max([k for k, x in enumerate(sents) if x["start"] - 0.1 <= t] or [0])
            k = ease_out_cubic(progress(t, sents[i]["start"] - 0.1, 0.35))
            spr = self._caption_sprite(i, sents[i]["text"])
            paste(f, spr, (self.W * 0.47, self.H * 0.44 + (1 - k) * 25), opacity=k, anchor="c")
        return f


class ArchiveScene(Scene):
    def prepare(self):
        if self.ctx.image is None:
            self.fallback = IllustrationScene(self.spec, self.ctx)
            return
        self.fallback = None
        img = self.ctx.image
        bg = cover(img, (self.W // 4, self.H // 4), 1.1).filter(ImageFilter.GaussianBlur(8))
        bg = Image.blend(bg, Image.new("RGB", bg.size, (10, 14, 30)), 0.55)
        self.bg = bg.resize((int(self.W * 1.1), int(self.H * 1.1)), Image.BILINEAR)
        cap = self.v.get("caption", "")
        max_w, max_h = self.W * 0.72, self.H * (0.66 if cap else 0.78)
        k = min(max_w / img.width, max_h / img.height)
        photo = img.resize((int(img.width * k), int(img.height * k)), Image.LANCZOS).convert("RGBA")
        border = 14
        framed = Image.new("RGBA", (photo.width + border * 2, photo.height + border * 2), (*CREAM, 255))
        framed.paste(photo, (border, border))
        self.photo = drop_shadow(framed, 26, 0.6, (0, 16))
        self.caption = None
        if cap:
            txt = text_sprite(cap, "body_semi", int(self.H * 0.034), fill=INK, max_w=int(self.W * 0.6))
            box = rounded_box((txt.width + 50, txt.height + 16), 18, (*CREAM, 240))
            box.alpha_composite(txt, (25, 8))
            self.caption = box

    def render(self, t):
        if self.fallback:
            return self.fallback.render(t)
        d = self.ctx.duration
        p = ease_in_out_sine(t / max(0.1, d))
        dx = (self.bg.width - self.W) * p
        f = self.bg.crop((int(dx), int((self.bg.height - self.H) / 2), int(dx) + self.W, int((self.bg.height - self.H) / 2) + self.H))
        enter = ease_out_back(progress(t, 0.0, 0.6))
        spr = scale_sprite(self.photo, 0.85 + 0.15 * enter) if enter < 0.999 else self.photo
        cy = self.H * (0.45 if self.caption else 0.5) + math.sin(t * 0.5) * 4
        paste(f, spr, (self.W / 2 + (p - 0.5) * 30, cy), opacity=clamp(enter * 1.5), anchor="c")
        if self.caption is not None:
            cp = ease_out_cubic(progress(t, 0.5, 0.5))
            paste(f, self.caption, (self.W / 2, self.H - 40 + (1 - cp) * 60), opacity=cp, anchor="bc")
        return f


# ------------------------------------------------------------------ graphic scenes
class TitleScene(Scene):
    corner_mascot = False

    def prepare(self):
        th = self.theme
        title = self.v.get("text", "")
        f, lines, lh = fit_text(title.upper(), "display", int(self.W * 0.72), int(self.H * 0.4), int(self.H * 0.15), 40)
        self.words = []  # (sprite, x, y, delay)
        y0 = self.H * 0.5 - (lh * len(lines)) / 2
        i = 0
        for li, line in enumerate(lines):
            ws = line.split()
            sprites = [text_sprite(w, "display", f.size, fill=th.fg, stroke=0, shadow=10) for w in ws]
            space = f.getlength(" ")
            total = sum(f.getlength(w) for w in ws) + space * (len(ws) - 1)
            x = self.W * 0.56 - total / 2
            for s, w in zip(sprites, ws):
                self.words.append((s, x + f.getlength(w) / 2, y0 + li * lh + lh / 2, 0.35 + i * 0.12))
                x += f.getlength(w) + space
                i += 1
        self.kicker = text_sprite(f"CHAPTER {self.ctx.chapter_number}", "heading", int(self.H * 0.045), fill=th.accent)
        self.kicker_y = y0 - self.H * 0.13
        sub = self.v.get("subtitle", "")
        self.sub = text_sprite(sub, "body_semi", int(self.H * 0.042), fill=th.fg, max_w=int(self.W * 0.6)) if sub else None
        self.sub_y = y0 + lh * len(lines) + self.H * 0.06
        self.zib = ZibActor(int(self.H * 0.34), "excited", seed=self.ctx.seed, envelope=self.ctx.envelope, fps=self.ctx.fps, enter="left", enter_at=0.2)

    def render(self, t):
        f = self.backdrop.frame(t)
        d = ImageDraw.Draw(f)
        p = ease_out_cubic(progress(t, 0.15, 0.6))
        bar_w = int(self.W * 0.5 * p)
        d.rounded_rectangle([self.W * 0.56 - bar_w / 2, self.kicker_y + 70, self.W * 0.56 + bar_w / 2, self.kicker_y + 80], 5, fill=self.theme.accent)
        paste(f, self.kicker, (self.W * 0.56, self.kicker_y + 30), opacity=p, anchor="c")
        for s, x, y, delay in self.words:
            k = ease_out_back(progress(t, delay, 0.45))
            if k > 0.01:
                paste(f, scale_sprite(s, k), (x, y), opacity=clamp(k * 2), anchor="c")
        if self.sub is not None:
            sp = ease_out_cubic(progress(t, 0.9, 0.5))
            paste(f, self.sub, (self.W * 0.56, self.sub_y + (1 - sp) * 30), opacity=sp, anchor="c")
        self.zib.draw(f, self.W * 0.14, self.H * 0.82, t)
        return f


class StatScene(Scene):
    corner_mascot = False

    def prepare(self):
        v = self.v
        self.value = float(v.get("value", 0))
        self.stat_label = text_sprite(v.get("label", ""), "heading_semi", int(self.H * 0.055), fill=self.theme.fg, max_w=int(self.W * 0.6), shadow=6)
        self.size_num = int(self.H * 0.2)
        final = f"{v.get('prefix', '')}{format_number(self.value, v.get('decimals', 0))}{v.get('suffix', '')}"
        while font("display", self.size_num).getlength(final) > self.W * 0.62 and self.size_num > 60:
            self.size_num -= 6
        expr = self.spec.get("mascot", "none")
        self.zib = ZibActor(int(self.H * 0.3), expr if expr != "none" else "surprised", seed=self.ctx.seed, envelope=self.ctx.envelope, fps=self.ctx.fps, enter="right", enter_at=1.4)

    def render(self, t):
        f = self.backdrop.frame(t)
        v = self.v
        cx, cy = self.W * 0.44, self.H * 0.45
        ring = ease_out_cubic(progress(t, 0.1, 0.8))
        d = ImageDraw.Draw(f, "RGBA")
        r = self.H * 0.33 * ring
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*self.theme.accent, 28))
        r2 = r * 0.82
        d.arc([cx - r2, cy - r2, cx + r2, cy + r2], -90 + t * 20, -90 + t * 20 + 300 * ring, fill=(*self.theme.accent, 140), width=6)
        count = ease_out_cubic(progress(t, 0.25, 1.8))
        txt = f"{v.get('prefix', '')}{format_number(self.value * count, v.get('decimals', 0))}{v.get('suffix', '')}"
        pop = 1 + 0.08 * math.sin(math.pi * clamp((t - 2.05) / 0.3)) if t > 2.05 else 1
        spr = text_sprite(txt, "display", int(self.size_num * pop), fill=self.theme.accent, stroke=0, shadow=12)
        paste(f, spr, (cx, cy), anchor="c")
        lp = ease_out_cubic(progress(t, 0.8, 0.5))
        paste(f, self.stat_label, (cx, cy + self.size_num * 0.75 + (1 - lp) * 30), opacity=lp, anchor="c")
        self.zib.draw(f, self.W * 0.84, self.H * 0.9, t)
        return f


class TimelineScene(Scene):
    def prepare(self):
        ev = self.v.get("events", [])
        n = len(ev)
        self.y = self.H * 0.52
        self.x0, self.x1 = self.W * 0.1, self.W * 0.9
        avail = max(1.0, self.ctx.duration - 1.5)
        step = min(1.8, avail / max(1, n))
        self.items = []
        for i, e in enumerate(ev):
            x = self.x0 + (self.x1 - self.x0) * (i + 0.5) / n
            year = text_sprite(str(e.get("year", "")), "display", int(self.H * 0.07), fill=self.theme.accent, shadow=6)
            lbl_txt = text_sprite(str(e.get("label", "")), "body", int(self.H * 0.032), fill=self.theme.card_text, max_w=int((self.x1 - self.x0) / n * 0.82))
            card = rounded_box((lbl_txt.width + 30, lbl_txt.height + 14), 16, self.theme.card)
            card.alpha_composite(lbl_txt, (15, 7))
            self.items.append((x, year, drop_shadow(card, 10, 0.3, (0, 5)), 0.9 + i * step, i % 2 == 0))

    def render(self, t):
        f = self.backdrop.frame(t)
        d = ImageDraw.Draw(f, "RGBA")
        p = ease_out_cubic(progress(t, 0.1, 0.9))
        d.rounded_rectangle([self.x0, self.y - 5, self.x0 + (self.x1 - self.x0) * p, self.y + 5], 5, fill=(*self.theme.fg, 200))
        for x, year, card, start, up in self.items:
            k = ease_out_back(progress(t, start, 0.45))
            if k <= 0.01:
                continue
            r = 18 * k
            d.ellipse([x - r - 6, self.y - r - 6, x + r + 6, self.y + r + 6], fill=(*self.theme.accent, 90))
            d.ellipse([x - r, self.y - r, x + r, self.y + r], fill=self.theme.accent, outline=WHITE, width=4)
            off = (1 - k) * 40
            if up:
                paste(f, year, (x, self.y - 40 - off), opacity=clamp(k), anchor="bc")
                paste(f, card, (x, self.y + 40 + card.height + off), opacity=clamp(k), anchor="bc")
            else:
                paste(f, year, (x, self.y + 40 + year.height + off), opacity=clamp(k), anchor="bc")
                paste(f, card, (x, self.y - 40 - off), opacity=clamp(k), anchor="bc")
        return f


class ListScene(Scene):
    def prepare(self):
        v = self.v
        items = v.get("items", [])
        self.heading = text_sprite(v.get("heading", ""), "heading", int(self.H * 0.07), fill=self.theme.fg, shadow=8, max_w=int(self.W * 0.8)) if v.get("heading") else None
        n = max(1, len(items))
        top = self.H * (0.3 if self.heading else 0.2)
        gap = min(self.H * 0.15, (self.H * 0.85 - top) / n)
        avail = max(1.0, self.ctx.duration * 0.75 - 0.6)
        self.rows = []
        for i, it in enumerate(items):
            txt = text_sprite(it, "body", int(self.H * 0.048), fill=self.theme.card_text, max_w=int(self.W * 0.55))
            row = rounded_box((int(self.W * 0.62), max(txt.height + 26, int(gap * 0.8))), 26, self.theme.card)
            badge = Image.new("RGBA", (row.height - 20, row.height - 20), (0, 0, 0, 0))
            ImageDraw.Draw(badge).ellipse([0, 0, badge.width - 1, badge.height - 1], fill=(*ORANGE, 255))
            num = text_sprite(str(i + 1), "heading", int(badge.height * 0.6), fill=WHITE)
            badge.alpha_composite(num, ((badge.width - num.width) // 2, (badge.height - num.height) // 2 + 2))
            row.alpha_composite(badge, (10, 10))
            row.alpha_composite(txt, (badge.width + 30, (row.height - txt.height) // 2))
            self.rows.append((drop_shadow(row, 12, 0.3, (0, 6)), top + i * gap, 0.6 + i * avail / n))

    def render(self, t):
        f = self.backdrop.frame(t)
        if self.heading is not None:
            hp = ease_out_cubic(progress(t, 0.0, 0.5))
            paste(f, self.heading, (self.W / 2 - self.heading.width / 2, self.H * 0.08 - (1 - hp) * 30), opacity=hp)
        for row, y, start in self.rows:
            k = ease_out_cubic(progress(t, start, 0.5))
            if k > 0.01:
                paste(f, row, (self.W / 2 - row.width / 2 - (1 - k) * 200, y), opacity=k)
        return f


class ComparisonScene(Scene):
    def prepare(self):
        v = self.v
        items = v.get("items", [])
        vals = [max(1e-9, abs(i["value"])) for i in items]
        self.log = max(vals) / min(vals) > 40
        ref = [math.log10(x) - math.log10(min(vals)) + 0.3 for x in vals] if self.log else vals
        mx = max(ref)
        self.heading = text_sprite(v.get("heading", ""), "heading", int(self.H * 0.065), fill=self.theme.fg, shadow=8, max_w=int(self.W * 0.85)) if v.get("heading") else None
        n = len(items)
        top = self.H * (0.27 if self.heading else 0.18)
        gap = min(self.H * 0.16, (self.H * 0.88 - top) / n)
        self.bars = []
        colors = [ORANGE, (46, 196, 182), YELLOW, (255, 93, 143), (130, 140, 255)]
        for i, (it, r) in enumerate(zip(items, ref)):
            lbl = text_sprite(it["label"], "body", int(self.H * 0.04), fill=self.theme.fg, max_w=int(self.W * 0.24), align="right")
            val = text_sprite(f"{format_number(it['value'], 0 if it['value'] >= 100 else 1)} {it['unit']}".strip(), "heading", int(self.H * 0.04), fill=self.theme.fg)
            self.bars.append((lbl, val, r / mx, top + i * gap, gap * 0.62, colors[i % len(colors)], 0.5 + i * 0.35))
        self.note = text_sprite("(log scale)", "body_semi", int(self.H * 0.026), fill=self.theme.fg) if self.log else None

    def render(self, t):
        f = self.backdrop.frame(t)
        d = ImageDraw.Draw(f, "RGBA")
        if self.heading is not None:
            hp = ease_out_cubic(progress(t, 0.0, 0.5))
            paste(f, self.heading, (self.W / 2 - self.heading.width / 2, self.H * 0.08 - (1 - hp) * 30), opacity=hp)
        x0 = self.W * 0.3
        maxw = self.W * 0.5
        for lbl, val, frac, y, h, col, start in self.bars:
            k = ease_out_cubic(progress(t, start, 1.1))
            if k <= 0:
                continue
            paste(f, lbl, (x0 - 24 - lbl.width, y + h / 2 - lbl.height / 2), opacity=clamp(k * 3))
            w = max(h, maxw * frac * k)
            d.rounded_rectangle([x0, y, x0 + w, y + h], int(h / 2), fill=col)
            paste(f, val, (x0 + w + 20, y + h / 2 - val.height / 2), opacity=clamp(k * 2 - 1))
        if self.note is not None:
            paste(f, self.note, (self.W - self.note.width - 40, self.H - self.note.height - 30), opacity=0.8)
        return f


class QuoteScene(Scene):
    def prepare(self):
        v = self.v
        self.panel_w = int(self.W * 0.72)
        fnt, lines, lh = fit_text(f"{v.get('text', '')}", "heading_semi", self.panel_w - 160, int(self.H * 0.42), int(self.H * 0.07), 26)
        self.panel_h = lh * len(lines) + (230 if v.get("author") else 170)
        self.lines = [text_sprite(l, "heading_semi", fnt.size, fill=self.theme.card_text) for l in lines]
        self.lh = lh
        self.author = text_sprite(f"- {v.get('author', '')}", "body", int(self.H * 0.036), fill=ORANGE) if v.get("author") else None
        self.panel = drop_shadow(rounded_box((self.panel_w, self.panel_h), 40, self.theme.card), 20, 0.35, (0, 10))
        self.qmark = text_sprite("“", "display", int(self.H * 0.3), fill=ORANGE)

    def render(self, t):
        f = self.backdrop.frame(t)
        p = ease_out_back(progress(t, 0.0, 0.5))
        paste(f, scale_sprite(self.panel, 0.9 + 0.1 * p), (self.W / 2, self.H / 2), opacity=clamp(p), anchor="c")
        paste(f, self.qmark, (self.W / 2 - self.panel_w / 2 + 30, self.H / 2 - self.panel_h / 2 - self.qmark.height * 0.35), opacity=clamp(p))
        n = len(self.lines)
        y0 = self.H / 2 - (n * self.lh) / 2 - (25 if self.author else 0)
        reveal = max(0.8, self.ctx.duration * 0.5)
        for i, l in enumerate(self.lines):
            k = ease_out_cubic(progress(t, 0.4 + i * reveal / n, 0.5))
            paste(f, l, (self.W / 2 - l.width / 2, y0 + i * self.lh + (1 - k) * 15), opacity=k)
        if self.author is not None:
            k = ease_out_cubic(progress(t, 0.6 + reveal, 0.5))
            paste(f, self.author, (self.W / 2 + self.panel_w / 2 - self.author.width - 70, y0 + n * self.lh + 25), opacity=k)
        return f


class MascotScene(Scene):
    corner_mascot = False

    def prepare(self):
        expr = self.spec.get("mascot", "none")
        expr = expr if expr != "none" else "happy"
        line = self.v.get("line", "")
        if self.ctx.is_last:
            self._prepare_end()
            return
        self.end = False
        self.zib = ZibActor(int(self.H * 0.52), expr, seed=self.ctx.seed, envelope=self.ctx.envelope, fps=self.ctx.fps, enter="left", enter_at=0.0)
        self.bubble = None
        if line:
            fnt, lines, lh = fit_text(line, "heading", int(self.W * 0.4), int(self.H * 0.32), int(self.H * 0.075), 30)
            txt = Image.new("RGBA", (int(self.W * 0.4) + 10, lh * len(lines) + 20), (0, 0, 0, 0))
            dd = ImageDraw.Draw(txt)
            for i, l in enumerate(lines):
                dd.text(((txt.width - fnt.getlength(l)) / 2, i * lh), l, font=fnt, fill=INK)
            bw, bh = txt.width + 90, txt.height + 70
            b = Image.new("RGBA", (bw + 60, bh), (0, 0, 0, 0))
            bd = ImageDraw.Draw(b)
            bd.rounded_rectangle([60, 0, bw + 59, bh - 1], 50, fill=WHITE)
            bd.polygon([(0, bh * 0.62), (75, bh * 0.42), (75, bh * 0.75)], fill=WHITE)
            b.alpha_composite(txt, (60 + 45, 40))
            self.bubble = drop_shadow(b, 16, 0.35, (0, 8))

    def _prepare_end(self):
        self.end = True
        th = self.theme
        self.zib = ZibActor(int(self.H * 0.36), "happy", seed=self.ctx.seed, envelope=self.ctx.envelope, fps=self.ctx.fps, enter="up", enter_at=0.0, arm="raised", wave=True)
        self.thanks = text_sprite("THANKS FOR PROBING WITH ME!", "display", int(self.H * 0.07), fill=th.fg, shadow=8)
        self.slots = []
        for x in (0.08, 0.56):  # where to drop YouTube end-screen video elements
            box = Image.new("RGBA", (int(self.W * 0.36), int(self.W * 0.36 * 9 / 16)), (0, 0, 0, 0))
            ImageDraw.Draw(box).rounded_rectangle([0, 0, box.width - 1, box.height - 1], 24, fill=(255, 255, 255, 30), outline=(255, 255, 255, 120), width=4)
            self.slots.append((box, x))
        self.watch = text_sprite("WATCH NEXT", "heading", int(self.H * 0.04), fill=th.accent)

    def render(self, t):
        f = self.backdrop.frame(t)
        if self.end:
            p = ease_out_cubic(progress(t, 0.2, 0.6))
            paste(f, self.thanks, (self.W / 2, self.H * 0.1), opacity=p, anchor="c")
            for box, x in self.slots:
                paste(f, box, (self.W * x, self.H * 0.2), opacity=p)
                paste(f, self.watch, (self.W * x + box.width / 2, self.H * 0.2 + box.height / 2), opacity=p * 0.8, anchor="c")
            self.zib.draw(f, self.W / 2, self.H * 0.97, t)
            return f
        self.zib.draw(f, self.W * 0.27, self.H * 0.93, t)
        if self.bubble is not None:
            k = ease_out_back(progress(t, 0.35, 0.45))
            if k > 0.01:
                paste(f, scale_sprite(self.bubble, 0.6 + 0.4 * k), (self.W * 0.47 + self.bubble.width / 2 * (0.6 + 0.4 * k), self.H * 0.4), opacity=clamp(k * 2), anchor="c")
        return f


class CloseupScene(IllustrationScene):
    """A free extra cut: a tight moving crop on the previous image."""
    REGIONS = {"center": (0.22, 0.2), "left": (0.02, 0.15), "right": (0.42, 0.15), "top": (0.22, 0.0), "bottom": (0.22, 0.4)}

    def prepare(self):
        img = self.ctx.image
        if img is not None:
            fx, fy = self.REGIONS.get(self.v.get("focus", "center"), (0.22, 0.2))
            w, h = img.width * 0.56, img.height * 0.56
            self.ctx = SceneContext(**{**self.ctx.__dict__, "image": img.crop((int(img.width * fx), int(img.height * fy), int(img.width * fx + w), int(img.height * fy + h)))})
        super().prepare()


class KineticScene(Scene):
    """Big words slam onto the screen one by one."""
    corner_mascot = False

    def prepare(self):
        th = self.theme
        text = str(self.v.get("text", "")).upper()
        if self.ctx.image is not None:
            bg = cover(self.ctx.image, (self.W // 3, self.H // 3), 1.15).filter(ImageFilter.GaussianBlur(6))
            self.bg = Image.blend(bg, Image.new("RGB", bg.size, (8, 12, 30)), 0.62).resize((int(self.W * 1.15), int(self.H * 1.15)), Image.BILINEAR)
            fg, accent = WHITE, YELLOW
        else:
            self.bg = None
            fg, accent = th.fg, th.accent
        f, lines, lh = fit_text(text, "display", int(self.W * 0.82), int(self.H * 0.62), int(self.H * 0.2), 50, spacing=1.05)
        words = text.split()
        key = {w for w in words if any(c.isdigit() for c in w)} or ({max(words, key=len)} if words else set())
        self.words = []
        y0 = self.H / 2 - lh * len(lines) / 2 + lh / 2
        n = 0
        for li, line in enumerate(lines):
            ws = line.split()
            total = sum(f.getlength(w) for w in ws) + f.getlength(" ") * (len(ws) - 1)
            x = self.W / 2 - total / 2
            for w in ws:
                spr = text_sprite(w, "display", f.size, fill=accent if w in key else fg, stroke=max(4, f.size // 22), stroke_fill=INK, shadow=10)
                self.words.append((spr, x + f.getlength(w) / 2, y0 + li * lh, 0.05 + n * 0.11))
                x += f.getlength(w + " ")
                n += 1

    def render(self, t):
        if self.bg is not None:
            z = 1 + 0.06 * ease_out_cubic(t / max(0.1, self.ctx.duration))
            w, h = self.bg.width / z, self.bg.height / z
            cx, cy = self.bg.width / 2, self.bg.height / 2
            f = self.bg.resize(self.ctx.size, Image.BILINEAR, box=(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
        else:
            f = self.backdrop.frame(t)
        for spr, x, y, delay in self.words:
            k = progress(t, delay, 0.22)
            if k <= 0:
                continue
            sc = 1 + 0.9 * (1 - ease_out_cubic(k))
            paste(f, scale_sprite(spr, sc) if sc > 1.001 else spr, (x, y), opacity=clamp(k * 2.5), anchor="c")
        return f


class SplitScene(Scene):
    """Two images side by side (versus / before-after)."""
    corner_mascot = False

    def prepare(self):
        pw, ph = int(self.W * 0.44), int(self.H * 0.62)
        self.panels = []
        for side, img in (("left", self.ctx.image), ("right", self.ctx.image2)):
            info = self.v.get(side, {})
            if img is not None:
                pic = cover(img, (pw, ph)).convert("RGBA")
            else:
                pic = Backdrop(self.theme.name, (pw, ph), self.ctx.seed + (1 if side == "right" else 0)).frame(0).convert("RGBA")
            mask = Image.new("L", (pw, ph), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, pw - 1, ph - 1], 30, fill=255)
            panel = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
            panel.paste(pic, (0, 0), mask)
            ImageDraw.Draw(panel).rounded_rectangle([0, 0, pw - 1, ph - 1], 30, outline=(*CREAM, 255), width=8)
            label = info.get("label", "")
            lab = None
            if label:
                txt = text_sprite(label.upper(), "heading", int(self.H * 0.05), fill=INK)
                lab = rounded_box((txt.width + 50, txt.height + 14), 20, (*CREAM, 250))
                lab.alpha_composite(txt, (25, 7))
            self.panels.append((drop_shadow(panel, 20, 0.5, (0, 10)), lab))
        self.vs = text_sprite("VS", "display", int(self.H * 0.12), fill=YELLOW, stroke=8, stroke_fill=INK, shadow=10)

    def render(self, t):
        f = self.backdrop.frame(t)
        for k, (panel, lab) in enumerate(self.panels):
            p = ease_out_back(progress(t, 0.05 + k * 0.18, 0.45))
            cx = self.W * (0.27 if k == 0 else 0.73)
            off = (1 - p) * self.W * 0.6 * (-1 if k == 0 else 1)
            drift = math.sin(t * 0.8 + k) * 6
            paste(f, panel, (cx + off, self.H * 0.46 + drift), opacity=clamp(p * 2), anchor="c")
            if lab is not None:
                paste(f, lab, (cx + off, self.H * 0.84), opacity=clamp(p * 2), anchor="c")
        vk = ease_out_back(progress(t, 0.45, 0.35))
        if vk > 0.01:
            paste(f, scale_sprite(self.vs, vk), (self.W / 2, self.H * 0.46), anchor="c")
        return f


class VideoScene(Scene):
    """Plays a (pre-normalised) stock clip, with a gentle push-in and the usual overlays."""

    def prepare(self):
        import subprocess

        from ..tts import ffmpeg_exe

        self._sp = subprocess
        self._ff = ffmpeg_exe()
        self._proc = None
        self._next = 0
        self._last = None

    def _open(self, frame_index: int):
        if self._proc is not None:
            self._proc.kill()
        W, H = self.ctx.size
        self._proc = self._sp.Popen(
            [self._ff, "-v", "error", "-ss", f"{frame_index / self.ctx.fps:.3f}", "-i", self.ctx.video,
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(self.ctx.fps), "-"],
            stdout=self._sp.PIPE, stderr=self._sp.DEVNULL)
        self._next = frame_index

    def _read(self, idx: int) -> Image.Image | None:
        W, H = self.ctx.size
        if self._proc is None or idx < self._next or idx > self._next + 90:
            self._open(idx)
        size = W * H * 3
        while self._next <= idx:
            buf = self._proc.stdout.read(size)
            if len(buf) < size:  # clip ended: hold the last frame
                return self._last
            self._next += 1
            if self._next > idx:
                self._last = Image.frombytes("RGB", (W, H), buf)
        return self._last

    def render(self, t):
        f = self._read(int(t * self.ctx.fps))
        if f is None:
            f = self.ctx.image.resize(self.ctx.size) if self.ctx.image is not None else self.backdrop.frame(t)
        z = 1 + 0.05 * ease_in_out_sine(t / max(0.1, self.ctx.duration))
        w, h = self.W / z, self.H / z
        f = f.resize(self.ctx.size, Image.BILINEAR, box=((self.W - w) / 2, (self.H - h) / 2, (self.W + w) / 2, (self.H + h) / 2))
        return apply_vignette(f, 0.25)

    def __del__(self):
        if getattr(self, "_proc", None) is not None:
            self._proc.kill()


class BrollScene(Scene):
    """Real footage: a video clip if we have one, else the photo with a Ken Burns move."""

    def __new__(cls, spec, ctx):
        if ctx.video:
            return VideoScene(spec, ctx)
        return IllustrationScene(spec, ctx)


class SequenceScene(Scene):
    """A paragraph of narration cut into several shots, with punchy cuts and FX."""
    corner_mascot = False
    NO_CORNER = {"mascot", "title", "stat", "kinetic"}

    def prepare(self):
        ctx = self.ctx
        self.starts = [sh["start"] for sh in ctx.shots]
        self.subs = []
        for j, sh in enumerate(ctx.shots):
            st = sh["start"]
            en = ctx.shots[j + 1]["start"] if j + 1 < len(ctx.shots) else ctx.duration
            dur = max(1 / ctx.fps, en - st)
            env = None
            if ctx.envelope is not None:
                a = int(st * ctx.fps)
                env = ctx.envelope[a:]
            sub_ctx = SceneContext(
                size=ctx.size, fps=ctx.fps, duration=dur, theme=ctx.theme, seed=ctx.seed * 13 + j,
                image=sh.get("image"), image2=sh.get("image2"), video=sh.get("video"), envelope=env,
                sentences=[{**x, "start": x["start"] - st, "end": x["end"] - st} for x in ctx.sentences if x["end"] > st and x["start"] < en],
                chapter_number=ctx.chapter_number, is_last=ctx.is_last and j == len(ctx.shots) - 1,
                channel_name=ctx.channel_name, burn_captions=False,
            )
            spec = {"visual": sh["spec"]["visual"], "mascot": "none", "on_screen_text": sh["spec"].get("label", "")}
            if spec["visual"]["type"] in ("mascot", "stat"):
                spec["mascot"] = self.spec.get("mascot", "none")
            self.subs.append((st, SCENES.get(spec["visual"]["type"], IllustrationScene)(spec, sub_ctx), sh["spec"].get("fx", "none")))
        expr = self.spec.get("mascot", "none")
        self.zib = ZibActor(int(self.H * 0.22), expr, seed=ctx.seed, envelope=ctx.envelope, fps=ctx.fps, enter_at=0.4) if expr != "none" else None

    def render(self, t):
        j = 0
        for k, st in enumerate(self.starts):
            if t >= st:
                j = k
        st, sub, fx = self.subs[j]
        lt = t - st
        f = sub.frame(lt)
        # every cut lands with a tiny zoom-settle; fx add extra punch
        zoom = 1.0
        if j > 0 and lt < 0.25:
            zoom = 1 + 0.035 * (1 - ease_out_cubic(lt / 0.25))
        if fx == "punch" and lt < 0.4:
            zoom = max(zoom, 1 + 0.16 * (1 - ease_out_cubic(lt / 0.4)))
        dx = dy = 0.0
        if fx == "shake" and lt < 0.5:
            a = 22 * (1 - lt / 0.5)
            dx, dy = a * math.sin(lt * 95), a * math.cos(lt * 71)
            zoom = max(zoom, 1.05)
        if zoom > 1.0005 or dx or dy:
            w, h = self.W / zoom, self.H / zoom
            x0 = (self.W - w) / 2 + dx
            y0 = (self.H - h) / 2 + dy
            x0 = min(max(0, x0), self.W - w)
            y0 = min(max(0, y0), self.H - h)
            f = f.resize(self.ctx.size, Image.BILINEAR, box=(x0, y0, x0 + w, y0 + h))
        if fx == "flash" and lt < 0.3:
            f = Image.blend(f, Image.new("RGB", f.size, (255, 255, 255)), 0.85 * (1 - lt / 0.3))
        if self.zib is not None and sub.v.get("type") not in self.NO_CORNER:
            self.zib.draw(f, self.W - self.H * 0.16, self.H - 20, t)
        return f


SCENES = {
    "illustration": IllustrationScene,
    "archive": ArchiveScene,
    "title": TitleScene,
    "stat": StatScene,
    "timeline": TimelineScene,
    "list": ListScene,
    "comparison": ComparisonScene,
    "quote": QuoteScene,
    "mascot": MascotScene,
    "closeup": CloseupScene,
    "broll": BrollScene,
    "kinetic": KineticScene,
    "split": SplitScene,
}


def make_scene(spec: dict, ctx: SceneContext) -> Scene:
    if ctx.shots and len(ctx.shots) > 0:
        return SequenceScene(spec, ctx)
    return SCENES.get(spec.get("visual", {}).get("type"), IllustrationScene)(spec, ctx)
