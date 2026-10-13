"""hf_kit.py — reusable HyperFrames devices for CDev (EDL-driven, any niche).

Born from the Wedgetail defence sample + the map v2 skills test (2026-10-13). Every device returns
(html, tweens) and is placed by start/duration on the main timeline; `page()` assembles index.html, `render()`
lints + renders. Motion follows the installed skills:
  gsap-plugins  : DrawSVG (route draw), MotionPath (ship/plane along a route, autoRotate), SplitText (title per
                  char), ScrambleText (chip "decode"), CustomEase (signature ease). ALL plugins are vendored in
                  hf_assets/js — a CDN fetch failed mid-render once (measured), so never load them from a CDN.
  motion-design : one personality per video (default Corporate/Premium): signature ease 0.2,0,0,1; exits
                  0.3,0,1,1; duration palette Q/STD/SLOW; entrances ease-out, exits ease-in; stagger <= 40 ms
                  per item, total < 500 ms; camera moves split into keyframed legs; primary + secondary + ambient.
HyperFrames lint rules learnt the hard way (each one failed `hyperframes check` once):
  - never tween letterSpacing (pixel-snaps) -> SplitText chars + y/opacity
  - a full-frame scene must start at opacity 0 via gsap.set (outside the timeline) -> page() does it for scenes
  - never put a CSS `transform` on an element GSAP animates (use gsap.set for the start value)
  - draw strokes with DrawSVG, not a CSS stroke-dasharray
  - one root composition file per folder (no stray *.html copies next to index.html)
Usage sketch:
    from hf_kit import *
    proj = setup_project("work/hf")
    parts = [footage(...), date_box(...), map_scene(...), ...]
    page(proj, parts, duration=106.3); render(proj, "out/silent.mp4")
"""
from __future__ import annotations
import json, math, re, shutil, subprocess
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "hf_assets"
NAVY, GOLD, CYAN, TEAL, PIN = "#0b2545", "#FFC94D", "#78E2FF", "#0C7393", "#FF5A4E"
Q, STD, SLOW = 0.35, 0.6, 1.2            # duration palette (motion-design)
_uid = [0]


def _id(prefix):
    _uid[0] += 1
    return f"{prefix}{_uid[0]}"


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace("'", "&rsquo;").replace('"', "&quot;"))


# ------------------------------------------------------------------ project
def setup_project(d) -> Path:
    """Create a HyperFrames project folder with the vendored js + fonts."""
    d = Path(d); (d / "assets").mkdir(parents=True, exist_ok=True)
    for sub in ("js", "fonts"):
        dst = d / "assets" / sub
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(ASSETS / sub, dst)
    (d / "hyperframes.json").write_text(json.dumps({
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
        "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
        "media": {"autoProxy": True}}, indent=2), encoding="utf-8")
    for stray in d.glob("*.html"):
        if stray.name != "index.html":
            stray.unlink()                 # lint: multiple root compositions
    return d


