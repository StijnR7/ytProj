"""Zib - the channel mascot. A tiny floating exploration probe with a screen face.

Drawn procedurally (no image files needed) at 3x supersampling for crisp edges,
then cached per pose so animation is cheap.
"""
from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .common import CYAN, INK, ORANGE, PINK, YELLOW, clamp, ease_out_back, paste

BODY = (243, 238, 228)
BODY_SHADE = (214, 205, 190)
SCREEN = (16, 24, 51)
ORANGE_DARK = (214, 92, 30)

EXPRESSIONS = ("neutral", "happy", "surprised", "thinking", "excited", "worried", "pointing")
SS = 3


def _star(cx, cy, r_out, r_in, n=5, rot=-90):
    pts = []
    for i in range(n * 2):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(rot + i * 180 / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _capsule(d: ImageDraw.ImageDraw, p, cx, cy, length, thick, angle_deg, fill, outline, ow):
    """Rotated capsule (rounded arm) as a polygon approximation."""
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    hl, r = length / 2 - thick / 2, thick / 2
    pts = []
    for k in range(0, 181, 15):  # right cap
        t = math.radians(k - 90)
        x, y = hl + r * math.cos(t), r * math.sin(t)
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    for k in range(180, 361, 15):  # left cap
        t = math.radians(k - 90)
        x, y = -hl + r * math.cos(t), r * math.sin(t)
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    d.polygon([(p(x), p(y)) for x, y in pts], fill=fill, outline=outline, width=int(p(ow)))


@lru_cache(maxsize=512)
def draw_zib(size: int = 400, expression: str = "neutral", mouth: int = 0, blink: bool = False, arm: str = "auto") -> Image.Image:
    """Return an RGBA sprite of Zib. size = sprite width in px (height = 1.1 x width)."""
    if expression not in EXPRESSIONS:
        expression = "neutral"
    if arm == "auto":
        arm = "raised" if expression in ("pointing", "excited") else "down"
    W, H = size * SS, int(size * 1.1) * SS
    k = W / 1000

    def p(v):
        return v * k

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ow = 14  # outline width (units)

    # --- antenna (behind body)
    d.line([(p(500), p(330)), (p(500), p(185))], fill=INK, width=int(p(16)))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([p(440), p(90), p(560), p(210)], fill=(*YELLOW, 170))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(p(22))))
    d.ellipse([p(466), p(116), p(534), p(184)], fill=ORANGE, outline=INK, width=int(p(12)))
    d.ellipse([p(482), p(128), p(504), p(150)], fill=(255, 220, 170))

    # --- arms (behind body)
    _capsule(d, p, 195, 650, 150, 72, -25, ORANGE, INK, 12)
    if arm == "raised":
        _capsule(d, p, 790, 485, 170, 72, -55, ORANGE, INK, 12)
    else:
        _capsule(d, p, 805, 650, 150, 72, 25, ORANGE, INK, 12)

    # --- thruster
    d.polygon([(p(440), p(885)), (p(560), p(885)), (p(535), p(940)), (p(465), p(940))], fill=(120, 130, 160), outline=INK, width=int(p(10)))

    # --- body sphere with shading
    body_box = [p(200), p(300), p(800), p(900)]
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse(body_box, fill=255)
    body = Image.new("RGBA", (W, H), (*BODY, 255))
    shade_cut = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shade_cut).ellipse([p(150), p(230), p(770), p(850)], fill=255)
    shade_mask = ImageChops.subtract(mask, shade_cut)
    body.paste((*BODY_SHADE, 255), (0, 0), shade_mask)
    # orange equator band
    band = Image.new("L", (W, H), 0)
    ImageDraw.Draw(band).rectangle([0, p(735), W, p(790)], fill=255)
    body.paste((*ORANGE, 255), (0, 0), ImageChops.multiply(band, mask))
    band_shade = ImageChops.multiply(ImageChops.multiply(band, mask), shade_mask)
    body.paste((*ORANGE_DARK, 255), (0, 0), band_shade)
    bd = ImageDraw.Draw(body)
    for x in (330, 500, 670):  # rivets
        bd.ellipse([p(x - 11), p(752), p(x + 11), p(774)], fill=(255, 214, 170))
    img.paste(body, (0, 0), mask)
    d = ImageDraw.Draw(img)
    d.ellipse(body_box, outline=INK, width=int(p(ow)))
    # highlight
    hl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse([p(270), p(350), p(380), p(420)], fill=(255, 255, 255, 150))
    img.alpha_composite(hl.filter(ImageFilter.GaussianBlur(p(8))))

    # --- screen face
    d.rounded_rectangle([p(285), p(420), p(715), p(690)], radius=int(p(105)), fill=SCREEN, outline=INK, width=int(p(ow)))
    d.rounded_rectangle([p(318), p(445), p(470), p(470)], radius=int(p(12)), fill=(60, 75, 120))

    face = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    f = ImageDraw.Draw(face)
    lx, rx, ey = 420, 580, 545
    eye_col = (*CYAN, 255)

    def pill(cx, cy, w, h, col=eye_col):
        f.rounded_rectangle([p(cx - w / 2), p(cy - h / 2), p(cx + w / 2), p(cy + h / 2)], radius=int(p(min(w, h) / 2)), fill=col)

    def arc_eye(cx, cy, up=True, w=80):
        box = [p(cx - w / 2), p(cy - 30), p(cx + w / 2), p(cy + 40)]
        f.arc(box, 200 if up else 20, 340 if up else 160, fill=eye_col, width=int(p(16)))

    if blink and expression not in ("happy", "excited"):
        for cx in (lx, rx):
            pill(cx, ey + 10, 70, 14)
    elif expression == "happy":
        arc_eye(lx, ey + 10)
        arc_eye(rx, ey + 10)
    elif expression == "surprised":
        for cx in (lx, rx):
            f.ellipse([p(cx - 44), p(ey - 44), p(cx + 44), p(ey + 44)], fill=eye_col)
            f.ellipse([p(cx - 14), p(ey - 26), p(cx + 6), p(ey - 6)], fill=(230, 255, 252, 255))
    elif expression == "thinking":
        pill(lx + 10, ey - 12, 54, 84)
        f.arc([p(rx - 40), p(ey - 25), p(rx + 40), p(ey + 25)], 190, 350, fill=eye_col, width=int(p(16)))
    elif expression == "excited":
        for cx in (lx, rx):
            f.polygon([(p(x), p(y)) for x, y in _star(cx, ey, 50, 22)], fill=(*YELLOW, 255))
    elif expression == "worried":
        f.polygon([(p(lx - 34), p(ey - 25)), (p(lx + 34), p(ey - 45)), (p(lx + 34), p(ey + 40)), (p(lx - 34), p(ey + 40))], fill=eye_col)
        f.polygon([(p(rx - 34), p(ey - 45)), (p(rx + 34), p(ey - 25)), (p(rx + 34), p(ey + 40)), (p(rx - 34), p(ey + 40))], fill=eye_col)
    else:  # neutral / pointing
        pill(lx, ey, 62, 96)
        pill(rx, ey, 62, 96)
        f.ellipse([p(lx - 16), p(ey - 34), p(lx + 4), p(ey - 14)], fill=(230, 255, 252, 255))
        f.ellipse([p(rx - 16), p(ey - 34), p(rx + 4), p(ey - 14)], fill=(230, 255, 252, 255))

    # mouth
    my = 628
    mouth = int(clamp(mouth, 0, 4))
    if mouth > 0:
        h = 10 + mouth * 9
        f.rounded_rectangle([p(500 - 34 + mouth * 2), p(my - h / 2), p(500 + 34 - mouth * 2), p(my + h / 2)], radius=int(p(h / 2)), fill=eye_col)
    elif expression == "surprised":
        f.ellipse([p(484), p(my - 18), p(516), p(my + 18)], outline=eye_col, width=int(p(10)))
    elif expression == "worried":
        f.line([(p(470), p(my + 6)), (p(485), p(my - 6)), (p(500), p(my + 6)), (p(515), p(my - 6)), (p(530), p(my + 6))], fill=eye_col, width=int(p(10)), joint="curve")
    elif expression == "thinking":
        f.line([(p(480), p(my)), (p(525), p(my - 8))], fill=eye_col, width=int(p(10)))
    else:
        f.arc([p(462), p(my - 30), p(538), p(my + 14)], 20, 160, fill=eye_col, width=int(p(11)))
    # cheeks
    f.ellipse([p(330), p(600), p(372), p(624)], fill=(*PINK, 140))
    f.ellipse([p(628), p(600), p(670), p(624)], fill=(*PINK, 140))

    face_glow = face.filter(ImageFilter.GaussianBlur(p(14)))
    img.alpha_composite(face_glow)
    img.alpha_composite(face)

    return img.resize((size, int(size * 1.1)), Image.LANCZOS)


