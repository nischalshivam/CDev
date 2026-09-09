#!/usr/bin/env python3
"""build_core.py — the pieces every niche's builder MUST share.

This module exists because of a measured, repeating failure mode. Each niche got its own build
script, and each script re-implemented the same handful of tricky functions:

    _spinks/sample_audio.py   454 lines
    _quadrasteer/build.py     332 lines
    duplicated in both: gate_ok() objpath() autolevel() render() main()

So a fix landed in one niche and never reached the other. Concretely, and confirmed by grep:
branding_box (the foreign-watermark crop) was referenced 5 times in the boxing build and 0 times in
the cars build — which is exactly why another channel's "BatmaxKing" watermark shipped in the cars
sample after the boxing sample had been cleaned of the same thing weeks earlier. Same class of
defect, new niche, because the fix was written in a fork.

Anything here is written ONCE and inherited by every niche. A niche script should supply only what
is genuinely different — its style profile, its beat->query map, its audio design — and never
re-implement cropping, exposure, gating, or de-duplication.
"""
from __future__ import annotations
import json
import math
import os
import re
import subprocess
from pathlib import Path

import frame_quality as FQ

_crop, _dims, _brand, _lvl, _fc = {}, {}, {}, {}, {}
_gate_frames = {}
_gate_verdict = {}
_proxy = {}
_eproxy = {}


# --------------------------------------------------------------------------------------------
# STYLE PROFILES — the ONLY thing a niche should need to vary about its look.
# max_shot is MEASURED from each niche's reference channel, not chosen: a 4.0s hold suits a car
# explainer (competitor median 4.2s) and is visibly sluggish for a sports scandal (2.6s) or a
# defence piece (3.0s). Cut rate is part of a channel's voice.
# --------------------------------------------------------------------------------------------
STYLES = {
    "boxing": {
        "typography": "boxing",
        "grade": "contrast=1.10:saturation=0.66:brightness=0.005",
        "denoise": "hqdn3d=3:3:6:6",
        "sharpen": "unsharp=7:7:1.1:7:7:0.35",
        "target_y": 108.0, "gamma_damp": 0.85, "gamma_max": 2.40,
        "max_shot": 3.0,   # fight doc: fast
    },
    "clean": {          # explainer / cars: natural, modern, minimal
        "typography": "clean",
        "grade": "contrast=1.05:saturation=1.06:brightness=0.006",
        "denoise": "hqdn3d=1.5:1.5:4:4",
        "sharpen": "unsharp=5:5:0.5:5:5:0.0",
        "target_y": 112.0, "gamma_damp": 0.70, "gamma_max": 1.90,
        "max_shot": 4.2,   # measured: competitor cars median shot 4.2s
    },
    "sportsdoc": {      # 1970s-80s broadcast film: warm-ish, contrasty, a little desaturated
        "typography": "sportsdoc",
        "grade": "contrast=1.14:saturation=0.82:brightness=0.0",
        "denoise": "hqdn3d=2:2:5:5",
        "sharpen": "unsharp=5:5:0.8:5:5:0.0",
        "target_y": 104.0, "gamma_damp": 0.80, "gamma_max": 2.10,
        "max_shot": 2.6,   # measured: competitor sports median shot 2.6s
    },
    "defence": {        # military/procurement: cooler and slightly desaturated, never warm
        "typography": "defence",
        "grade": "contrast=1.08:saturation=0.90:brightness=0.004",
        "denoise": "hqdn3d=1.5:1.5:4:4",
        "sharpen": "unsharp=5:5:0.6:5:5:0.0",
        "target_y": 106.0, "gamma_damp": 0.70, "gamma_max": 1.85,
        "max_shot": 3.0,   # measured: competitor defence median shot 3.0s
    },
}


def style(name):
    return STYLES.get(name, STYLES["clean"])


# --------------------------------------------------------------------------------------------
# GEOMETRY — pillarbox removal AND another channel's branding, in one crop.
# --------------------------------------------------------------------------------------------
def src_dims(v):
    if v not in _dims:
        o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", str(v)],
                           capture_output=True, text=True).stdout.strip().split(",")
        _dims[v] = (int(o[0]), int(o[1])) if len(o) == 2 else (1280, 720)
    return _dims[v]


