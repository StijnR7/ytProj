"""Thumbnail + channel-art composition."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from .config import CHANNEL_DIR, load_config
from .render.backgrounds import Backdrop
from .render.common import CYAN, INK, ORANGE, WHITE, YELLOW, cover, drop_shadow, font, text_sprite, vertical_gradient, wrap
from .render.mascot import draw_zib

TW, TH = 1280, 720


def _glow_outline(sprite: Image.Image, color=(255, 255, 255), radius: int = 10) -> Image.Image:
    pad = radius * 3
    out = Image.new("RGBA", (sprite.width + pad * 2, sprite.height + pad * 2), (0, 0, 0, 0))
    a = Image.new("L", out.size, 0)
    a.paste(sprite.split()[3], (pad, pad))
    a = a.filter(ImageFilter.MaxFilter(radius * 2 + 1)).filter(ImageFilter.GaussianBlur(radius / 2))
    glow = Image.new("RGBA", out.size, (*color, 255))
    glow.putalpha(a)
    out.alpha_composite(glow)
    out.alpha_composite(sprite, (pad, pad))
    return out


def _headline(text: str, highlight: str, max_w: int, max_h: int) -> Image.Image:
    text = text.upper().strip()
    hl = {w.strip(".,!?").upper() for w in highlight.split()} if highlight else set()
    size = 190
    while size > 60:
        f = font("display", size)
        lines = wrap(text, f, max_w)
        if len(lines) <= 3 and len(lines) * size * 1.02 <= max_h:
            break
        size -= 6
    f = font("display", size)
    lines = wrap(text, f, max_w)
    lh = int(size * 1.02)
    stroke = max(6, size // 14)
    W = max_w + stroke * 4
    img = Image.new("RGBA", (W, lh * len(lines) + stroke * 4 + int(size * 0.2)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        x = stroke * 2
        for w in line.split():
            col = YELLOW if w.strip(".,!?").upper() in hl else WHITE
            d.text((x, stroke * 2 + i * lh), w, font=f, fill=col, stroke_width=stroke, stroke_fill=INK)
            x += f.getlength(w + " ")
    bbox = img.getbbox()
    img = img.crop(bbox) if bbox else img
    return drop_shadow(img, 12, 0.6, (0, 8))


def make_thumbnail(concept: dict, background: Image.Image | None, theme: str, out: Path) -> Path:
    layout = concept.get("layout", "left")
    bg = background or Backdrop(theme, (TW, TH), 11).frame(0)
    bg = cover(bg, (TW, TH))
    bg = ImageEnhance.Color(bg).enhance(1.35)
    bg = ImageEnhance.Contrast(bg).enhance(1.15).convert("RGBA")
    # darken behind the text for legibility
    shade = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for i in range(TW):
        if layout == "center":
            break
        x = i if layout == "left" else TW - 1 - i
        a = int(190 * max(0, 1 - i / (TW * 0.62)))
        sd.line([(x, 0), (x, TH)], fill=(8, 10, 30, a))
    if layout == "center":
        for y in range(TH):
            a = int(170 * max(0, 1 - y / (TH * 0.55)))
            sd.line([(0, y), (TW, y)], fill=(8, 10, 30, a))
    bg.alpha_composite(shade)

    expr = concept.get("mascot", "surprised")
    zib = _glow_outline(draw_zib(400 if layout != "center" else 300, expr), WHITE, 9)
    head = _headline(concept.get("text", ""), concept.get("highlight", ""), int(TW * (0.6 if layout != "center" else 0.86)), int(TH * (0.8 if layout != "center" else 0.48)))

    if layout == "left":
        bg.alpha_composite(head, (40, (TH - head.height) // 2))
        bg.alpha_composite(zib, (TW - zib.width + 30, TH - zib.height + 50))
    elif layout == "right":
        bg.alpha_composite(head, (TW - head.width - 40, (TH - head.height) // 2))
        bg.alpha_composite(zib, (-30, TH - zib.height + 50))
    else:
        bg.alpha_composite(head, ((TW - head.width) // 2, 30))
        bg.alpha_composite(zib, (TW - zib.width + 10, TH - zib.height + 40))
    out.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(out, quality=95)
    return out


def contact_sheet(paths: list[Path], out: Path) -> None:
    ims = [Image.open(p).resize((640, 360)) for p in paths]
    sheet = Image.new("RGB", (640 * len(ims) + 20 * (len(ims) + 1), 400), (20, 22, 30))
    for i, im in enumerate(ims):
        sheet.paste(im, (20 + i * 660, 20))
    sheet.save(out, quality=90)


# ------------------------------------------------------------------ channel branding
def make_branding(log=print) -> list[Path]:
    ch = load_config()["channel"]
    CHANNEL_DIR.mkdir(exist_ok=True)
    outs = []

    # profile picture 800x800 (displayed as a circle)
    pp = vertical_gradient((800, 800), (28, 52, 110), (15, 27, 61)).convert("RGBA")
    ring = Image.new("RGBA", (800, 800), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([60, 60, 740, 740], fill=(*ORANGE, 255))
    ImageDraw.Draw(ring).ellipse([90, 90, 710, 710], fill=(20, 36, 82, 255))
    pp.alpha_composite(ring)
    z = draw_zib(560, "happy")
    pp.alpha_composite(z, ((800 - z.width) // 2, 800 - z.height - 30))
    outs.append(CHANNEL_DIR / "profile_picture.png")
    pp.convert("RGB").save(outs[-1])

    # banner 2560x1440, safe area 1546x423 centred
    bn = Backdrop("brand", (2560, 1440), 4).frame(0).convert("RGBA")
    z = _glow_outline(draw_zib(380, "excited"), WHITE, 8)
    sx, sy = (2560 - 1546) // 2, (1440 - 423) // 2
    bn.alpha_composite(z, (sx + 20, sy + 423 // 2 - z.height // 2))
    name = text_sprite(ch["name"].upper(), "display", 150, fill=WHITE, stroke=8, stroke_fill=INK, shadow=10)
    tag = text_sprite(ch["tagline"], "heading_semi", 60, fill=CYAN, shadow=6)
    tx = sx + 20 + z.width + 20
    bn.alpha_composite(name, (tx, sy + 60))
    bn.alpha_composite(tag, (tx + 10, sy + 60 + name.height))
    outs.append(CHANNEL_DIR / "banner.png")
    bn.convert("RGB").save(outs[-1])

    # video watermark 150x150 (transparent)
    wm = Image.new("RGBA", (150, 150), (0, 0, 0, 0))
    z = draw_zib(128, "happy")
    wm.alpha_composite(z, ((150 - z.width) // 2, 150 - z.height))
    outs.append(CHANNEL_DIR / "watermark.png")
    wm.save(outs[-1])

    # expression sheet for reference / community posts
    from .render.mascot import EXPRESSIONS
    sheet = vertical_gradient((7 * 320 + 40, 400), (40, 60, 110), (15, 27, 61)).convert("RGBA")
    for i, e in enumerate(EXPRESSIONS):
        s = draw_zib(300, e)
        sheet.alpha_composite(s, (20 + i * 320, 30))
        lab = text_sprite(e, "heading_semi", 30, fill=WHITE)
        sheet.alpha_composite(lab, (20 + i * 320 + 150 - lab.width // 2, 350))
    outs.append(CHANNEL_DIR / "zib_expressions.png")
    sheet.convert("RGB").save(outs[-1])
    for o in outs:
        log(f"  wrote {o}")
    return outs
