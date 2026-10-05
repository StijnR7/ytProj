"""Shared drawing helpers: brand palette, fonts, easing, text layout."""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import FONTS

# ------------------------------------------------------------------ brand
NAVY = (15, 27, 61)
DEEP = (10, 18, 48)
ORANGE = (255, 122, 48)
TEAL = (46, 196, 182)
CYAN = (92, 242, 230)
CREAM = (255, 244, 224)
YELLOW = (255, 210, 63)
PINK = (255, 93, 143)
WHITE = (255, 255, 255)
INK = (27, 36, 64)

FONT_FILES = {
    "display": "LuckiestGuy-Regular.ttf",
    "heading": "Fredoka-Bold.ttf",
    "heading_semi": "Fredoka-SemiBold.ttf",
    "body": "Nunito-ExtraBold.ttf",
    "body_semi": "Nunito-SemiBold.ttf",
    "black": "Nunito-Black.ttf",
}


@lru_cache(maxsize=256)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONTS / FONT_FILES.get(name, name)
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        for fb in ("arialbd.ttf", "DejaVuSans-Bold.ttf"):
            try:
                return ImageFont.truetype(fb, size)
            except OSError:
                continue
        return ImageFont.load_default(size)


# ------------------------------------------------------------------ easing
def clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return a if x < a else b if x > b else x


def ease_out_cubic(x: float) -> float:
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in_out_sine(x: float) -> float:
    x = clamp(x)
    return -(math.cos(math.pi * x) - 1) / 2


def ease_out_back(x: float, s: float = 1.70158) -> float:
    x = clamp(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def ease_in_cubic(x: float) -> float:
    x = clamp(x)
    return x**3


def progress(t: float, start: float, dur: float) -> float:
    return clamp((t - start) / dur) if dur > 0 else (1.0 if t >= start else 0.0)


# ------------------------------------------------------------------ text
def wrap(text: str, f: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if f.getlength(test) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_text(text: str, fname: str, max_w: int, max_h: int, max_size: int, min_size: int = 18, spacing: float = 1.12):
    size = max_size
    while size >= min_size:
        f = font(fname, size)
        lines = wrap(text, f, max_w)
        lh = int(size * spacing)
        if lh * len(lines) <= max_h and all(f.getlength(l) <= max_w for l in lines):
            return f, lines, lh
        size -= 2
    f = font(fname, min_size)
    return f, wrap(text, f, max_w), int(min_size * spacing)


def text_sprite(
    text: str,
    fname: str,
    size: int,
    fill=WHITE,
    stroke: int = 0,
    stroke_fill=INK,
    shadow: int = 0,
    max_w: int | None = None,
    align: str = "center",
    spacing: float = 1.12,
) -> Image.Image:
    """Render (wrapped) text to a tight RGBA sprite, optional outline and soft shadow."""
    f = font(fname, size)
    lines = wrap(text, f, max_w) if max_w else [text]
    lh = int(size * spacing)
    widths = [int(f.getlength(l)) for l in lines]
    pad = stroke + shadow * 2 + 6
    W = max(widths) + pad * 2
    H = lh * len(lines) + pad * 2 + int(size * 0.25)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, l in enumerate(lines):
        x = pad + (0 if align == "left" else (max(widths) - widths[i]) // (2 if align == "center" else 1))
        d.text((x, pad + i * lh), l, font=f, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        alpha = img.split()[3].filter(ImageFilter.GaussianBlur(shadow))
        sh.putalpha(alpha.point(lambda a: int(a * 0.55)))
        base = Image.new("RGBA", img.size, (0, 0, 0, 0))
        base.alpha_composite(sh, (0, shadow // 2 + 2))
        base.alpha_composite(img)
        img = base
    return img


def rounded_box(size, radius, fill, outline=None, width=0) -> Image.Image:
    w, h = size
    s = 2
    img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        (0, 0, w * s - 1, h * s - 1), radius * s, fill=fill, outline=outline, width=width * s
    )
    return img.resize((w, h), Image.LANCZOS)


def drop_shadow(sprite: Image.Image, blur: int = 18, opacity: float = 0.45, offset=(0, 10)) -> Image.Image:
    pad = blur * 2 + max(abs(offset[0]), abs(offset[1]))
    W, H = sprite.width + pad * 2, sprite.height + pad * 2
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    a = sprite.split()[3].point(lambda v: int(v * opacity))
    sh = Image.new("RGBA", sprite.size, (0, 0, 0, 255))
    sh.putalpha(a)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.paste(sh, (pad + offset[0], pad + offset[1]))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    out.alpha_composite(layer)
    out.alpha_composite(sprite, (pad, pad))
    return out


def with_opacity(sprite: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 0.999:
        return sprite
    s = sprite.copy()
    a = s.split()[3].point(lambda v: int(v * max(0.0, opacity)))
    s.putalpha(a)
    return s


def paste(frame: Image.Image, sprite: Image.Image, xy, opacity: float = 1.0, anchor: str = "tl") -> None:
    """Alpha-paste sprite onto an RGB frame. anchor: tl | c | bc."""
    if opacity <= 0.01:
        return
    x, y = xy
    if anchor == "c":
        x, y = x - sprite.width / 2, y - sprite.height / 2
    elif anchor == "bc":
        x, y = x - sprite.width / 2, y - sprite.height
    s = with_opacity(sprite, opacity)
    frame.paste(s, (int(round(x)), int(round(y))), s)


def scale_sprite(sprite: Image.Image, k: float) -> Image.Image:
    if abs(k - 1) < 1e-3:
        return sprite
    w, h = max(1, int(sprite.width * k)), max(1, int(sprite.height * k))
    return sprite.resize((w, h), Image.BILINEAR)


def vertical_gradient(size, top, bottom) -> Image.Image:
    w, h = size
    t = np.linspace(0, 1, h)[:, None, None]
    arr = (np.array(top)[None, None, :] * (1 - t) + np.array(bottom)[None, None, :] * t)
    arr = np.repeat(arr, w, axis=1).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


@lru_cache(maxsize=4)
def vignette_mask(size, strength: float = 0.55) -> Image.Image:
    """'L' mask: 255 = keep image, lower = darken towards edges."""
    w, h = size
    y, x = np.ogrid[-1:1:h * 1j, -1:1:w * 1j]
    r = np.sqrt(x**2 * 0.9 + y**2 * 1.1)
    m = 1 - strength * np.clip((r - 0.55) / 0.85, 0, 1) ** 1.6
    return Image.fromarray((m * 255).astype(np.uint8), "L")


def apply_vignette(frame: Image.Image, strength: float = 0.55) -> Image.Image:
    black = Image.new("RGB", frame.size, (5, 8, 20))
    return Image.composite(frame, black, vignette_mask(frame.size, strength))


def cover(img: Image.Image, size, scale: float = 1.0) -> Image.Image:
    """Resize to cover `size * scale`, center-cropped."""
    W, H = int(size[0] * scale), int(size[1] * scale)
    k = max(W / img.width, H / img.height)
    r = img.resize((max(W, int(img.width * k + 0.5)), max(H, int(img.height * k + 0.5))), Image.LANCZOS)
    x, y = (r.width - W) // 2, (r.height - H) // 2
    return r.crop((x, y, x + W, y + H))


def format_number(v: float, decimals: int = 0) -> str:
    if decimals <= 0:
        return f"{int(round(v)):,}"
    return f"{v:,.{decimals}f}"