def detect_crop(v):
    """Pillarbox/letterbox removal. Returns (w, h, x, y) or None."""
    if v not in _crop:
        r = subprocess.run(["ffmpeg", "-ss", "60", "-t", "4", "-i", str(v), "-vf",
                            "cropdetect=24:2:0", "-f", "null", "-"], capture_output=True, text=True)
        m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
        _crop[v] = tuple(int(x) for x in m[-1]) if m else None
    return _crop[v]


def brand_trim(v, cache_path=None):
    """Fraction of the picture to cut off top/bottom to remove a rival channel's captions.

    Cached to disk per object because it is the most expensive measurement in a build (a full decode
    of the source) and can never change for given bytes. MUST be warmed before any render thread
    pool starts — six workers each decoding the same half-hour source once made a build do no
    visible work for over an hour."""
    key = os.path.basename(str(v))
    if key in _brand:
        return _brand[key]
    disk = {}
    if cache_path and Path(cache_path).exists():
        try:
            disk = json.load(open(cache_path, encoding="utf-8"))
        except Exception:
            disk = {}
    if key in disk:
        _brand[key] = disk[key]
        return disk[key]
    # keyframe-only: a spread of frames across the whole file without decoding all of it
    _brand[key] = FQ.branding_box(FQ.decode_keyframes(proxy(v), width=768))
    if cache_path:
        disk[key] = _brand[key]
        json.dump(disk, open(cache_path, "w", encoding="utf-8"), indent=1)
    return _brand[key]


def full_crop(v, cache_path=None):
    """Pillarbox removal AND foreign-branding removal as one crop, preserving aspect.

    Aspect is preserved on purpose: trimming only height made the picture far wider than 16:9, and a
    renderer that fits-and-centres turned that into a short strip with big black bands — six new
    near-black stretches, one of them 13 seconds. Cropping both axes zooms in instead."""
    c = detect_crop(v)
    sw, sh = src_dims(v)
    cw, ch, cx, cy = c if c else (sw, sh, 0, 0)
    b = brand_trim(v, cache_path)
    if ch >= sh - 2:                     # cropdetect took no height -> row indices still valid
        top, bot = int(ch * b.get("top", 0)), int(ch * b.get("bottom", 0))
        # A crop that eats a third of the height ALSO eats a third of the width (aspect is
        # preserved), leaving under half the picture to be blown back up to full frame — one shot
        # came out as an unreadable close-up of a wheel arch. Removing somebody's caption is not
        # worth destroying the shot; if the trim is that large, keep the frame and accept the
        # caption, which the source-level gate can still reject on its own.
        if (top + bot) > ch * 0.22:
            top = bot = 0
        if top or bot:
            nh = ch - top - bot
            nw = max(16, int(cw * nh / ch) // 2 * 2)
            cx, cw = cx + (cw - nw) // 2, nw
            cy, ch = cy + top, nh // 2 * 2
    return (cw, ch, cx, cy) if (cw, ch, cx, cy) != (sw, sh, 0, 0) else None


def crop_expr(v, cache_path=None):
    c = full_crop(v, cache_path)
    return f"crop={c[0]}:{c[1]}:{c[2]}:{c[3]}," if c else ""


# --------------------------------------------------------------------------------------------
# EXPOSURE
# --------------------------------------------------------------------------------------------
def autolevel(v, at, st, cache_path=None):
    """Per-shot exposure correction measured on the CROPPED picture.

    Solved, not guessed: ffmpeg's eq gamma is out = in**(1/g), so the g that lands a mean of y on
    target is ln(y/255)/ln(target/255). An earlier ratio-to-a-power approximation under-corrected
    the darkest shots and left 30 seconds of one cut below YAVG 40 — visibly black.

    Measured after cropping because these sources carry baked-in pillarbox; black bars drag an
    uncropped mean far below what the viewer sees, so the correction would be computed from bars."""
    key = (str(v), round(at, 1), st["target_y"])
    if key not in _lvl:
        vf = crop_expr(v, cache_path) + "scale=320:-2,signalstats,metadata=print:key=lavfi.signalstats.YAVG"
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{max(0.0, at):.2f}",
                            "-t", "1.5", "-i", str(v), "-vf", vf, "-f", "null", "-"],
                           capture_output=True, text=True)
        ys = [float(x) for x in re.findall(r"YAVG=([\d.]+)", r.stderr)]
        y = min(245.0, max(11.0, sum(ys) / len(ys) if ys else st["target_y"]))
        g_ideal = math.log(y / 255.0) / math.log(st["target_y"] / 255.0)
        _lvl[key] = round(max(0.80, min(st["gamma_max"], 1.0 + (g_ideal - 1.0) * st["gamma_damp"])), 3)
    return _lvl[key]


