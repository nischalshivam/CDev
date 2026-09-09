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

W, H = 1920, 1080          # default canvas; every card takes size=(w, h) to match the build
# The build renders 1280x720 while these cards were still drawn at 1920x1080 and overlaid at 0:0
# with no scale, so only the top-left 1280x720 of each card survived: centred text landed in the
# bottom-right corner and ran off the edge ("Quadrastee", "37 ft" half gone). Cards must be told
# the frame they are going into.
DISPLAY = "C:/Windows/Fonts/impact.ttf"      # condensed, heavy — documentary display face
BODY = "C:/Windows/Fonts/arialbd.ttf"
ACCENT = (214, 40, 40, 255)                  # blood red accent
WHITE = (245, 245, 245, 255)
MUTED = (176, 176, 176, 255)

# STYLE PROFILES — a channel's on-screen look is not universal. The boxing/sports-doc face is heavy
# Impact with a blood-red accent; a car-failure channel is the opposite — clean white sans-serif,
# almost no tracking, a data-green accent for numbers. Same card functions, different profile, so
# one typography module serves every niche instead of a per-channel fork.
STYLES = {
    "boxing": {"display": DISPLAY, "body": BODY, "accent": ACCENT,
               "upper": True, "tracking_scale": 1.0, "shadow": True},
    "clean":  {"display": "C:/Windows/Fonts/arialbd.ttf",
               "body": "C:/Windows/Fonts/arial.ttf", "accent": (46, 204, 113, 255),
               "upper": False, "tracking_scale": 0.35, "shadow": True},
    # sports scandal / biography: heavier than the explainer styles but not the fight-doc's
    # blood red — a colder crimson, all-caps, for a story about a man's death rather than a bout.
    "sportsdoc": {"display": "C:/Windows/Fonts/impact.ttf",
                  "body": "C:/Windows/Fonts/arialbd.ttf", "accent": (178, 34, 52, 255),
                  "upper": True, "tracking_scale": 0.8, "shadow": True},
    # defence/procurement: the cars niche's data-green reads as consumer-tech and is wrong here.
    # Restrained amber carries money and warning without turning a serious subject into a thriller.
    "defence": {"display": "C:/Windows/Fonts/arialbd.ttf",
                "body": "C:/Windows/Fonts/arial.ttf", "accent": (214, 162, 58, 255),
                "upper": True, "tracking_scale": 0.55, "shadow": True},
}


def _style(s):
    return STYLES.get(s, STYLES["boxing"]) if isinstance(s, str) else (s or STYLES["boxing"])


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
               size: int = 128, style="boxing", size_px=None) -> str:
    """Centred statement card — for a date, a place, a chapter line."""
    st = _style(style)
    case = (lambda s: s.upper()) if st["upper"] else (lambda s: s)
    W, H = size_px or (globals()["W"], globals()["H"])
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    lines = [l for l in case(main).split("\n") if l.strip()]
    fm = _font(st["display"], size)
    tr = 6 * st["tracking_scale"]
    heights = [size * 1.15 for _ in lines]
    total = sum(heights) + (26 if sub else 0)
    y = (H - total) / 2
    for ln in lines:
        w = _width(d, ln, fm, tr)
        _tracked(d, ((W - w) / 2, y), ln, fm, WHITE, tr, st["shadow"])
        y += size * 1.15
    # accent rule under the block
    rw = 190
    d.rectangle([(W - rw) / 2, y + 6, (W + rw) / 2, y + 12], fill=st["accent"])
    if sub:
        fs = _font(st["body"], 40)
        s = case(sub)
        w = _width(d, s, fs, 8 * st["tracking_scale"])
        _tracked(d, ((W - w) / 2, y + 34), s, fs, MUTED, 8 * st["tracking_scale"], st["shadow"])
    im.save(out)
    return str(out)


