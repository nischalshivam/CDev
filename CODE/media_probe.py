#!/usr/bin/env python3
"""
media_probe.py — cheap-first LOCAL measures (no API). Absorbed from the FOOTAGE-WORKFLOW's
measured lessons so we spend Gemini only on segments that already passed free checks.

Three measures, each with hard-won thresholds (measured on real corpora, not guessed):
  * probe + HD gate    — width>=1280 AND height>=720 AND width>height  (the width check is the
                         most-forgotten one; a 608x1080 vertical Short otherwise passes as "1080p").
  * histogram cuts     — ffmpeg scene-detect RETURNS 0 on cross-dissolves; colour-histogram
                         chi-square at 0.4s spacing (>=0.10 = shot change) actually works. Discards
                         the end-of-file artifact (the last frame always reads as a transition).
  * motion / frozen    — mean frame-diff (whole clip) AND still_run (longest frozen stretch). The
                         average alone lies: a clip can average fine while 3s inside it is frozen.

`segment_video()` combines them into shot segments with a `usable` verdict + reason — all free.
"""
from __future__ import annotations
import os
import glob
import subprocess
import tempfile
from pathlib import Path
import numpy as np
from PIL import Image

MIN_W, MIN_H = 1280, 720
CUT_STEP, CUT_JUMP, END_SLACK, BINS = 0.4, 0.10, 0.20, 32
MOTION_FPS, MOTION_W, MOTION_FLOOR, STILL_RUN = 4, 240, 1.0, 1.5


def probe(path) -> dict:
    """{width,height,dur,fps} from ffprobe. Empty dict on failure (NOT zeros — zeros would
    silently kill any file that failed to measure)."""
    try:
        import json
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height,r_frame_rate",
                            "-show_entries", "format=duration", "-of", "json", str(path)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=120)
        j = json.loads(r.stdout or "{}")
    except Exception:
        return {}
    st = (j.get("streams") or [{}])[0]
    try:
        w, h = int(st["width"]), int(st["height"])
    except (KeyError, TypeError, ValueError):
        return {}
    fps = 0.0
    rate = st.get("r_frame_rate") or ""
    if "/" in rate:
        a, b = rate.split("/", 1)
        try:
            fps = round(float(a) / float(b), 3) if float(b) else 0.0
        except ValueError:
            pass
    try:
        dur = round(float((j.get("format") or {}).get("duration") or 0), 3)
    except ValueError:
        dur = 0.0
    return {"width": w, "height": h, "dur": dur, "fps": fps}


def passes_hd(info: dict) -> tuple[bool, str]:
    if not info:
        return False, "could not measure"
    w, h = info.get("width", 0), info.get("height", 0)
    if w < MIN_W:
        return False, f"width {w} < {MIN_W}"
    if h < MIN_H:
        return False, f"height {h} < {MIN_H}"
    if w <= h:
        return False, f"portrait/square ({w}x{h})"
    return True, ""


def _hist(a: np.ndarray) -> np.ndarray:
    h = np.concatenate([np.histogram(a[:, :, k], bins=BINS, range=(0, 256))[0]
                        for k in range(3)]).astype(np.float64)
    return h / max(h.sum(), 1)


def find_cuts(path, jump: float = CUT_JUMP, step: float = CUT_STEP) -> list[float] | None:
    """Times where the shot changes (colour-histogram chi-square). [] = one shot;
    None = could not measure (missing file / no frames)."""
    if not Path(path).is_file():
        return None
    d = tempfile.mkdtemp()
    try:
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(path),
                        "-vf", f"fps=1/{step},scale=128:-2", f"{d}/f%04d.png"],
                       capture_output=True, timeout=600)
        hs = []
        for f in sorted(glob.glob(d + "/f*.png")):
            try:
                hs.append(_hist(np.asarray(Image.open(f).convert("RGB"))))
            except Exception:
                pass
            os.remove(f)
        if len(hs) < 3:
            return None
        dur = probe(path).get("dur", 0)
        out = []
        for i in range(len(hs) - 1):
            x, y = hs[i], hs[i + 1]
            chi = float(0.5 * np.sum((x - y) ** 2 / (x + y + 1e-9)))
            if chi < jump:
                continue
            t = step * (i + 1)
            if t < END_SLACK or (dur > 0 and t > dur - END_SLACK):   # skip end-of-file artifact
                continue
            out.append(round(t, 2))
        return out
    except subprocess.TimeoutExpired:
        return None
    finally:
        for x in glob.glob(d + "/*"):
            os.remove(x)
        try:
            os.rmdir(d)
        except OSError:
            pass


