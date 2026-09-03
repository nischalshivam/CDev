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
def decode_frames(video, fps: float = 2.0, width: int = 480, out_dir=None) -> list:
    """Decode a whole source ONCE into an array of greyscale frames + their timestamps.

    The per-segment path costs ~10 ffmpeg seeks per candidate; on a few hundred segments that is
    thousands of process launches and the gate becomes the slowest step in the pipeline. Decoding
    once at a low fps and measuring in memory is ~50x faster for the same numbers.

    Returns [(t_seconds, frame_array), ...]."""
    d = out_dir or tempfile.mkdtemp()
    os.makedirs(d, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
                    "-vf", f"fps={fps},scale={width}:-2", f"{d}/f%06d.png"],
                   capture_output=True, timeout=3600)
    out = []
    for i, f in enumerate(sorted(glob.glob(d + "/f*.png"))):
        try:
            out.append((i / fps, np.asarray(Image.open(f).convert("L"), dtype=np.float32)))
        except Exception:
            pass
        os.remove(f)
    try:
        os.rmdir(d)
    except OSError:
        pass
    return out


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
    ov_pct = 0.0
    if len(win) >= 4:
        st = np.stack(win)
        tvar = st.var(axis=0)
        edges = np.abs(_laplacian(st.mean(axis=0)))
        mask = (tvar < 12.0) & (edges > 14.0)
        ov_pct = float(mask.mean() * 100)
        if ov_pct > overlay_max:
            reasons.append(f"burned-in graphics {ov_pct:.1f}%")
    return {"usable": not reasons, "reasons": reasons, "sharpness": round(sh, 1),
            "overlay_pct": round(ov_pct, 2)}


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