def grade(v, at, st, cache_path=None):
    g = autolevel(v, at, st, cache_path)
    return f"{st['denoise']},{st['sharpen']},eq=gamma={g}:{st['grade']}"


# --------------------------------------------------------------------------------------------
# GATING + RETRIEVAL
# --------------------------------------------------------------------------------------------
def gate_ok(v, a, b):
    """Frame-quality gate on JUST this segment. FAIL-CLOSED: any error means unusable.

    Decodes a window, not the source. The previous version decoded every source in full and cached
    it — 42s for a two-minute file — even though a build typically uses one or two segments from
    each source. Measured 28x faster per source with identical verdicts, and it was the single
    biggest reason a three-minute video took hours."""
    vk = (str(v), round(a, 2), round(b, 2))
    if vk in _gate_verdict:
        return _gate_verdict[vk]
    try:
        end = min(b, a + 4.0)
        fr = FQ.decode_window(proxy(v), a, max(0.6, end - a), fps=4.0, width=480)
        if len(fr) < 3:
            _gate_verdict[vk] = False
            return False
        _gate_frames[(str(v), round(a, 2))] = fr      # shot_hash reuses these, no second decode
        if len(_gate_frames) > 400:
            _gate_frames.clear()
        if v not in _fc:
            _fc[v] = FQ.source_edge_median(FQ.decode_keyframes(proxy(v), width=480))
        ok = FQ.assess_batch(fr, a, end, src_edge_median=_fc[v])["usable"]
        _gate_verdict[vk] = ok
        return ok
    except Exception:
        _gate_verdict[vk] = False
        return False


def objpath(cat, asset):
    sha = cat._asset_object_sha(asset)
    r = cat.cx.execute("SELECT rel_path FROM objects WHERE sha256=?", (sha,)).fetchone()
    root = os.environ["CDEV_LIBRARY_ROOT"]
    return os.path.join(root, r["rel_path"]).replace("\\", "/") if r else None


def _dhash(frame):
    import numpy as np
    from PIL import Image
    small = np.asarray(Image.fromarray(frame.astype("uint8")).resize((9, 8)))
    return (small[:, 1:] > small[:, :-1]).flatten()