def measure_motion(path, start: float = 0, end: float = None) -> dict | None:
    """{mean, still_run} over [start,end] (whole file if end None). still_run is the longest
    frozen stretch in seconds — the field that catches frozen bits an average hides."""
    d = tempfile.mkdtemp()
    try:
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        if start:
            cmd += ["-ss", f"{start:.2f}"]
        cmd += ["-i", str(path)]
        if end is not None:
            cmd += ["-t", f"{max(0.1, end - start):.2f}"]
        cmd += ["-vf", f"fps={MOTION_FPS},scale={MOTION_W}:-2", f"{d}/f%05d.png"]
        subprocess.run(cmd, capture_output=True, timeout=600)
        arr = []
        for f in sorted(glob.glob(d + "/f*.png")):
            try:
                arr.append(np.asarray(Image.open(f).convert("L"), dtype=np.float32))
            except Exception:
                pass
            os.remove(f)
        if len(arr) < 3:
            return None
        diff = np.array([np.abs(arr[i + 1] - arr[i]).mean() for i in range(len(arr) - 1)])
        run = best = 0
        for is_still in (diff < MOTION_FLOOR):
            run = run + 1 if is_still else 0
            best = max(best, run)
        return {"mean": round(float(diff.mean()), 3), "still_run": round(best / MOTION_FPS, 2)}
    except subprocess.TimeoutExpired:
        return None
    finally:
        for x in glob.glob(d + "/*"):
            os.remove(x)
        try:
            os.rmdir(d)
        except OSError:
            pass


def motion_ok(m: dict | None) -> tuple[bool, str]:
    if not m:
        return False, "motion not measured"
    if m["mean"] < MOTION_FLOOR:
        return False, f"whole clip frozen (motion {m['mean']} < {MOTION_FLOOR})"
    if m["still_run"] >= STILL_RUN:
        return False, f"{m['still_run']}s frozen inside (limit {STILL_RUN}s)"
    return True, ""


def segment_video(path, max_seconds: float = 7.0) -> dict:
    """Cheap-first segmentation: HD gate -> histogram cuts -> per-shot motion. Returns
    {hd, hd_reason, info, segments:[{start,end,motion,still_run,usable,reason}]}. NO API spend."""
    info = probe(path)
    hd, hd_reason = passes_hd(info)
    cuts = find_cuts(path)
    dur = info.get("dur", 0.0)
    bounds = [0.0] + (cuts or []) + [dur]
    segs = []
    for a, b in zip(bounds, bounds[1:]):
        b = min(b, a + max_seconds)          # copyright cap
        if b - a < 1.5:
            continue
        m = measure_motion(path, a, b)
        ok, reason = motion_ok(m)
        segs.append({"start": round(a, 2), "end": round(b, 2),
                     "motion": (m or {}).get("mean"), "still_run": (m or {}).get("still_run"),
                     "usable": ok, "reason": reason})
    return {"hd": hd, "hd_reason": hd_reason, "info": info, "segments": segs}


if __name__ == "__main__":
    import sys
    for f in sys.argv[1:]:
        r = segment_video(f)
        print(f"{Path(f).name}: HD={r['hd']} {r['info']}")
        for s in r["segments"]:
            print(f"  {s['start']:6.1f}-{s['end']:6.1f}  motion={s['motion']}  "
                  f"still={s['still_run']}  {'usable' if s['usable'] else 'DROP: '+s['reason']}")
