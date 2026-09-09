#!/usr/bin/env python3
"""
frame_quality.py — measure what a frame actually LOOKS like. Free, local, no API.

Why this exists: a vision model describes CONTENT, not QUALITY. A motion-smeared, half-dissolved
extreme close-up of nothing is still honestly described as "Mike Tyson punching" — the description
is right and the picture is garbage. A cut built on descriptions alone therefore fills up with
blur, ghosting and burned-in broadcast graphics. Every gate here is a measurement.

Four measures:
  sharpness(frame)          Laplacian variance — catches blur and motion smear
  ghosting(frames)          dissolve/cross-fade detection (a blended frame has soft doubled edges)
  static_overlay(video,a,b) burned-in logos/caption bars: broadcast graphics hold STILL while the
                            picture moves, so per-pixel temporal variance near zero + strong edges
                            = an overlay. Returns coverage + which zones are dirty.
  assess(video,a,b)         all of it -> {usable, reasons, sharpness, overlay_pct, zones}
"""
from __future__ import annotations
import os
import glob
import subprocess
import tempfile
import numpy as np
from PIL import Image

# CALIBRATED, not guessed. Measured over 34 shots of real archival boxing footage:
#   sharpness p5=51  p10=65  p25=107  p50=404  p75=1257  p90=1496   (min 6, max 2276)
# The first pass used SHARP_MIN=55, which sat below p10 — so blur was never rejected and the cut
# filled with smeared frames. p25-ish is the honest floor.
SHARP_MIN = 150.0         # ~p30: below this a frame reads as blurred / motion-smeared
SOURCE_SHARP_MIN = 250.0  # a source whose MEDIAN is under this is soft throughout — 6 of the 8
                          # worst shots in the first cut came from one source with median 84
GHOST_MAX = 0.55          # edge energy vs the source's own median: a dissolve frame sits well under
OVERLAY_MAX_PCT = 1.2     # % of frame allowed to be static graphic before we reject
SAMPLES = 7               # frames sampled across a segment for temporal analysis


def _grab(video, t, width=480) -> np.ndarray | None:
    fp = tempfile.mktemp(suffix=".png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video),
                    "-frames:v", "1", "-vf", f"scale={width}:-2", fp], capture_output=True)
    if not os.path.exists(fp):
        return None
    a = np.asarray(Image.open(fp).convert("L"), dtype=np.float32)
    os.remove(fp)
    return a


def _laplacian(a: np.ndarray) -> np.ndarray:
    k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    p = np.pad(a, 1, mode="edge")
    out = np.zeros_like(a)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            w = k[dy + 1, dx + 1]
            if w:
                out += w * p[1 + dy:1 + dy + a.shape[0], 1 + dx:1 + dx + a.shape[1]]
    return out


def sharpness(a: np.ndarray) -> float:
    """Laplacian variance. High = crisp edges. Low = blurred, smeared or out of focus."""
    return float(_laplacian(a).var())


def ghosting(frames: list[np.ndarray]) -> float:
    """Ratio of a frame's edge energy to its neighbours'. A cross-dissolve frame is a weighted
    blend of two pictures, so its edges are weaker than both sources -> ratio dips."""
    if len(frames) < 3:
        return 1.0
    e = [float(np.abs(_laplacian(f)).mean()) for f in frames]
    mid = len(e) // 2
    neigh = (e[mid - 1] + e[mid + 1]) / 2.0
    return float(e[mid] / neigh) if neigh > 0 else 1.0