def shot_hash(v, t):
    """Perceptual hash of the frame a shot will actually show — a one-second window, not a decode
    of the entire source."""
    for (kv, ka), cached in _gate_frames.items():   # the gate just decoded this exact window
        if kv == str(v) and abs(ka - (t - 0.5)) < 0.75 and cached:
            return _dhash(cached[len(cached) // 2][1])
    fr = FQ.decode_window(proxy(v), max(0.0, t - 0.2), 1.0, fps=2.0, width=320)
    if not fr:
        return None
    return _dhash(fr[len(fr) // 2][1])


def _too_similar(h, seen_hashes, max_dist=6):
    import numpy as np
    return any(int((h != g).sum()) <= max_dist for g in seen_hashes)


def pick(cat, query, used: set, *, deny=(), require=(), require_when=(), types=("video", "image"),
         top_k=120, seen_hashes=None, prefer=None, **search_kw):
    """First candidate that is unused, on-subject, and passes the quality gate.

    `used` is a GLOBAL set. It used to be a sliding window of the last N picks, which with a library
    smaller than the shot count let clips cycle back around; QC measured 64 repeated shots in a
    187-second cut and the viewer's first complaint was 'baar baar wahi clips'. A clip is spent the
    moment it is used, and when the pool runs dry the caller is expected to say so rather than
    quietly repeat.

    `deny`/`require` are the subject check bm25 cannot do: relevance by word overlap ranked a small
    SUV on a dirt road highly for 'pickup truck driving road' — every word matched except the one
    that mattered."""
    q = query.lower()
    # prefer lets the caller steer the stills ratio. The competitor cars video is 44% stills and
    # ours was 3%; stills are simultaneously the most precise option (the exact document being
    # narrated) and the cheapest to render, so the mix is a deliberate dial, not an accident.
    if prefer in types:
        types = (prefer,) + tuple(t for t in types if t != prefer)
    for typ in types:
        for x in cat.search(query_text=query, type=typ, top_k=top_k, **search_kw):
            if x["asset_id"] in used:
                continue
            d = (x.get("description") or "").lower()
            if any(w in d for w in deny):
                continue
            if require_when and any(t in q for t in require_when) and require:
                if not any(t in d for t in require):
                    continue
            f = objpath(cat, x)
            if not f:
                continue
            if typ == "image":
                return x, "image", f
            if not gate_ok(f, x["start_ms"] / 1000, x["end_ms"] / 1000):
                continue
            # PERCEPTUAL de-duplication, on top of the asset-id set. Two DIFFERENT assets can be
            # the same picture — neighbouring shots of one source often are — and a manifest-level
            # "62 unique assets" said nothing about it while the finished file still showed the
            # same frame twice, 107 seconds apart. What the viewer notices is the picture, so the
            # picture is what gets de-duplicated.
            if seen_hashes is not None:
                h = shot_hash(f, x["start_ms"] / 1000 + 0.5)
                if h is not None:
                    if _too_similar(h, seen_hashes):
                        continue
                    seen_hashes.append(h)
            return x, "video", f
    return None, None, None


def assert_alignment(beats, max_weak_frac=0.10):
    """Refuse to build on badly-aligned beats.

    align_beats already reported weak_alignment; nothing acted on it, so a script whose numerals the
    voice reads differently ("1990" -> "nineteen ninety") produced 110 of 121 beats misaligned and
    would have put every picture on the wrong sentence — invisible to every other check, because the
    file would still be sharp, bright, unrepeated and correctly mixed. A silent correctness failure
    is exactly the kind this pipeline must fail closed on."""
    scored = [b for b in beats if b.get("of")]
    if not scored:
        return
    weak = [b for b in scored if b["matched"] / b["of"] < 0.6]
    frac = len(weak) / len(scored)
    if frac > max_weak_frac:
        raise SystemExit(
            f"ALIGNMENT FAILED: {len(weak)}/{len(scored)} beats matched under 60% of their words "
            f"({frac*100:.0f}%, limit {max_weak_frac*100:.0f}%). The picture would land on the "
            f"wrong sentence. Re-run align_beats before building.")


def split_beats(beats, max_shot):
    """A beat is a unit of SPEECH, not of PICTURE. Gap-inclusive beats ran up to 9.4s, which broke
    three ways at once: the clip cap fetched only 7s so overlay's eof_action froze the last frame,
    a 9s hold reads as a slideshow, and one unlucky dark clip owned nine seconds of screen."""
    slots = []
    for b in beats:
        n = max(1, int(math.ceil(b["dur"] / max_shot)))
        per = b["dur"] / n
        for j in range(n):
            slots.append({**b, "dur": round(per, 2), "start": b["start"] + j * per,
                          "beat_i": b["i"], "sub": j})
    return slots


def warm(sources, cache_path=None):
    """Warm every whole-source measurement single-threaded BEFORE a render pool starts."""
    for v in sorted(set(sources)):
        full_crop(v, cache_path)


def warm_gates(candidates, workers: int = 6):
    """Gate many candidate windows CONCURRENTLY before the sequential pick loop runs.

    Gating is not CPU-bound in Python — it waits on an ffmpeg subprocess — so doing it one slot at a
    time left the machine idle. The pick loop must stay sequential (de-duplication is a running
    decision), but the expensive part can be computed ahead of it in parallel and looked up from the
    verdict cache. candidates: [(file, start_s, end_s), ...]"""
    from concurrent.futures import ThreadPoolExecutor
    todo = [c for c in dict.fromkeys(candidates)
            if (str(c[0]), round(c[1], 2), round(c[2], 2)) not in _gate_verdict]
    if not todo:
        return 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda c: gate_ok(c[0], c[1], c[2]), todo))
    return len(todo)


def collect_candidates(cat, queries, per_query: int = 8, types=("video",), **search_kw):
    """Every (file, start, end) the pick loop could plausibly ask about, for warm_gates."""
    out = []
    for q in queries:
        for typ in types:
            for x in cat.search(query_text=q, type=typ, top_k=per_query, **search_kw):
                f = objpath(cat, x)
                if f:
                    out.append((f, x["start_ms"] / 1000, x["end_ms"] / 1000))
    return out


def proxy(v, cache_dir=None):
    """A small, cheap-to-decode stand-in used for ALL measurement; the original is only ever used
    to render the finished picture.

    Profiling a three-minute build put 402 of 735 seconds in gating alone. The cause was not the
    algorithm — it was reading 500MB, high-bitrate 1080p files hundreds of times to look at a few
    low-resolution frames. Every measurement in this pipeline (quality gate, branding, exposure,
    perceptual hash) works on small greyscale frames, so none of them need the master.

    This is the standard proxy workflow from video editing, and it is a per-SOURCE one-off: once a
    proxy exists, every future build of every future video reuses it."""
    key = str(v)
    if key in _proxy:
        return _proxy[key]
    d = Path(cache_dir or (Path(v).parent.parent.parent / "proxy"))
    d.mkdir(parents=True, exist_ok=True)
    out = d / (Path(v).stem + "_px.mp4")
    if not out.exists():
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(v), "-an",
                            "-vf", "scale=480:-2", "-c:v", "libx264", "-preset", "ultrafast",
                            "-crf", "30", str(out)], capture_output=True, timeout=1800)
        if r.returncode or not out.exists():
            _proxy[key] = str(v)          # fall back to the master rather than fail the build
            return _proxy[key]
    _proxy[key] = str(out)
    return _proxy[key]


