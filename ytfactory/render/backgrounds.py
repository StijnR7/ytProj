"""Animated, procedurally drawn backdrops per theme (used behind graphics, and as image fallback)."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .common import CREAM, INK, ORANGE, PINK, TEAL, WHITE, YELLOW, vertical_gradient


@dataclass
class Theme:
    name: str
    top: tuple
    bottom: tuple
    fg: tuple          # main text colour
    accent: tuple      # highlight colour
    card: tuple        # card / panel fill (RGBA)
    card_text: tuple


THEMES = {
    "space": Theme("space", (11, 16, 46), (43, 27, 90), WHITE, (92, 242, 230), (255, 255, 255, 235), INK),
    "history": Theme("history", (246, 231, 200), (222, 190, 140), (58, 38, 22), (196, 84, 36), (255, 250, 238, 240), (58, 38, 22)),
    "animals": Theme("animals", (12, 62, 66), (24, 110, 84), WHITE, YELLOW, (255, 255, 255, 235), INK),
    "hypotheticals": Theme("hypotheticals", (26, 11, 61), (74, 20, 102), WHITE, PINK, (255, 255, 255, 235), INK),
    "brand": Theme("brand", (15, 27, 61), (28, 52, 110), WHITE, ORANGE, (255, 255, 255, 235), INK),
}


def get_theme(name: str) -> Theme:
    return THEMES.get(name, THEMES["brand"])


class Backdrop:
    """Static base painting + cheap per-frame particles."""

    def __init__(self, theme: str, size=(1920, 1080), seed: int = 0):
        self.theme = get_theme(theme)
        self.size = size
        self.rng = random.Random(seed)
        self.base = self._paint()
        self.particles = self._make_particles()

    # -------------------------------------------------------------- painting
    def _blob_layer(self, blobs, blur):
        W, H = self.size
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for (x, y, r, col) in blobs:
            d.ellipse([x - r, y - r, x + r, y + r], fill=col)
        return layer.filter(ImageFilter.GaussianBlur(blur))

    def _paint(self) -> Image.Image:
        W, H = self.size
        th, R = self.theme, self.rng
        img = vertical_gradient(self.size, th.top, th.bottom).convert("RGBA")
        if th.name == "space":
            img.alpha_composite(self._blob_layer(
                [(R.uniform(0, W), R.uniform(0, H), R.uniform(250, 500), (*c, 60))
                 for c in [(120, 60, 200), (40, 120, 220), (200, 60, 140), (60, 200, 200)]], 120))
            d = ImageDraw.Draw(img)
            for _ in range(320):
                x, y, r = R.uniform(0, W), R.uniform(0, H), R.choice([1, 1, 1, 1.5, 2])
                a = R.randint(90, 230)
                d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, a))
            # a planet in a corner
            side = R.choice([-1, 1])
            px, py, pr = (W * 0.9 if side > 0 else W * 0.1), H * R.uniform(0.75, 0.95), R.uniform(160, 260)
            planet = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            pd = ImageDraw.Draw(planet, "RGBA")
            col = R.choice([(255, 140, 90), (110, 170, 255), (190, 120, 255), (90, 210, 180)])
            pd.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(*col, 255))
            for i in range(5):
                yy = py - pr + (i + 1) * pr * 2 / 6
                pd.rectangle([px - pr, yy - 8, px + pr, yy + 8], fill=(*[max(0, c - 30) for c in col], 120))
            shade = Image.new("L", (W, H), 0)
            ImageDraw.Draw(shade).ellipse([px - pr * 0.75 + side * -pr * 0.5, py - pr * 1.25, px + pr * 1.25 + side * -pr * 0.5, py + pr * 0.75], fill=255)
            mask = Image.new("L", (W, H), 0)
            ImageDraw.Draw(mask).ellipse([px - pr, py - pr, px + pr, py + pr], fill=255)
            dark = Image.new("RGBA", (W, H), (10, 10, 30, 150))
            from PIL import ImageChops
            planet.paste(dark, (0, 0), ImageChops.subtract(mask, shade))
            planet.putalpha(ImageChops.multiply(planet.split()[3], mask))
            img.alpha_composite(planet)
        elif th.name == "history":
            noise = (np.random.default_rng(R.randint(0, 9999)).normal(0, 9, (H // 2, W // 2))).clip(-30, 30)
            n = Image.fromarray((128 + noise).astype(np.uint8), "L").resize((W, H), Image.BILINEAR)
            grain = Image.new("RGBA", (W, H), (90, 60, 30, 0))
            grain.putalpha(n.point(lambda v: max(0, v - 118) * 3))
            img.alpha_composite(grain)
            img.alpha_composite(self._blob_layer(
                [(R.uniform(0, W), R.uniform(0, H), R.uniform(200, 420), (160, 110, 60, 40)) for _ in range(5)], 140))
            d = ImageDraw.Draw(img)
            cx, cy, r = W * R.choice([0.12, 0.88]), H * 0.8, 170  # faint compass rose
            for i in range(16):
                a = math.radians(i * 22.5)
                rr = r if i % 2 == 0 else r * 0.55
                d.line([(cx, cy), (cx + rr * math.cos(a), cy + rr * math.sin(a))], fill=(120, 80, 40, 60), width=3)
            d.ellipse([cx - r * 0.7, cy - r * 0.7, cx + r * 0.7, cy + r * 0.7], outline=(120, 80, 40, 60), width=3)
            for y in range(140, H, 210):  # faint map latitude lines
                d.line([(0, y), (W, y + 30)], fill=(120, 80, 40, 25), width=2)
        elif th.name == "animals":
            leaves = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            for _ in range(14):
                lw, lh = R.uniform(260, 520), R.uniform(110, 200)
                leaf = Image.new("RGBA", (int(lw), int(lh)), (0, 0, 0, 0))
                ImageDraw.Draw(leaf).ellipse([0, 0, lw - 1, lh - 1], fill=(8, R.randint(70, 110), R.randint(55, 80), 210))
                ImageDraw.Draw(leaf).line([(10, lh / 2), (lw - 10, lh / 2)], fill=(30, 140, 100, 160), width=4)
                leaf = leaf.rotate(R.uniform(0, 360), expand=True, resample=Image.BICUBIC)
                edge = R.choice(["l", "r", "b", "t"])
                x = R.uniform(-150, 250) if edge == "l" else R.uniform(W - 400, W - 50) if edge == "r" else R.uniform(0, W)
                y = R.uniform(H - 300, H - 50) if edge == "b" else R.uniform(-150, 150) if edge == "t" else R.uniform(0, H)
                leaves.alpha_composite(leaf, (int(x - leaf.width / 2), int(y - leaf.height / 2)) if leaf.width < W else (0, 0))
            img.alpha_composite(leaves.filter(ImageFilter.GaussianBlur(2)))
            img.alpha_composite(self._blob_layer([(W / 2, -100, 600, (255, 240, 170, 60))], 160))
        elif th.name == "hypotheticals":
            img.alpha_composite(self._blob_layer([(W * 0.5, H * 0.62, 520, (255, 93, 143, 70)), (W * 0.2, H * 0.2, 300, (120, 80, 255, 60))], 150))
            d = ImageDraw.Draw(img)
            hz = H * 0.62
            for i in range(-14, 15):  # perspective grid
                d.line([(W / 2 + i * 40, hz), (W / 2 + i * 260, H)], fill=(255, 93, 143, 90), width=2)
            y, step = hz, 8
            while y < H:
                d.line([(0, y), (W, y)], fill=(255, 93, 143, 90), width=2)
                step *= 1.35
                y += step
            for _ in range(160):
                x, yy = R.uniform(0, W), R.uniform(0, hz)
                d.ellipse([x - 1, yy - 1, x + 1, yy + 1], fill=(255, 255, 255, R.randint(60, 200)))
        else:  # brand
            img.alpha_composite(self._blob_layer(
                [(W * 0.15, H * 0.2, 380, (*ORANGE, 70)), (W * 0.85, H * 0.85, 420, (*TEAL, 70)), (W * 0.7, H * 0.1, 250, (*YELLOW, 40))], 150))
            d = ImageDraw.Draw(img)
            for _ in range(26):
                x, y, r = R.uniform(0, W), R.uniform(0, H), R.uniform(4, 14)
                d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 255, 50), width=3)
        return img.convert("RGB")

    def _make_particles(self):
        R = self.rng
        n = {"space": 40, "history": 30, "animals": 26, "hypotheticals": 30, "brand": 24}[self.theme.name]
        return [
            (R.uniform(0, self.size[0]), R.uniform(0, self.size[1]), R.uniform(1.5, 4.5), R.uniform(-12, 12),
             R.uniform(-18, -4), R.uniform(0, 6.28), R.uniform(0.4, 1.4))
            for _ in range(n)
        ]

    def draw_particles(self, img: Image.Image, t: float, strength: float = 1.0, color=None) -> None:
        d = ImageDraw.Draw(img, "RGBA")
        W, H = img.size
        col = color or {"space": (255, 255, 255), "history": (120, 80, 40), "animals": (255, 250, 200),
                        "hypotheticals": (255, 180, 220), "brand": (255, 255, 255)}[self.theme.name]
        for (x0, y0, r, vx, vy, ph, sp) in self.particles:
            x = (x0 + vx * t) % W
            y = (y0 + vy * t) % H
            a = int((70 + 110 * (0.5 + 0.5 * math.sin(ph + t * sp * 2))) * strength)
            d.ellipse([x - r, y - r, x + r, y + r], fill=(*col, a))

    def frame(self, t: float) -> Image.Image:
        img = self.base.copy()
        self.draw_particles(img, t)
        return img


def fallback_illustration(prompt: str, theme: str, size=(1344, 768), seed: int = 0) -> Image.Image:
    """When no AI image backend is set up: a themed backdrop. (Graphics + Zib carry the scene.)"""
    return Backdrop(theme, size, seed).frame(0)


def cream_panel(size, theme: Theme) -> Image.Image:
    from .common import rounded_box
    return rounded_box(size, 36, theme.card)


_ = CREAM  # re-export convenience