BASE_CSS = """
@font-face{font-family:"IB";src:url("assets/fonts/Inter-Bold.ttf")}
@font-face{font-family:"IS";src:url("assets/fonts/Inter-SemiBold.ttf")}
@font-face{font-family:"IX";src:url("assets/fonts/InterDisplay-Black.ttf")}
@font-face{font-family:"RC";src:url("assets/fonts/Roboto-Condensed.ttf")}
@font-face{font-family:"EBG";src:url("assets/fonts/EB-Garamond.ttf")}
@font-face{font-family:"HAND";src:url("assets/fonts/Caveat.ttf")}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1920px;height:1080px;overflow:hidden;background:#000}
#root{position:relative;width:100%;height:100%;overflow:hidden;background:#000}
.shot{position:absolute;inset:0;transform-origin:50% 50%}
.shot video,.shot img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.ov{position:absolute;inset:0;pointer-events:none}
.scene{position:absolute;inset:0;overflow:hidden;background:#05080b}
.bg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.blur{filter:blur(10px) saturate(.7)}
.dim2{position:absolute;inset:0;background:radial-gradient(ellipse at 50% 50%,rgba(4,10,18,.55),rgba(4,10,18,.88))}
.vign{position:absolute;inset:0;background:radial-gradient(ellipse at 50% 50%,rgba(0,0,0,0) 52%,rgba(0,0,0,.55) 100%)}
.lt{display:flex;flex-direction:column;align-items:flex-start;justify-content:flex-end;padding:0 0 92px 84px}
.lt .d{display:inline-block;background:%NAVY%;color:#fff;font-family:"IX";font-size:36px;padding:6px 18px}
.lt .c{display:inline-block;margin-top:8px;background:#fff;color:%NAVY%;font-family:"IB";font-size:24px;padding:9px 18px;letter-spacing:.03em}
.chip{position:absolute;font-family:"IB";font-size:30px;color:#fff;background:%NAVY%;padding:8px 18px;letter-spacing:.04em;box-shadow:0 10px 30px rgba(0,0,0,.45)}
.chip small{display:block;font-family:"RC";font-weight:700;font-size:20px;letter-spacing:.18em;color:#9fd4ff}
.map{background:radial-gradient(ellipse at 50% 45%,#1d3140 0%,#0c141b 80%)}
.world{position:absolute;left:0;top:0;transform-origin:0 0}
.land{fill:#33495a;stroke:#4d6b80;stroke-width:1.2}
.grid line{stroke:rgba(120,226,255,.07);stroke-width:1}
.son{fill:none;stroke:rgba(120,226,255,.35);stroke-width:3}
.route{fill:none;stroke:%GOLD%;stroke-width:5;stroke-linecap:round}
.routeGlow{fill:none;stroke:rgba(255,201,77,.25);stroke-width:18;stroke-linecap:round}
.pin{fill:%PIN%}.ring{fill:none;stroke:#fff;stroke-width:3}
""".replace("%NAVY%", NAVY).replace("%GOLD%", GOLD).replace("%PIN%", PIN)

JS_HEAD = "".join(f'<script src="assets/js/{n}.min.js"></script>' for n in
                  ("gsap", "MotionPathPlugin", "DrawSVGPlugin", "SplitText", "ScrambleTextPlugin", "CustomEase"))
JS_INIT = ('gsap.registerPlugin(MotionPathPlugin, DrawSVGPlugin, SplitText, ScrambleTextPlugin, CustomEase);\n'
           'CustomEase.create("sig","0.2,0,0,1");CustomEase.create("sigIn","0.3,0,1,1");\n')


class Part:
    """One timeline element: html + tweens (+ js run before the timeline, + full-frame scene ids to pre-hide)."""

    def __init__(self, html="", tweens=(), pre=(), hide=(), css=""):
        self.html, self.tweens, self.pre, self.hide, self.css = html, list(tweens), list(pre), list(hide), css


def page(proj, parts, duration, extra_css="", fade_out=0.45):
    proj = Path(proj)
    css = BASE_CSS + extra_css + "".join(p.css for p in parts)
    body = "\n".join(p.html for p in parts)
    hide = [h for p in parts for h in p.hide]
    pre = "\n".join(x for p in parts for x in p.pre)
    tw = "\n".join(t for p in parts for t in p.tweens)
    fade = (f'tl.fromTo("#fade",{{opacity:0}},{{opacity:1,duration:{fade_out},ease:"sigIn"}},{duration - fade_out:.2f});'
            if fade_out else "")
    html = (f'<!doctype html><html lang="en" data-resolution="landscape"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=1920, height=1080">{JS_HEAD}<style>{css}'
            f'#fade{{position:absolute;inset:0;background:#000;opacity:0}}</style></head><body>'
            f'<div id="root" data-composition-id="main" data-start="0" data-duration="{duration}" '
            f'data-width="1920" data-height="1080">{body}<div id="fade"></div></div>\n<script>\n{JS_INIT}'
            + (f'gsap.set({json.dumps(["#" + h for h in hide])},{{opacity:0}});\n' if hide else "")
            + f'{pre}\nconst tl = gsap.timeline({{paused:true}});\n{tw}\n{fade}\n'
            f'window.__timelines["main"] = tl;\ntl.seek(0);\n</script></body></html>')
    (proj / "index.html").write_text(html, encoding="utf-8")
    return proj / "index.html"