def build_proxies(sources, workers: int = 4, cache_dir=None):
    """Make every proxy up front, in parallel. Belongs in library building, not per video."""
    from concurrent.futures import ThreadPoolExecutor
    todo = [v for v in dict.fromkeys(sources) if str(v) not in _proxy]
    if not todo:
        return 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda v: proxy(v, cache_dir), todo))
    return len(todo)


def edit_proxy(v, cache_path=None, cache_dir=None, height: int = 720):
    """NOT USED — kept as a measured negative result.

    Rendering from a pre-cropped 720p intermediate is 6x cheaper PER SHOT in isolation, but
    building the intermediates cost 998s one-time and saved only 14s of a 154s render stage,
    because most sources are small enough to decode quickly and each is used for only one or two
    shots. Payback would take ~70 builds. Do not re-enable without re-measuring.

    Original note: the source the RENDER reads from: cropped, 720p, cheap to decode.

    Measured per shot on a 520MB 1080p master: 5.70s with the full grade chain, and 2.76s for a bare
    scale — i.e. simply decoding the master was the floor, and it dominated a 154-second render
    stage. Rendering the same shot from a small proxy took 0.98s.

    Since the finished video is 720p (all three competitor channels ship 720p), a 720p intermediate
    throws away nothing the viewer could see.

    The pillarbox and foreign-branding crop is BAKED IN here rather than applied per shot: it is a
    per-source constant, so doing it once at proxy time removes a filter from every single render
    and keeps crop coordinates out of the render path entirely, where a proxy of different
    dimensions would have made them wrong."""
    key = str(v)
    if key in _eproxy:
        return _eproxy[key]
    # Only worth it for BIG masters. A proxy costs a full transcode of the source, so for a small
    # file it is pure loss — the first version built one for every source and produced 1.5GB of
    # intermediates (one of them 159MB) on a disk that was already 93% full, for sources that
    # decode quickly anyway.
    try:
        if os.path.getsize(v) < 80_000_000:
            _eproxy[key] = str(v)
            return _eproxy[key]
    except OSError:
        pass
    d = Path(cache_dir or (Path(v).parent.parent.parent / "edit"))
    d.mkdir(parents=True, exist_ok=True)
    out = d / (Path(v).stem + "_ed.mp4")
    if not out.exists():
        ck = crop_expr(v, cache_path)
        vf = f"{ck}scale=-2:{height}"
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(v), "-an", "-vf", vf,
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "25", str(out)],
                           capture_output=True, timeout=3600)
        if r.returncode or not out.exists():
            _eproxy[key] = str(v)
            return _eproxy[key]
    _eproxy[key] = str(out)
    return _eproxy[key]