CANON = 640


@lru_cache(maxsize=1024)
def zib_sprite(size: int, expression: str = "neutral", mouth: int = 0, blink: bool = False, arm: str = "auto") -> Image.Image:
    """Zib at any size: drawn once at a canonical size, then downscaled (fast)."""
    base = draw_zib(CANON, expression, mouth, blink, arm)
    if size == CANON:
        return base
    return base.resize((size, int(size * 1.1)), Image.LANCZOS)


@lru_cache(maxsize=16)
def thruster_glow(size: int) -> Image.Image:
    W = int(size * 0.5)
    g = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    d.ellipse([W * 0.3, W * 0.2, W * 0.7, W * 0.75], fill=(*YELLOW, 200))
    d.ellipse([W * 0.4, W * 0.25, W * 0.6, W * 0.55], fill=(255, 255, 230, 230))
    return g.filter(ImageFilter.GaussianBlur(W * 0.08))


class ZibActor:
    """Animated Zib: bobbing, blinking, talking (driven by voice loudness) and entrances."""

    def __init__(self, size: int, expression: str = "neutral", seed: int = 0, envelope=None, fps: int = 30,
                 enter: str = "up", enter_at: float = 0.15, arm: str = "auto", wave: bool = False):
        self.size, self.expression, self.seed = size, expression, seed
        self.envelope, self.fps = envelope, fps
        self.enter, self.enter_at, self.arm, self.wave = enter, enter_at, arm, wave

    def mouth_at(self, t: float) -> int:
        if self.envelope is None or len(self.envelope) == 0:
            return 0
        i = min(len(self.envelope) - 1, max(0, int(t * self.fps)))
        return int(self.envelope[i])

    def blink_at(self, t: float) -> bool:
        period = 3.2 + (self.seed % 7) * 0.31
        return (t + self.seed * 0.37) % period < 0.13

    def draw(self, frame: Image.Image, x: float, y: float, t: float, talk: bool = True) -> None:
        """Draw with sprite bottom-center at (x, y)."""
        p = ease_out_back(clamp((t - self.enter_at) / 0.55))
        if p <= 0:
            return
        off_x = off_y = 0.0
        if self.enter == "up":
            off_y = (1 - p) * (self.size * 1.4)
        elif self.enter == "left":
            off_x = -(1 - p) * (x + self.size)
        elif self.enter == "right":
            off_x = (1 - p) * (frame.width - x + self.size)
        bob = math.sin(2 * math.pi * 0.55 * t + self.seed) * self.size * 0.03
        tilt = math.sin(2 * math.pi * 0.35 * t + self.seed * 2) * 3.0
        if self.wave:
            tilt += math.sin(2 * math.pi * 1.6 * t) * 6
        sprite = zib_sprite(self.size, self.expression, self.mouth_at(t) if talk else 0, self.blink_at(t), self.arm)
        if abs(tilt) > 0.3:
            sprite = sprite.rotate(tilt, resample=Image.BICUBIC, expand=True)
        cx, by = x + off_x, y + off_y + bob
        glow = thruster_glow(self.size)
        flick = 0.75 + 0.25 * math.sin(t * 37 + self.seed)
        paste(frame, glow, (cx, by - sprite.height * 0.1), opacity=flick, anchor="c")
        paste(frame, sprite, (cx, by), anchor="bc")