def check(proj) -> bool:
    r = subprocess.run("hyperframes check", shell=True, cwd=proj, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)
    ok = "Check passed" in out
    if not ok:
        print("\n".join(l for l in out.splitlines() if "✗" in l or "error" in l.lower())[:2000])
    return ok


def render(proj, out, strict=False) -> Path:
    if not check(proj) and strict:
        raise RuntimeError("hyperframes check failed")
    out = Path(out).resolve()
    subprocess.run(f'hyperframes render -o "{out}"', shell=True, cwd=proj, check=True)
    return out


# ------------------------------------------------------------------ footage & text devices
def footage(src, a, b, push=1.035, track=0):
    """A pre-cut H.264 clip (Chrome can't decode HEVC/mkv) with the 3.5 % documentary push."""
    i = _id("s")       # the <video> needs its own id or HyperFrames renders it FROZEN (lint: media_missing_id)
    return Part(f'<div class="shot" id="{i}"><video id="{i}v" class="clip" src="{src}" data-start="{a:.2f}" '
                f'data-duration="{b - a:.2f}" data-track-index="{track}" muted playsinline></video></div>',
                [f'tl.fromTo("#{i}",{{scale:1}},{{scale:{push},duration:{b - a:.2f},ease:"none"}},{a:.2f});'])


def date_box(a, d, top, sub, track=2):
    """Reference-channel lower third: navy box + white caption bar, wiping in one after the other."""
    i = _id("lt")
    return Part(f'<div id="{i}" class="clip ov lt" data-start="{a:.2f}" data-duration="{d:.2f}" data-track-index="{track}">'
                f'<span class="d">{esc(top)}</span><span class="c">{esc(sub)}</span></div>',
                [f'tl.fromTo("#{i} .d",{{clipPath:"inset(0 100% 0 0)"}},{{clipPath:"inset(0 0% 0 0)",duration:{Q},ease:"sig"}},{a:.2f});',
                 f'tl.fromTo("#{i} .c",{{clipPath:"inset(0 100% 0 0)"}},{{clipPath:"inset(0 0% 0 0)",duration:{STD},ease:"sig"}},{a + 0.12:.2f});',
                 f'tl.to("#{i}",{{opacity:0,duration:0.25,ease:"sigIn"}},{a + d - 0.25:.2f});'])


def title(a, d, main, kicker="", track=2, size=128):
    """Lower-left title: kicker, then the main word per char (SplitText, 30 ms cascade), gold rule."""
    i = _id("ti")
    css = (f'#{i}{{display:flex;flex-direction:column;justify-content:flex-end;padding:0 0 150px 120px}}'
           f'#{i} .k{{font-family:"RC";font-weight:700;font-size:30px;letter-spacing:.32em;color:#9fd4ff;text-shadow:0 2px 12px rgba(0,0,0,.6)}}'
           f'#{i} .m{{font-family:"IX";font-size:{size}px;color:#fff;line-height:1.02;text-shadow:0 6px 30px rgba(0,0,0,.55)}}'
           f'#{i} .r{{width:240px;height:6px;background:{GOLD};margin-top:14px;transform-origin:0 50%}}')
    return Part(f'<div id="{i}" class="clip ov" data-start="{a:.2f}" data-duration="{d:.2f}" data-track-index="{track}">'
                f'<div class="k">{esc(kicker)}</div><div class="m">{esc(main)}</div><div class="r"></div></div>',
                [f'tl.fromTo("#{i} .k",{{opacity:0,y:14}},{{opacity:1,y:0,duration:{STD},ease:"sig"}},{a + 0.1:.2f});',
                 f'tl.from(SplitText.create("#{i} .m",{{type:"chars"}}).chars,{{y:40,opacity:0,duration:{STD},ease:"sig",stagger:0.03}},{a + 0.2:.2f});',
                 f'tl.fromTo("#{i} .r",{{scaleX:0}},{{scaleX:1,duration:{STD},ease:"sig"}},{a + 0.6:.2f});',
                 f'tl.to("#{i}",{{opacity:0,duration:0.4,ease:"sigIn"}},{a + d - 0.4:.2f});'], css=css)


