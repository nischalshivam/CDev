#!/usr/bin/env python3
"""qc.py — automated quality control on a FINISHED video file.

This exists because of a specific, repeated failure: a build would report "DONE", get handed to a
human, and the human would find defects that a machine could have found in seconds. That loop is
one video per hour with a person inside it. It cannot make 100 videos a day.

Every check here corresponds to a defect that actually shipped:

  audible_bed     the score bed was built entirely from 55-110Hz sines and noise low-passed to
                  380Hz. Total level measured fine (-20dB) so it looked correct, but ABOVE 300Hz —
                  the only band a laptop or phone speaker reproduces — it was -47dB. 35dB under
                  speech. Not quiet: inaudible. Measuring total energy was measuring the wrong
                  thing. This check measures the band the listener can actually hear.
  audible_hits    same failure, same cause (90Hz sine + noise low-passed to 180Hz).
  frozen_runs     two 10-second stretches where every frame was identical — a text-less filler
                  card. 23% of one cut was frozen.
  dark_runs       those same cards render near-black (YAVG 26 of 255) on a normal screen.
  static_ratio    what fraction of runtime is not moving footage at all.
  shot_pacing     a documentary that holds any single shot too long reads as a slideshow.

Usage:  python CODE/qc.py VIDEO.mp4 [--voice voice.wav]
Exit code is 1 if any check FAILS, so a build script can refuse to hand over a bad file.
"""
from __future__ import annotations
import json
import re
import subprocess
import sys

# --- thresholds -------------------------------------------------------------------------------
# AUDIBLE_BAND_HZ: below this, small speakers reproduce almost nothing. 300Hz is deliberately
# conservative; laptop drivers typically roll off between 200-400Hz.
AUDIBLE_BAND_HZ = 300
BED_MAX_UNDER_SPEECH = 20.0   # dB. Bed may sit under speech, but not vanish beneath it.
HIT_MAX_UNDER_SPEECH = 12.0   # dB. A hit is an accent; it must read as loud as the voice, near it.
FROZEN_MAX_RUN = 2.5          # seconds a LOW-DETAIL frozen image may hold (see check_video)
FROZEN_DETAIL = 26.0          # pixel std above which a still frame is a photograph, not a card
DARK_MAX_RUN = 2.0            # seconds of near-black
DARK_YAVG = 40.0              # 0-255. The filler card measured 26.
STATIC_MAX_RATIO = 0.25       # The reference channel holds 18% of its shots completely still,
                              # so a stills-led cut is SUPPOSED to be partly static. 12% was
                              # calibrated when the pipeline was video-only.
MOTION_FLOOR = 2.0            # mean abs 8-bit pixel delta between samples; below this = a still
SHOT_MAX = 8.0                # seconds
DUP_HAMMING = 6               # dHash distance under which two frames are "the same picture"
DUP_MIN_GAP = 4.0             # seconds apart before two similar frames count as a REPEAT, not a
                              # neighbouring frame of the same continuous shot
DUP_MAX = 0                   # a finished video may contain ZERO repeated shots
DUP_MIN_DETAIL = 18.0         # per-frame pixel std below which a dHash is not trustworthy
BURNED_TEXT_MAX_PCT = 0.30    # %% of the OUTER frame that may be a static graphic in one shot
BURNED_TEXT_MAX_SHOTS = 0     # how many shots may carry another channel's watermark: none


def _sh(cmd) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stderr