def lower_third(name: str, detail: str = "", out: str | Path = "lt.png") -> str:
    """Bottom-left identification label: accent bar + name + optional detail line."""
    W, H = size_px or (globals()["W"], globals()["H"])
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
              size: int = 300, style="boxing", size_px=None) -> str:
    """One huge number with a caption — the punch-line card (91 / SECONDS)."""
    st = _style(style)
    case = (lambda s: s.upper()) if st["upper"] else (lambda s: s)
    W, H = size_px or (globals()["W"], globals()["H"])
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fv = _font(st["display"], size)
    v = case(value)
    tr = 10 * st["tracking_scale"]
    vw = _width(d, v, fv, tr)
    y = H / 2 - size * 0.72
    # the number itself carries the accent in the clean style (data-green), white in boxing
    numfill = st["accent"] if (not st["upper"]) else WHITE
    _tracked(d, ((W - vw) / 2, y), v, fv, numfill, tr, st["shadow"])
    y += size * 1.02
    rw = 150
    d.rectangle([(W - rw) / 2, y + 10, (W + rw) / 2, y + 17], fill=st["accent"])
    if label:
        fl = _font(st["body"], 52)
        s = case(label)
        lw = _width(d, s, fl, 14 * st["tracking_scale"])
        _tracked(d, ((W - lw) / 2, y + 44), s, fl, MUTED, 14 * st["tracking_scale"], st["shadow"])
    im.save(out)
    return str(out)


def _wrap(draw, text, font, max_w, tracking=0):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if _width(draw, t, font, tracking) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def quote_card(text: str, attribution: str = "", out: str | Path = "quote.png",
               size: int = 60, style="clean", size_px=None) -> str:
    """A spoken line held on screen as text.

    Straight from the competitor teardown: when the narration quotes somebody, the reference
    channels stop the pictures and put the words up — white, centred, on black. It is the cheapest
    shot in the video and one of the most convincing, because the viewer reads the evidence instead
    of being told about it."""
    st = _style(style)
    W, H = size_px or (globals()["W"], globals()["H"])
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = _font(st["body"], size)
    tr = 2 * st["tracking_scale"]
    body = text if text.strip().startswith(('"', '“')) else f'"{text.strip()}"'
    lines = _wrap(d, body, f, int(W * 0.74), tr)
    total = len(lines) * size * 1.34 + (54 if attribution else 0)
    y = (H - total) / 2
    for ln in lines:
        w = _width(d, ln, f, tr)
        _tracked(d, ((W - w) / 2, y), ln, f, WHITE, tr, st["shadow"])
        y += size * 1.34
    if attribution:
        fa = _font(st["body"], int(size * 0.52))
        a = ("— " + attribution).upper() if st["upper"] else ("— " + attribution)
        w = _width(d, a, fa, 6 * st["tracking_scale"])
        _tracked(d, ((W - w) / 2, y + 16), a, fa, st["accent"], 6 * st["tracking_scale"], st["shadow"])
    im.save(out)
    return str(out)


def highlight(src_image: str | Path, box, out: str | Path,
              colour=(255, 214, 0), alpha: int = 90) -> str:
    """Lay a translucent marker-pen box over part of a document still.

    This is the single most repeated device in the competitor's cars video: a spec sheet or window
    sticker on screen with the ONE line being narrated highlighted in yellow. It converts a wall of
    unreadable small print into a specific piece of evidence, which is the difference between
    showing a document and using one.

    box is normalised (x, y, w, h) in 0-1 so the same spec works at any resolution."""
    im = Image.open(src_image).convert("RGBA")
    w, h = im.size
    x0, y0, bw, bh = box
    lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(lay)
    rect = [int(x0 * w), int(y0 * h), int((x0 + bw) * w), int((y0 + bh) * h)]
    dr.rectangle(rect, fill=colour + (alpha,))
    dr.rectangle(rect, outline=colour + (220,), width=max(2, int(h * 0.004)))
    Image.alpha_composite(im, lay).convert("RGB").save(out, quality=94)
    return str(out)


if __name__ == "__main__":
    out = Path("typo_demo"); out.mkdir(exist_ok=True)
    print(title_card("JUNE 27, 1988", "Atlantic City", out / "t.png"))
    print(lower_third("Michael Spinks", "31-0  ·  undefeated", out / "l.png"))
    print(stat_card("91", "seconds", out / "s.png"))