def year_card(a, d, year, track=3):
    i = _id("yr")
    css = (f'#{i}{{display:flex;flex-direction:column;align-items:center;justify-content:center;'
           f'background:radial-gradient(ellipse at 50% 50%,rgba(0,0,0,.45),rgba(0,0,0,0) 60%)}}'
           f'#{i} .n{{font-family:"IX";font-size:250px;color:#fff;text-shadow:0 8px 40px rgba(0,0,0,.6)}}'
           f'#{i} .r{{width:180px;height:7px;background:{GOLD};margin-top:-6px}}')
    return Part(f'<div id="{i}" class="clip ov" data-start="{a:.2f}" data-duration="{d:.2f}" data-track-index="{track}">'
                f'<div class="n">{esc(str(year))}</div><div class="r"></div></div>',
                [f'tl.fromTo("#{i} .n",{{opacity:0,scale:1.14}},{{opacity:1,scale:1,duration:0.38,ease:"sig"}},{a:.2f});',
                 f'tl.to("#{i} .n",{{scale:1.03,duration:{max(0.1, d - 0.7):.2f},ease:"none"}},{a + 0.4:.2f});',
                 f'tl.fromTo("#{i} .r",{{scaleX:0}},{{scaleX:1,duration:0.42,ease:"sig"}},{a + 0.1:.2f});',
                 f'tl.to("#{i}",{{opacity:0,duration:0.3,ease:"sigIn"}},{a + d - 0.3:.2f});'], css=css)


def chapter_card(a, d, kicker, word, ground_img, track=1):
    i = _id("ch")
    css = (f'#{i}{{display:flex;flex-direction:column;align-items:center;justify-content:center}}'
           f'#{i} .k,#{i} .t,#{i} .r{{position:relative}}'
           f'#{i} .k{{font-family:"RC";font-weight:700;font-size:32px;letter-spacing:.5em;color:{GOLD}}}'
           f'#{i} .t{{font-family:"IX";font-size:150px;color:#fff;letter-spacing:.04em}}'
           f'#{i} .r{{width:220px;height:6px;background:{GOLD}}}')
    return Part(f'<div id="{i}" class="clip scene" data-start="{a:.2f}" data-duration="{d:.2f}" data-track-index="{track}">'
                f'<img class="bg blur" src="{ground_img}"><div class="dim2"></div>'
                f'<div class="k">{esc(kicker)}</div><div class="t">{esc(word)}</div><div class="r"></div></div>',
                [f'tl.fromTo("#{i}",{{opacity:0}},{{opacity:1,duration:0.6,ease:"sig"}},{a:.2f});',
                 f'tl.fromTo("#{i} .bg",{{scale:1.04}},{{scale:1.1,duration:{d:.2f},ease:"none"}},{a:.2f});',
                 f'tl.fromTo("#{i} .k",{{opacity:0,y:-12}},{{opacity:1,y:0,duration:{STD},ease:"sig"}},{a + 0.4:.2f});',
                 f'tl.from(SplitText.create("#{i} .t",{{type:"chars"}}).chars,{{y:50,opacity:0,duration:{STD},ease:"sig",stagger:0.035}},{a + 0.6:.2f});',
                 f'tl.fromTo("#{i} .r",{{scaleX:0}},{{scaleX:1,duration:{STD},ease:"sig"}},{a + 1.1:.2f});',
                 f'tl.to("#{i}",{{opacity:0,duration:0.5,ease:"sigIn"}},{a + d - 0.5:.2f});'], hide=[i], css=css)