def static_overlay(video, start: float, end: float, samples: int = SAMPLES) -> dict:
    """Find burned-in graphics. Broadcast logos/caption bars are pinned to the frame while the
    footage moves underneath, so they show ~zero temporal variance AND strong spatial edges.

    Returns {pct, zones} where zones names the regions that are dirty."""
    ts = [start + (end - start) * (i + 0.5) / samples for i in range(samples)]
    fr = [f for f in (_grab(video, t) for t in ts) if f is not None]
    if len(fr) < 4:
        return {"pct": 0.0, "zones": [], "measured": False}
    stack = np.stack(fr)                       # (n, h, w)
    tvar = stack.var(axis=0)                   # temporal variance per pixel
    edges = np.abs(_laplacian(stack.mean(axis=0)))
    # static AND edgy = a graphic pinned on top of moving footage
    mask = (tvar < 12.0) & (edges > 14.0)
    h, w = mask.shape
    pct = float(mask.mean() * 100)
    zones = []
    for name, sl in {
        "top-left":     (slice(0, h // 4), slice(0, w // 3)),
        "top-right":    (slice(0, h // 4), slice(2 * w // 3, w)),
        "bottom-left":  (slice(3 * h // 4, h), slice(0, w // 2)),
        "bottom-right": (slice(3 * h // 4, h), slice(w // 2, w)),
        "lower-band":   (slice(2 * h // 3, h), slice(0, w)),
    }.items():
        if mask[sl].mean() * 100 > 2.5:
            zones.append(name)
    return {"pct": round(pct, 2), "zones": zones, "measured": True}


def assess(video, start: float, end: float,
           sharp_min: float = SHARP_MIN, overlay_max: float = OVERLAY_MAX_PCT) -> dict:
    """Full verdict for one candidate segment. All local, no API."""
    mid = (start + end) / 2
    step = max(0.12, (end - start) / 8)
    fr = [f for f in (_grab(video, mid + d * step) for d in (-1, 0, 1)) if f is not None]
    if not fr:
        return {"usable": False, "reasons": ["could not sample frames"]}
    centre = fr[len(fr) // 2]
    sh = sharpness(centre)
    gh = ghosting(fr) if len(fr) >= 3 else 1.0
    ov = static_overlay(video, start, end)

    reasons = []
    if sh < sharp_min:
        reasons.append(f"blurred/smeared (sharpness {sh:.0f} < {sharp_min:.0f})")
    if gh < GHOST_MAX:
        reasons.append(f"dissolve/ghosted frame (edge ratio {gh:.2f})")
    if ov["measured"] and ov["pct"] > overlay_max:
        reasons.append(f"burned-in graphics {ov['pct']:.1f}% ({', '.join(ov['zones']) or 'spread'})")
    return {"usable": not reasons, "reasons": reasons,
            "sharpness": round(sh, 1), "ghost_ratio": round(gh, 2),
            "overlay_pct": ov["pct"], "overlay_zones": ov["zones"]}


def source_quality(video, samples: int = 16) -> dict:
    """Judge a WHOLE SOURCE before cataloging it. Quality is mostly a source property, not a
    per-shot lottery: in the first cut, 6 of the 8 worst shots came from one source whose median
    sharpness was 84 against a corpus median of 404. Rejecting that source up front is worth more
    than filtering its shots one by one — and it saves the vision spend too.

    Also finds graphics that persist across the WHOLE source (a highlight reel's logo/caption bar
    sits in the same place for its entire runtime) and suggests a crop that removes them."""
    dur = 0.0
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nk=1:nw=1", str(video)], capture_output=True, text=True)
    try:
        dur = float(r.stdout.strip())
    except ValueError:
        return {"ok": False, "reasons": ["could not probe"], "measured": False}
    if dur <= 0:
        return {"ok": False, "reasons": ["zero duration"], "measured": False}

    ts = [dur * (i + 0.5) / samples for i in range(samples)]
    fr = [f for f in (_grab(video, t) for t in ts) if f is not None]
    if len(fr) < 6:
        return {"ok": False, "reasons": ["too few frames sampled"], "measured": False}

    sh = sorted(sharpness(f) for f in fr)
    med = float(np.median(sh))
    stack = np.stack(fr)
    tvar = stack.var(axis=0)
    edges = np.abs(_laplacian(stack.mean(axis=0)))
    mask = (tvar < 12.0) & (edges > 14.0)          # pinned across the ENTIRE source = branding
    h, w = mask.shape
    pct = float(mask.mean() * 100)

    # how much of the bottom band would a crop have to remove?
    band = mask[int(h * 0.72):, :]
    crop_bottom = 0.28 if band.mean() * 100 > 2.0 else 0.0

    reasons = []
    if med < SOURCE_SHARP_MIN:
        reasons.append(f"soft source (median sharpness {med:.0f} < {SOURCE_SHARP_MIN:.0f})")
    if pct > OVERLAY_MAX_PCT:
        reasons.append(f"persistent burned-in graphics on {pct:.1f}% of frame")
    return {"ok": not reasons, "reasons": reasons, "median_sharpness": round(med, 1),
            "overlay_pct": round(pct, 2), "suggest_crop_bottom": crop_bottom,
            "duration": round(dur, 1), "measured": True}


# ---------------------------------------------------------------- fast batch path
_FRAME_CACHE = {}
_DIMS = {}


def _dims(video):
    """Cached source dimensions. Every decode call used to spawn its own ffprobe; at two
    process launches per gate check across hundreds of candidates that is pure overhead."""
    k = str(video)
    if k not in _DIMS:
        o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "csv=p=0", k],
                           capture_output=True, text=True).stdout.strip().split(",")
        try:
            _DIMS[k] = (int(o[0]), int(o[1]))
        except Exception:
            _DIMS[k] = (1280, 720)
    return _DIMS[k]


def decode_frames(video, fps: float = 2.0, width: int = 480, out_dir=None) -> list:
    """Decode a whole source ONCE into greyscale frames + timestamps, via a RAW PIPE.

    This used to write one PNG per frame to a temp directory and read them back with PIL. Measured
    on a 117-second source that cost 113 seconds — essentially real-time — because every frame paid
    a PNG encode, a disk write, a disk read and a PNG decode. Across a 66-source library that was
    ~109 minutes of pure decoding before a single shot could be rendered, and it was the single
    largest reason a three-minute video took hours to build.

    Piping raw 8-bit grey straight out of ffmpeg removes all four costs: no image codec, no
    filesystem, one process. Same numbers out, a fraction of the time.

    Results are memoised per (video, fps, width) because the gate, the branding detector and the
    exposure measurement all want the same frames and used to decode the file separately."""
    key = (str(video), round(float(fps), 4), int(width))
    if key in _FRAME_CACHE:
        return _FRAME_CACHE[key]

    sw, sh = _dims(video)
    w = int(width) // 2 * 2
    h = max(2, int(round(w * sh / max(1, sw))) // 2 * 2)

    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video),
                        "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo",
                        "-pix_fmt", "gray", "-"],
                       capture_output=True, timeout=3600)
    buf, fsz = p.stdout, w * h
    n = len(buf) // fsz if fsz else 0
    arr = np.frombuffer(buf[:n * fsz], dtype=np.uint8).reshape(n, h, w).astype(np.float32)
    out = [(i / fps, arr[i]) for i in range(n)]
    if len(_FRAME_CACHE) > 24:                 # bound memory on long multi-source builds
        _FRAME_CACHE.clear()
    _FRAME_CACHE[key] = out
    return out


def decode_window(video, start: float, dur: float, fps: float = 4.0, width: int = 480) -> list:
    """Decode ONLY the seconds a candidate segment needs, using a fast pre-input seek.

    This replaces decoding the whole source for every gate check. Measured: a 117-second source cost
    ~42s to decode in full, and a build touches ~30 sources — so the gate alone was tens of minutes
    before a single frame was rendered. But a shot is at most a few seconds long and a build uses
    only one or two segments from most sources, so nearly all of that decoding was thrown away.

    `-ss` placed BEFORE `-i` seeks by keyframe without decoding the skipped part, so the cost
    becomes proportional to the SHOT, not to the source."""
    sw, sh = _dims(video)
    w = int(width) // 2 * 2
    h = max(2, int(round(w * sh / max(1, sw))) // 2 * 2)
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, start):.2f}",
                        "-t", f"{max(0.4, dur):.2f}", "-i", str(video),
                        "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo",
                        "-pix_fmt", "gray", "-"], capture_output=True, timeout=300)
    fsz = w * h
    n = len(p.stdout) // fsz if fsz else 0
    if n == 0:
        return []
    arr = np.frombuffer(p.stdout[:n * fsz], dtype=np.uint8).reshape(n, h, w).astype(np.float32)
    return [(start + i / fps, arr[i]) for i in range(n)]


def decode_keyframes(video, width: int = 768, max_frames: int = 60) -> list:
    """Keyframe-only decode: a cheap sample spread across a WHOLE source.

    Used by the branding detector, which needs frames from everywhere in the file but only about
    thirty of them. Asking for fps=0.25 still made ffmpeg decode every frame and throw most away
    (~45s on a two-minute source); -skip_frame nokey decodes just the I-frames."""
    sw, sh = _dims(video)
    w = int(width) // 2 * 2
    h = max(2, int(round(w * sh / max(1, sw))) // 2 * 2)
    p = subprocess.run(["ffmpeg", "-v", "error", "-skip_frame", "nokey", "-i", str(video),
                        "-vsync", "0", "-vf", f"scale={w}:{h}", "-f", "rawvideo",
                        "-pix_fmt", "gray", "-"], capture_output=True, timeout=900)
    fsz = w * h
    n = min(len(p.stdout) // fsz if fsz else 0, max_frames)
    if n == 0:
        return []
    arr = np.frombuffer(p.stdout[:n * fsz], dtype=np.uint8).reshape(n, h, w).astype(np.float32)
    return [(float(i), arr[i]) for i in range(n)]


def assess_batch(frames: list, start: float, end: float,
                 sharp_min: float = SHARP_MIN, overlay_max: float = OVERLAY_MAX_PCT,
                 src_edge_median: float = None) -> dict:
    """Same verdict as assess(), but reading from pre-decoded frames. No ffmpeg calls."""
    win = [f for t, f in frames if start <= t <= end]
    if len(win) < 2:
        win = [f for t, f in frames if start - 0.6 <= t <= end + 0.6]
    if not win:
        return {"usable": False, "reasons": ["no frames in window"]}
    centre = win[len(win) // 2]
    sh = sharpness(centre)
    reasons = []
    if sh < sharp_min:
        reasons.append(f"blurred/smeared (sharpness {sh:.0f} < {sharp_min:.0f})")
    # ghosting relative to the SOURCE's own edge energy, not just neighbours: inside a dissolve
    # every nearby frame is equally soft, so a local ratio always looks fine.
    if src_edge_median:
        e = float(np.abs(_laplacian(centre)).mean())
        ratio = e / src_edge_median if src_edge_median else 1.0
        if ratio < GHOST_MAX:
            reasons.append(f"dissolve/soft frame (edge ratio {ratio:.2f} of source median)")
    # SLIDING WINDOW, not whole-window. A broadcast caption that is on screen for only part of a
    # shot has HIGH variance over the full window, so a whole-window test scores it clean — that is
    # exactly how a "CLASSIC SPORTS" caption bar passed at 0.42% while plainly visible on screen.
    # Graphics are static within their own dwell time, so take the WORST sub-window.
    ov_pct = 0.0
    if len(win) >= 4:
        sub = max(3, min(4, len(win)))
        for a in range(0, len(win) - sub + 1):
            st = np.stack(win[a:a + sub])
            tvar = st.var(axis=0)
            edges = np.abs(_laplacian(st.mean(axis=0)))
            mask = (tvar < 12.0) & (edges > 14.0)
            ov_pct = max(ov_pct, float(mask.mean() * 100))
        if ov_pct > overlay_max:
            reasons.append(f"burned-in graphics {ov_pct:.1f}% (worst sub-window)")
    return {"usable": not reasons, "reasons": reasons, "sharpness": round(sh, 1),
            "overlay_pct": round(ov_pct, 2)}


def branding_box(frames: list, ratio: float = 4.0, edge_zone: float = 0.35,
                 max_trim: float = 0.34) -> dict:
    """Locate another channel's burned-in captions and return the fraction to trim off each edge.

    Why this is needed even though a per-shot overlay detector already exists: that detector fires
    above ~1.2% frame coverage, and a compilation channel's lower-third ("Mike Tyson Knockouts —
    September 5, 1985") plus its corner ranking badge cover about 1% together. Under the threshold,
    so all of them passed, and a cut went out with a rival channel's furniture on ten shots.

    The first attempt at THIS function also failed, and the reason is worth keeping: it looked for
    pixels that never change across the source, on the assumption branding is permanent. But a
    countdown compilation re-writes its caption for every entry — different name, different date,
    different rank — so the text is not static at all and the measured coverage came back 0.0-0.4%
    on sources visibly covered in captions.

    What IS invariant is not the pixels but the LAYOUT: rendered text is a dense band of hard
    horizontal gradients, and a channel always puts it in the same rows. Profiling how often each
    ROW carries text-like gradient, over the whole source, made the band unmistakable — 12.9x and
    44.9x the frame's own baseline on the two offending sources, against no band at all on the
    four clean ones. Measuring the layout rather than the content is what separated them.

    Only the outer `edge_zone` of the frame is considered: captions live at the edges, while a
    band across the middle is usually real content (ring ropes, a crowd barrier).

    Returns {'top','bottom','left','right'} as fractions to cut, plus the band strength."""
    if len(frames) < 10:
        return {"top": 0.0, "bottom": 0.0, "left": 0.0, "right": 0.0, "strength": 0.0}
    sel = frames[::max(1, len(frames) // 80)][:80]
    st = np.stack([f for _, f in sel])
    h, w = st.shape[1], st.shape[2]

    def bands(axis_profile, n):
        """(start, end, strength) for stretches whose text-likeness far exceeds the frame's own
        baseline. Normalising against the source's own baseline is what lets one threshold work
        across a clean broadcast master and a noisy upload alike."""
        base = max(float(np.median(axis_profile)), 1e-6)
        hot = [i for i, v in enumerate(axis_profile) if v > base * ratio]
        out, cur = [], None
        for i in hot:
            if cur and i - cur[1] <= 3:
                cur[1] = i
            else:
                if cur and cur[1] - cur[0] >= 2:
                    out.append(cur)
                cur = [i, i]
        if cur and cur[1] - cur[0] >= 2:
            out.append(cur)
        return [(a, b, float(max(axis_profile[a:b + 1]) / base)) for a, b in out]

    # hard horizontal gradient = the signature of rendered type against any background
    flag = (np.abs(np.diff(st, axis=2)) > 26).mean(axis=0)
    res = {"top": 0.0, "bottom": 0.0, "left": 0.0, "right": 0.0, "strength": 0.0}
    # ROWS ONLY. Broadcast and channel furniture is laid out in horizontal bands; a vertical scan
    # instead flagged ring ropes and the ring's own posts as "branding" on two clean sources and
    # would have thrown away 9% of the picture on each side for nothing.
    for key_lo, key_hi, prof, n in (("top", "bottom", flag.mean(axis=1), h),):
        for a, b, s in bands(prof, n):
            if b < n * edge_zone:                       # band hugs the leading edge
                res[key_lo] = max(res[key_lo], min(max_trim, (b + 3) / n))
                res["strength"] = max(res["strength"], s)
            elif a > n * (1 - edge_zone):               # band hugs the trailing edge
                res[key_hi] = max(res[key_hi], min(max_trim, (n - a + 3) / n))
                res["strength"] = max(res["strength"], s)
    res["strength"] = round(res["strength"], 1)
    return res


def source_edge_median(frames: list) -> float:
    if not frames:
        return 0.0
    vals = [float(np.abs(_laplacian(f)).mean()) for _, f in frames[::max(1, len(frames)//40)]]
    return float(np.median(vals)) if vals else 0.0


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) == 2:
        print(json.dumps(source_quality(sys.argv[1]), indent=1))
    else:
        v = sys.argv[1]; a = float(sys.argv[2]); b = float(sys.argv[3])
        print(json.dumps(assess(v, a, b), indent=1))