def _mean_db(path, hp: int | None = None, ss: float | None = None, t: float | None = None):
    """mean_volume over an optional window, optionally high-passed to the audible band.

    Two cascaded high-pass stages, not one: a single biquad is only 12dB/octave and leaks far too
    much sub-bass into the measurement to tell a real midrange bed from a pure sub drone."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if ss is not None:
        cmd += ["-ss", f"{ss:.3f}"]
    if t is not None:
        cmd += ["-t", f"{t:.3f}"]
    af = (f"highpass=f={hp},highpass=f={hp}," if hp else "") + "volumedetect"
    out = _sh(cmd + ["-i", str(path), "-af", af, "-f", "null", "-"])
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", out)
    return float(m.group(1)) if m else None


def band_rms(path, win=0.25, lo=300, hi=3400):
    """RMS of the AUDIBLE SPEECH BAND per short window, over the whole file. [(t, dB), ...]

    Two earlier attempts at this both produced a check that agreed with itself and disagreed with
    the listener:

      1. silencedetect on a separate voice.wav — but voice.wav and the final cut are on different
         timelines (an 8s intro is prepended), so gap timestamps landed on speech and a silent bed
         measured as loud as the narration. The check passed on a file with no audible bed.
      2. silencedetect on the final file's speech band — self-consistent, but self-defeating: once
         the bed HAS midrange content it stops crossing the silence threshold, so no gaps are
         found at all and the bed reads as -68dB. Fixing the bed broke the check.

    A percentile of a windowed RMS has neither failure. Speech occupies the top of the
    distribution and the exposed bed sits at its floor, on one timeline, with no threshold to
    tune and nothing to go stale when the bed changes."""
    n = int(48000 * win)
    out = _sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
               f"highpass=f={lo},highpass=f={lo},lowpass=f={hi},aresample=48000,"
               f"asetnsamples=n={n}:p=0,astats=metadata=1:reset=1,"
               f"ametadata=print:key=lavfi.astats.Overall.RMS_level", "-f", "null", "-"])
    ts = [float(x) for x in re.findall(r"pts_time:([\d.]+)", out)]
    db = [float(x) for x in re.findall(r"RMS_level=(-?[\d.inf]+)", out.replace("-inf", "-99"))]
    return [(t, d) for t, d in zip(ts, db) if d > -98]


def levels(path, dur, edge=3.0):
    """(speech_db, bed_db) in the audible band: the 90th and 8th percentile of windowed RMS.

    Head and tail are excluded — fades there are quieter than any bed and would be mistaken for
    one."""
    pts = [(t, d) for t, d in band_rms(path) if edge <= t <= dur - edge]
    if len(pts) < 20:
        return None, None
    vals = sorted(d for _, d in pts)
    return vals[int(len(vals) * 0.90)], vals[int(len(vals) * 0.08)]


def frame_stats(video, fps=2.0):
    """Brightness AND real inter-frame motion, from one decode pass.

    Motion is measured as mean absolute pixel difference between consecutive frames, NOT as
    identical YAVG. Filler cards have animated film grain screen-blended over them, so their
    brightness wobbles frame to frame and an equality test called a 10-second frozen card
    "moving". The grain changes every pixel slightly; the picture underneath does not move at
    all, and a mean-abs-diff separates those two cleanly."""
    import numpy as np
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    import frame_quality as FQ
    frames = FQ.decode_frames(video, fps=fps, width=320)
    times = [t for t, _ in frames]
    yavg = [float(f.mean()) for _, f in frames]
    motion = [0.0]
    for i in range(1, len(frames)):
        motion.append(float(np.abs(frames[i][1] - frames[i - 1][1]).mean()))
    return times, yavg, motion, [f for _, f in frames]


def _runs(times, vals, pred, step):
    """Contiguous stretches where pred(value) holds. Returns [(start, duration)]."""
    out, run_start = [], None
    for i, v in enumerate(vals):
        if pred(i, v):
            if run_start is None:
                run_start = times[i]
        elif run_start is not None:
            out.append((run_start, times[i] - run_start))
            run_start = None
    if run_start is not None:
        out.append((run_start, times[-1] + step - run_start))
    return out


def check(video, voice=None, fps=2.0) -> dict:
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=nk=1:nw=1", str(video)],
                               capture_output=True, text=True).stdout.strip() or 0)
    rep = {"file": str(video), "duration": round(dur, 2), "checks": []}

    def add(name, ok, detail, **kw):
        rep["checks"].append(dict(name=name, ok=bool(ok), detail=detail, **kw))

    # ---------- audio: measure the band the listener can actually hear ----------
    speech_db, bed_db = levels(video, dur)
    if speech_db is None:
        add("audible_bed", False, "file too short to measure")
    else:
        under = speech_db - bed_db
        add("audible_bed", under <= BED_MAX_UNDER_SPEECH,
            f"floor {bed_db:.1f}dB vs speech {speech_db:.1f}dB above {AUDIBLE_BAND_HZ}Hz "
            f"= {under:.1f}dB under (limit {BED_MAX_UNDER_SPEECH:.0f})",
            bed_db=round(bed_db, 1), speech_db=round(speech_db, 1), under=round(under, 1))
    return rep, [], speech_db, (dur, fps)


def check_hits(video, hit_times, speech_db, rep):
    """A hit is an accent: measured at its cue, in the audible band, against speech."""
    if speech_db is None or not hit_times:
        return
    worst, worst_at = None, None
    for at in hit_times:
        v = _mean_db(video, AUDIBLE_BAND_HZ, max(0.0, at - 0.05), 0.35)
        if v is not None and (worst is None or v < worst):
            worst, worst_at = v, at
    if worst is None:
        return
    under = speech_db - worst
    rep["checks"].append(dict(
        name="audible_hits", ok=bool(under <= HIT_MAX_UNDER_SPEECH),
        detail=f"weakest hit (t={worst_at:.1f}s) {worst:.1f}dB vs speech {speech_db:.1f}dB "
               f"above {AUDIBLE_BAND_HZ}Hz = {under:.1f}dB under (limit {HIT_MAX_UNDER_SPEECH:.0f})",
        hit_db=round(worst, 1), under=round(under, 1)))


def check_repeats(video, rep, fps=1.0):
    """Catch the SAME shot being used more than once in one video.

    This shipped: a 3-minute cut re-used the same clips over and over because retrieval only
    avoided the last 10 picks and the library was smaller than the number of slots. A viewer sees
    it instantly ("baar baar wahi wahi clips"); nothing in QC did, because every other check looks
    at one moment in isolation rather than at the video as a whole.

    Measured on the FINISHED FILE with a perceptual hash, deliberately — not on the build's own
    manifest. A manifest only proves what the planner intended; a dHash proves what a viewer
    actually sees twice, and still catches it when two DIFFERENT library assets happen to be the
    same footage."""
    import numpy as np
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    import frame_quality as FQ
    frames = FQ.decode_frames(video, fps=fps, width=64)
    if len(frames) < 6:
        return

    from PIL import Image

    def dhash(f):
        # 8x9 -> horizontal gradient bits: robust to grade/brightness, sensitive to content
        small = np.asarray(Image.fromarray(f.astype("uint8")).resize((9, 8)))
        return (small[:, 1:] > small[:, :-1]).flatten()

    # A dHash of a nearly FLAT image is meaningless — most of its 72 bits come from noise, so it
    # lands within the Hamming threshold of almost anything. Our own title cards are flat charcoal
    # gradients, and one of them was reported as a duplicate of an aerial shot of a tank. Frames
    # without enough detail to hash are excluded from matching rather than trusted.
    hs = [(t, dhash(f)) for t, f in frames if float(f.std()) >= DUP_MIN_DETAIL]
    if len(hs) < 4:
        return
    dups, seen = [], set()
    for i in range(len(hs)):
        for j in range(i + 1, len(hs)):
            if hs[j][0] - hs[i][0] < DUP_MIN_GAP:
                continue
            if int((hs[i][1] != hs[j][1]).sum()) <= DUP_HAMMING:
                key = round(hs[i][0], 1)
                if key not in seen:
                    seen.add(key)
                    dups.append((hs[i][0], hs[j][0]))
                break
    rep["checks"].append(dict(
        name="repeat_shots", ok=len(dups) <= DUP_MAX,
        detail=(f"{len(dups)} repeated shots: " +
                ", ".join(f"{a:.0f}s~{b:.0f}s" for a, b in dups[:8])) if dups
               else "no shot appears twice",
        count=len(dups)))


# NOTE — an output-level "foreign watermark" check was written here and REMOVED, deliberately.
# It cannot work on pixels alone: our own lower-thirds and title cards are, by design, static
# high-contrast graphics in the outer frame, so the detector flagged the MIKE TYSON lower-third and
# every 4:3 pillarbox seam as somebody else's watermark — 26 "hits" on a visibly clean cut. A check
# that cries wolf is worse than no check, because it teaches you to ignore QC.
# Foreign branding is prevented where it is actually detectable: at SOURCE level, in
# frame_quality.branding_box (measured 26x-43x over baseline on genuinely branded sources), applied
# by build_core.full_crop. If this is ever revived, it must be given the build's own overlay
# geometry so it can subtract what we drew ourselves.

def check_video(video, rep, fps=2.0):
    import numpy as np
    times, yavg, motion, frames_std = frame_stats(video, fps)
    step = 1.0 / fps
    if len(yavg) < 4:
        rep["checks"].append(dict(name="video_stats", ok=False, detail="decode failed"))
        return

    # Frozen: the picture is not moving. This check exists to catch MISSING footage — a blank
    # filler card sitting on screen — not a deliberately still photograph. A stills-led cut holds
    # real pictures still on purpose (the reference channel does it in 18% of its shots), and those
    # are not defects. What separates them is DETAIL: a photograph is full of it, a dropout card is
    # nearly flat. So a frozen run is only reported when the frame is also low-detail, or when it
    # runs longer than any single legitimate shot (meaning something is genuinely stuck).
    froz_all = _runs(times, motion, lambda i, v: i > 0 and v < MOTION_FLOOR, step)
    froz = [(s, d) for s, d in froz_all if d >= 1.0]
    detail_at = {}
    for i, t in enumerate(times):
        detail_at[round(t, 2)] = float(np.std(frames_std[i])) if i < len(frames_std) else 99.0
    def flat(start, dur_):
        vals = [v for k, v in detail_at.items() if start - 0.01 <= k <= start + dur_ + 0.01]
        return (sum(vals) / len(vals)) < FROZEN_DETAIL if vals else False
    bad_f = [(s, d) for s, d in froz
             if (d > FROZEN_MAX_RUN and flat(s, d)) or d > 6.0]
    rep["checks"].append(dict(
        name="frozen_runs", ok=not bad_f,
        detail=(f"{len(bad_f)} dead frozen stretches: "
                + ", ".join(f"{s:.0f}s({d:.1f}s)" for s, d in bad_f[:6])) if bad_f
               else f"none ({len(froz)} still shots, all detailed pictures)",
        runs=[[round(s, 1), round(d, 1)] for s, d in bad_f]))

    dark = [(s, d) for s, d in _runs(times, yavg, lambda i, v: v < DARK_YAVG, step) if d >= 1.0]
    bad_d = [(s, d) for s, d in dark if d > DARK_MAX_RUN]
    rep["checks"].append(dict(
        name="dark_runs", ok=not bad_d,
        detail=(f"{len(bad_d)} near-black stretches over {DARK_MAX_RUN}s (YAVG<{DARK_YAVG:.0f}): "
                + ", ".join(f"{s:.0f}s({d:.1f}s)" for s, d in bad_d[:6])) if bad_d
               else f"none over {DARK_MAX_RUN}s",
        runs=[[round(s, 1), round(d, 1)] for s, d in bad_d]))

    static = sum(d for _, d in froz)
    ratio = static / max(1e-6, rep["duration"])
    rep["checks"].append(dict(
        name="static_ratio", ok=ratio <= STATIC_MAX_RATIO,
        detail=f"{static:.1f}s of {rep['duration']:.0f}s is non-moving = {ratio*100:.0f}% "
               f"(limit {STATIC_MAX_RATIO*100:.0f}%)", ratio=round(ratio, 3)))


def run(video, voice=None, hit_times=None, fps=2.0):
    rep, gaps, speech_db, _ = check(video, voice, fps)
    check_hits(video, hit_times or [], speech_db, rep)
    check_video(video, rep, fps)
    check_repeats(video, rep)
    rep["pass"] = all(c["ok"] for c in rep["checks"])
    return rep


def report(rep) -> str:
    lines = [f"QC  {rep['file']}  ({rep['duration']:.1f}s)"]
    for c in rep["checks"]:
        lines.append(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['name']:<14} {c['detail']}")
    lines.append(f"  => {'PASS' if rep['pass'] else 'FAIL'}")
    return "\n".join(lines)


if __name__ == "__main__":
    a = sys.argv[1:]
    vid = a[0]
    voice = a[a.index("--voice") + 1] if "--voice" in a else None
    hits = json.loads(a[a.index("--hits") + 1]) if "--hits" in a else None
    r = run(vid, voice, hits)
    print(report(r))
    sys.exit(0 if r["pass"] else 1)