def bullet_list(a, d, heading, items, source="", track=2):
    """Requirement / spec list over footage. items = [(text, t_absolute)] — each lands on its word."""
    i = _id("bl")
    css = (f'#{i} .sh{{position:absolute;inset:0;background:linear-gradient(90deg,rgba(4,10,18,.72) 0%,rgba(4,10,18,.45) 42%,rgba(4,10,18,0) 70%)}}'
           f'#{i} .h{{position:absolute;left:110px;top:150px;font-family:"RC";font-weight:700;font-size:30px;letter-spacing:.3em;color:{GOLD}}}'
           f'#{i} .it{{position:absolute;left:110px;font-family:"IX";font-size:46px;color:#fff;display:flex;align-items:center}}'
           f'#{i} .it i{{display:inline-block;width:22px;height:22px;background:{GOLD};margin-right:26px}}'
           f'#{i} .src{{position:absolute;left:112px;top:{240 + 100 * len(items) + 30}px;font-family:"IB";font-size:22px;color:rgba(255,255,255,.6)}}')
    rows = "".join(f'<div class="it" id="{i}_{k}" style="top:{230 + 100 * k}px"><i></i>{esc(t)}</div>'
                   for k, (t, _) in enumerate(items))
    tw = [f'tl.fromTo("#{i} .sh",{{opacity:0}},{{opacity:1,duration:{STD}}},{a:.2f});',
          f'tl.fromTo("#{i} .h",{{opacity:0,x:-30}},{{opacity:1,x:0,duration:{STD},ease:"sig"}},{a + 0.3:.2f});']
    for k, (_, t) in enumerate(items):
        tw += [f'tl.fromTo("#{i}_{k}",{{opacity:0,x:-26}},{{opacity:1,x:0,duration:{Q},ease:"sig"}},{t - 0.1:.2f});',
               f'tl.fromTo("#{i}_{k} i",{{scale:0}},{{scale:1,duration:0.3,ease:"back.out(2.2)"}},{t:.2f});']
    tw.append(f'tl.to("#{i}",{{opacity:0,duration:0.4,ease:"sigIn"}},{a + d - 0.4:.2f});')
    return Part(f'<div id="{i}" class="clip ov" data-start="{a:.2f}" data-duration="{d:.2f}" data-track-index="{track}">'
                f'<div class="sh"></div><div class="h">{esc(heading)}</div>{rows}'
                + (f'<div class="src">{esc(source)}</div>' if source else "") + '</div>', tw, css=css)


