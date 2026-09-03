#!/usr/bin/env python3
"""
typography.py — real on-screen text, rendered with PIL instead of ffmpeg drawtext.

Why not drawtext: it gives you a font, a box and nothing else. No letter-spacing, no accent rules,
no layered shadow, no stat layouts. The first cut of this system used drawtext and the text read as
"basic" — correctly. PIL renders an RGBA overlay we then fade/slide in with ffmpeg, which gets us
broadcast-looking cards without a motion-graphics dependency.

Three card types, all transparent PNGs at 1920x1080:
    title_card(main, sub)        centred statement card (chapter / date / place)
    lower_third(name, detail)    bottom-left label with an accent bar
    stat_card(value, label)      one huge number + caption (91 / SECONDS)

    from typography import title_card, lower_third, stat_card
    png = stat_card("91", "SECONDS", "out/stat.png")
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
DISPLAY = "C:/Windows/Fonts/impact.ttf"      # condensed, heavy — documentary display face
BODY = "C:/Windows/Fonts/arialbd.ttf"
ACCENT = (214, 40, 40, 255)                  # blood red accent
WHITE = (245, 245, 245, 255)
MUTED = (176, 176, 176, 255)


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _tracked(draw, xy, text, font, fill, tracking=0, shadow=True):
    """Draw text with letter-spacing (tracking) and a soft drop shadow."""
    x, y = xy
    for ch in text:
        if shadow:
            draw.text((x + 3, y + 4), ch, font=font, fill=(0, 0, 0, 170))
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x - xy[0]


def _width(draw, text, font, tracking=0):
    return sum(draw.textlength(c, font=font) for c in text) + tracking * max(0, len(text) - 1)


def title_card(main: str, sub: str = "", out: str | Path = "title.png",
               size: int = 128) -> str:
    """Centred statement card — for a date, a place, a chapter line."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    lines = [l for l in main.upper().split("\n") if l.strip()]
    fm = _font(DISPLAY, size)
    tr = 6
    heights = [size * 1.15 for _ in lines]
    total = sum(heights) + (26 if sub else 0)
    y = (H - total) / 2
    for ln in lines:
        w = _width(d, ln, fm, tr)
        _tracked(d, ((W - w) / 2, y), ln, fm, WHITE, tr)
        y += size * 1.15
    # accent rule under the block
    rw = 190
    d.rectangle([(W - rw) / 2, y + 6, (W + rw) / 2, y + 12], fill=ACCENT)
    if sub:
        fs = _font(BODY, 40)
        s = sub.upper()
        w = _width(d, s, fs, 8)
        _tracked(d, ((W - w) / 2, y + 34), s, fs, MUTED, 8)
    im.save(out)
    return str(out)


def lower_third(name: str, detail: str = "", out: str | Path = "lt.png") -> str:
    """Bottom-left identification label: accent bar + name + optional detail line."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fn = _font(DISPLAY, 62)
    fd = _font(BODY, 30)
    x0, base = 96, H - 190
    nm = name.upper()
    nw = _width(d, nm, fn, 3)
    dw = _width(d, detail.upper(), fd, 5) if detail else 0
    plate_w = int(max(nw, dw) + 78)
    plate_h = 150 if detail else 108
    # translucent plate + accent bar
    d.rectangle([x0 - 30, base - 26, x0 - 30 + plate_w, base - 26 + plate_h], fill=(8, 8, 10, 190))
    d.rectangle([x0 - 30, base - 26, x0 - 20, base - 26 + plate_h], fill=ACCENT)
    _tracked(d, (x0, base - 8), nm, fn, WHITE, 3)
    if detail:
        _tracked(d, (x0 + 3, base + 68), detail.upper(), fd, MUTED, 5)
    im.save(out)
    return str(out)


def stat_card(value: str, label: str = "", out: str | Path = "stat.png",
              size: int = 300) -> str:
    """One huge number with a caption — the punch-line card (91 / SECONDS)."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fv = _font(DISPLAY, size)
    v = value.upper()
    vw = _width(d, v, fv, 10)
    y = H / 2 - size * 0.72
    _tracked(d, ((W - vw) / 2, y), v, fv, WHITE, 10)
    y += size * 1.02
    rw = 150
    d.rectangle([(W - rw) / 2, y + 10, (W + rw) / 2, y + 17], fill=ACCENT)
    if label:
        fl = _font(BODY, 52)
        s = label.upper()
        lw = _width(d, s, fl, 14)
        _tracked(d, ((W - lw) / 2, y + 44), s, fl, MUTED, 14)
    im.save(out)
    return str(out)


if __name__ == "__main__":
    out = Path("typo_demo"); out.mkdir(exist_ok=True)
    print(title_card("JUNE 27, 1988", "Atlantic City", out / "t.png"))
    print(lower_third("Michael Spinks", "31-0  ·  undefeated", out / "l.png"))
    print(stat_card("91", "seconds", out / "s.png"))