def build_edit_proxies(sources, workers: int = 4, cache_path=None, cache_dir=None):
    from concurrent.futures import ThreadPoolExecutor
    todo = [v for v in dict.fromkeys(sources) if str(v) not in _eproxy]
    if not todo:
        return 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda v: edit_proxy(v, cache_path, cache_dir), todo))
    return len(todo)


# --------------------------------------------------------------------------------------------
# KEN BURNS — subpixel, measured
# --------------------------------------------------------------------------------------------
_WHEEL = None


def motion_wheel(static_share=0.18, pan_share=0.03, size=12):
    """Spread static/pan/zoom evenly across a video instead of letting them clump.

    Shares are MEASURED from the reference channel, not chosen: 18% of its shots are completely
    static and a pan appears roughly once in 34 shots."""
    global _WHEEL
    if _WHEEL:
        return _WHEEL
    n_s = max(0, min(size, round(static_share * size)))
    n_p = max(0, min(size - n_s, round(pan_share * size)))
    w = [None] * size
    def place(count, what):
        for k in range(count):
            i = round((k + 0.5) * size / count) % size if count else 0
            while w[i]:
                i = (i + 1) % size
            w[i] = what
    place(n_s, "static")
    place(n_p, "pan")
    flip = 0
    for i in range(size):
        if not w[i]:
            w[i] = "out" if flip % 2 else "in"
            flip += 1
    _WHEEL = w
    return w


def ken_burns(W, H, fps, dur, index=0, zoom_per_sec=0.0099):
    """Ken Burns move as an ffmpeg filter string, using `perspective` instead of `zoompan`.

    zoompan truncates its crop origin to whole pixels, and in a zoom it truncates the crop HEIGHT
    too, so the requested sub-pixel motion arrives as uneven whole-pixel steps and the frame
    shivers. Measured on our own stills, per-frame displacement:

        zoompan       dx sd 0.352 px   dy sd 0.301 px    <- visible shake
        perspective   dx sd 0.001 px   dy sd 0.001 px

    `perspective` takes the source rectangle as FLOATS and resamples with cubic interpolation, so
    there is nothing to truncate. Two things break it if omitted: the canvas width must be a
    multiple of 16 (otherwise the 16:9 height lands off-integer and the aspect wobbles per frame),
    and the caller MUST pass `-framerate` on the image input or ffmpeg feeds 25fps into a 30fps
    output and duplicates every sixth frame.

    Returns (filter_string, n_frames). Speed is per SECOND, so a 2s and a 4s shot move alike."""
    n = max(2, int(round(dur * fps)))
    move = motion_wheel()[index % 12]
    if move == "static" or zoom_per_sec <= 0:
        return (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1", n)
    z = min(0.20, max(0.012, zoom_per_sec * dur))
    CW = max(16, round(W * (1 + z) / 16) * 16)
    CH = round(CW * H / W)
    N1 = max(1, n - 1)
    if move in ("in", "out"):
        ax, ay = (CW - W) / 2 / N1, (CH - H) / 2 / N1
        p = "on" if move == "in" else f"({N1}-on)"
        L, T = f"{ax:.4f}*{p}", f"{ay:.4f}*{p}"
        R, B = f"{CW}-{ax:.4f}*{p}", f"{CH}-{ay:.4f}*{p}"
    else:
        sx, ty = (CW - W) / N1, (CH - H) / 2
        p = f"({N1}-on)" if index % 2 else "on"
        L, T = f"{sx:.4f}*{p}", f"{ty:.4f}"
        R, B = f"{sx:.4f}*{p}+{W}", f"{ty + H:.4f}"
    persp = ("perspective=eval=frame:sense=source:interpolation=cubic:"
             f"x0='{L}':y0='{T}':x1='{R}':y1='{T}':x2='{L}':y2='{B}':x3='{R}':y3='{B}'")
    return (f"scale={CW}:{CH}:force_original_aspect_ratio=increase,crop={CW}:{CH},"
            f"{persp},scale={W}:{H}:flags=lanczos,setsar=1", n)