def size_bars(a, d, heading, sub, rows, unit="m", ground_img=None, source="", track=1):
    """Comparison bars counting up. rows = [(name, origin, value, highlight_bool)]."""
    i = _id("sz")
    vmax = max(r[2] for r in rows)
    css = (f'#{i} .t{{position:absolute;left:150px;top:150px;font-family:"IX";font-size:84px;color:#fff}}'
           f'#{i} .s{{position:absolute;left:154px;top:258px;font-family:"RC";font-weight:700;font-size:28px;letter-spacing:.32em;color:#9fd4ff}}'
           f'#{i} .row{{position:absolute;left:150px;width:1620px;height:120px;display:flex;align-items:center}}'
           f'#{i} .n{{width:420px;font-family:"IX";font-size:44px;color:#fff;line-height:1}}'
           f'#{i} .n small{{display:block;font-family:"RC";font-weight:700;font-size:20px;letter-spacing:.2em;color:#9fd4ff;margin-top:8px}}'
           f'#{i} .bar{{flex:1;height:34px;background:rgba(255,255,255,.08);margin:0 30px}}'
           f'#{i} .f{{height:100%;transform-origin:0 50%}}'
           f'#{i} .v{{width:200px;font-family:"IX";font-size:46px;color:#fff;text-align:right}}'
           f'#{i} .src{{position:absolute;right:150px;bottom:90px;font-family:"IB";font-size:20px;color:rgba(255,255,255,.6)}}')
    html = (f'<div id="{i}" class="clip scene" data-start="{a:.2f}" data-duration="{d:.2f}" data-track-index="{track}">'
            + (f'<img class="bg blur" src="{ground_img}"><div class="dim2"></div>' if ground_img else "")
            + f'<div class="t">{esc(heading)}</div><div class="s">{esc(sub)}</div>')
    tw = [f'tl.fromTo("#{i}",{{opacity:0}},{{opacity:1,duration:0.3}},{a:.2f});',
          f'tl.from(SplitText.create("#{i} .t",{{type:"chars"}}).chars,{{y:30,opacity:0,duration:{STD},ease:"sig",stagger:0.025}},{a + 0.3:.2f});',
          f'tl.fromTo("#{i} .s",{{opacity:0}},{{opacity:1,duration:0.4}},{a + 0.5:.2f});']
    for k, (name, origin, val, hi) in enumerate(rows):
        t = a + 0.8 + 0.4 * k
        html += (f'<div class="row" id="{i}_{k}" style="top:{390 + 170 * k}px"><div class="n">{esc(name)}<small>{esc(origin)}</small></div>'
                 f'<div class="bar"><div class="f" style="width:{val / vmax * 100:.1f}%;background:{GOLD if hi else "#8FA5B4"}"></div></div>'
                 f'<div class="v" id="{i}_v{k}">0 {unit}</div></div>')
        dec = 1 if val < 100 else 0
        tw += [f'tl.fromTo("#{i}_{k}",{{opacity:0,y:18}},{{opacity:1,y:0,duration:{Q},ease:"sig"}},{t:.2f});',
               f'tl.fromTo("#{i}_{k} .f",{{scaleX:0}},{{scaleX:1,duration:0.8,ease:"sig"}},{t + 0.1:.2f});',
               f'(function(){{const o={{v:0}};tl.to(o,{{v:{val},duration:0.8,ease:"sig",onUpdate:()=>{{'
               f'document.querySelector("#{i}_v{k}").textContent=o.v.toFixed({dec})+" {unit}"}}}},{t + 0.1:.2f});}})();']
    html += (f'<div class="src">{esc(source)}</div>' if source else "") + "</div>"
    return Part(html, tw, hide=[i], css=css)


# ------------------------------------------------------------------ maps
_GEO = None


def _geo():
    global _GEO
    if _GEO is None:
        _GEO = json.load(open(ASSETS / "world_110m.geojson", encoding="utf-8"))["features"]
    return _GEO


def proj(lon, lat):
    """Web-Mercator onto a 4000 px world."""
    lat = max(-84, min(84, lat))
    x = (lon + 180) / 360 * 4000
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * 4000
    return x, y


def _path(geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    return "".join("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in (proj(lo, la) for lo, la in ring)) + "Z"
                   for poly in polys for ring in poly)


def map_scene(a, d, cams, highlight=(), pins=(), routes=(), chips=(), sonar=None, heading="", sub="", track=1):
    """Two-tone 'midnight' map (Frontier Style 1 grammar, defence palette).
    cams      : [(t_rel, scale, lon, lat)] camera keyframes — first is the opening view; legs ease sine.inOut.
    highlight : [(country ADMIN name, t_rel)] — fills teal on t.
    pins      : [(lon, lat, t_rel)] — pop + ripple rings.
    routes    : [((lon,lat), (lon,lat), t_rel, dur, bend)] — DrawSVG line + a vessel riding it (MotionPath).
    chips     : [(x_px, y_px, small, text, t_rel, dur)] — screen-space label that ScrambleText-decodes.
    sonar     : (lon, lat, t_rel) — three expanding rings (ambient layer).
    """
    i = _id("mp")
    names = {h[0] for h in highlight}
    land, hi = [], {}
    for f in _geo():
        n = f["properties"]["ADMIN"]
        (hi.__setitem__(n, _path(f["geometry"])) if n in names else land.append(_path(f["geometry"])))
    grid = "".join(f'<line x1="{x}" y1="0" x2="{x}" y2="4000"/>' for x in range(0, 4000, 111)) + \
           "".join(f'<line x1="0" y1="{y}" x2="4000" y2="{y}"/>' for y in range(0, 4000, 111))
    svg = [f'<svg id="{i}w" class="world" width="4000" height="4000" viewBox="0 0 4000 4000">',
           f'<g class="grid" id="{i}g">{grid}</g><path class="land" d="{"".join(land)}"/>']
    for k, (n, _) in enumerate(highlight):
        svg.append(f'<path id="{i}h{k}" class="land" d="{hi.get(n, "")}" style="stroke-width:2.2"/>')
    if sonar:
        sx, sy = proj(sonar[0], sonar[1])
        svg.append("".join(f'<circle class="son {i}son" cx="{sx:.1f}" cy="{sy:.1f}" r="40"/>' for _ in range(3)))
    for k, (p0, p1, _, _, bend) in enumerate(routes):
        x0, y0 = proj(*p0); x1, y1 = proj(*p1)
        dx, dy = x1 - x0, y1 - y0
        c1 = (x0 + dx * 0.3 - dy * bend, y0 + dy * 0.3 + dx * bend)
        c2 = (x0 + dx * 0.7 - dy * bend, y0 + dy * 0.7 + dx * bend)
        dd = f"M{x0:.1f},{y0:.1f} C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {x1:.1f},{y1:.1f}"
        svg.append(f'<path id="{i}rg{k}" class="routeGlow" d="{dd}"/><path id="{i}r{k}" class="route" d="{dd}"/>'
                   f'<g id="{i}v{k}"><path d="M-22,-9 L18,-9 L28,0 L18,9 L-22,9 Z" fill="{GOLD}" stroke="{NAVY}" stroke-width="3"/></g>')
    for k, (lo, la, _) in enumerate(pins):
        x, y = proj(lo, la)
        svg.append(f'<circle class="pin" id="{i}p{k}" cx="{x:.1f}" cy="{y:.1f}" r="10"/>'
                   f'<circle class="ring" id="{i}q{k}" cx="{x:.1f}" cy="{y:.1f}" r="10"/>')
    svg.append("</svg>")
    head = ""
    if heading:
        head = (f'<div id="{i}t" style="position:absolute;left:110px;top:90px;font-family:IX;font-size:64px;color:#fff">{esc(heading)}</div>'
                f'<div id="{i}s" style="position:absolute;left:112px;top:170px;font-family:RC;font-weight:700;font-size:26px;letter-spacing:.32em;color:{GOLD}">{esc(sub)}</div>')
    chip_html = "".join(f'<div class="chip" id="{i}c{k}" style="left:{x}px;top:{y}px"><small>{esc(sm)}</small>'
                        f'<span id="{i}ct{k}">{esc(tx)}</span></div>' for k, (x, y, sm, tx, _, _) in enumerate(chips))
    html = (f'<div id="{i}" class="clip scene map" data-start="{a:.2f}" data-duration="{d:.2f}" data-track-index="{track}">'
            + "".join(svg) + '<div class="vign"></div>' + head + chip_html + "</div>")

    def cam(s, lo, la):
        x, y = proj(lo, la)
        return f"{{scale:{s},x:{960 - x * s:.1f},y:{540 - y * s:.1f}}}"
    t0, s0, lo0, la0 = cams[0]
    pre = [f'gsap.set("#{i}w",{cam(s0, lo0, la0)});']
    pre += [f'gsap.set(["#{i}r{k}","#{i}rg{k}"],{{drawSVG:"0%"}});gsap.set("#{i}v{k}",{{opacity:0}});' for k in range(len(routes))]
    pre += [f'gsap.set("#{i}c{k}",{{opacity:0}});' for k in range(len(chips))]
    tw = [f'tl.fromTo("#{i}",{{opacity:0}},{{opacity:1,duration:0.3,ease:"sig"}},{a:.2f});',
          f'tl.fromTo("#{i}g",{{x:0}},{{x:-111,duration:{d:.2f},ease:"none"}},{a:.2f});']       # ambient drift
    prev = cams[0]
    for t, s, lo, la in cams[1:]:
        tw.append(f'tl.to("#{i}w",{{...{cam(s, lo, la)},duration:{t - prev[0]:.2f},ease:"sine.inOut"}},{a + prev[0]:.2f});')
        prev = (t, s, lo, la)
    if heading:
        tw += [f'tl.from(SplitText.create("#{i}t",{{type:"chars"}}).chars,{{y:40,opacity:0,duration:{STD},ease:"sig",stagger:0.03}},{a + 0.3:.2f});',
               f'tl.fromTo("#{i}s",{{opacity:0,y:12}},{{opacity:1,y:0,duration:{STD},ease:"sig"}},{a + 0.7:.2f});']
    for k, (_, t) in enumerate(highlight):
        tw.append(f'tl.to("#{i}h{k}",{{fill:"{TEAL}",stroke:"{CYAN}",duration:{STD},ease:"sig"}},{a + t:.2f});')
    if sonar:
        tw.append(f'tl.fromTo(".{i}son",{{attr:{{r:40}},opacity:0.9}},{{attr:{{r:900}},opacity:0,duration:2.4,ease:"sine.out",stagger:0.8}},{a + sonar[2]:.2f});')
    for k, (_, _, t) in enumerate(pins):
        tw += [f'tl.fromTo("#{i}p{k}",{{scale:0,transformOrigin:"50% 50%"}},{{scale:1,duration:{Q},ease:"back.out(2.2)"}},{a + t:.2f});',
               f'tl.fromTo("#{i}q{k}",{{attr:{{r:10}},opacity:1}},{{attr:{{r:70}},opacity:0,duration:1.1,repeat:2,ease:"sig"}},{a + t + 0.1:.2f});']
    for k, (_, _, t, dur, _) in enumerate(routes):
        tw += [f'tl.to(["#{i}rg{k}","#{i}r{k}"],{{drawSVG:"100%",duration:{dur},ease:"sine.inOut",stagger:0.04}},{a + t:.2f});',
               f'tl.set("#{i}v{k}",{{opacity:1}},{a + t:.2f});',
               f'tl.to("#{i}v{k}",{{motionPath:{{path:"#{i}r{k}",align:"#{i}r{k}",alignOrigin:[0.5,0.5],autoRotate:true}},duration:{dur},ease:"sine.inOut"}},{a + t:.2f});',
               f'tl.to("#{i}v{k}",{{scale:0,opacity:0,duration:0.25,ease:"sigIn"}},{a + t + dur:.2f});']
    for k, (_, _, _, tx, t, dur) in enumerate(chips):
        tw += [f'tl.fromTo("#{i}c{k}",{{opacity:0,y:16}},{{opacity:1,y:0,duration:{Q},ease:"sig"}},{a + t:.2f});',
               f'tl.from("#{i}ct{k}",{{scrambleText:{{text:{json.dumps(tx)},chars:"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",speed:0.6}},duration:0.8}},{a + t:.2f});',
               f'tl.to("#{i}c{k}",{{opacity:0,y:-10,duration:0.25,ease:"sigIn"}},{a + t + dur:.2f});']
    return Part(html, tw, pre=pre, hide=[i])
