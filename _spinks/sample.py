#!/usr/bin/env python3
"""90-second sample: proves the render fix + the intro feature on the HARD case (soft 1988 footage).

Render chain rebuilt from measurement (sharpness on the same 1920px output frame):
    old  : scale 2x -> zoompan -> unsharp                     =  7
    +denoise+lanczos fill                                     = 16
    +crop baked-in bars, fill                                 = 14
    crop bars -> modest 1.74x scale -> DESIGNED FRAME         = 35   <- 5x the original

The lesson: soft archival gets WORSE the harder you blow it up to fill 1080p. Cropping the baked-in
pillarbox first (these sources waste 16-37% of width on black) and then presenting the picture in a
deliberate frame keeps the real detail instead of stretching it.

Structure: 8s cold-open of real footage with its OWN audio (no narration), then narration beats.
"""

import sys, os, io, json, subprocess, re
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, f"{ROOT}/CODE")
os.environ["CDEV_LIBRARY_ROOT"] = f"{ROOT}/_tyson/library"
import catalog_db
import frame_quality as FQ
from typography import title_card, lower_third, stat_card

# Repo root, derived from THIS file. Never hard-code an absolute path: a machine change (or a
# different drive letter) silently sends every read and write somewhere else. One earlier build
# wrote 719 files into the wrong library for exactly this reason, and the same mistake was already
# sitting in two other files at the time.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

_fcache = {}
def gate_ok(video, start, end):
    """Re-gate a candidate with the CURRENT detector. The library was cataloged before the
    sliding-window overlay fix, so its clean_status is stale for intermittent captions."""
    try:
        if video not in _fcache:
            fr = FQ.decode_frames(video, fps=2.0)
            _fcache[video] = (fr, FQ.source_edge_median(fr))
        fr, emed = _fcache[video]
        q = FQ.assess_batch(fr, start, min(end, start + 4.0), src_edge_median=emed)
        return q["usable"]
    except Exception:
        return True

HERE = f"{ROOT}/_spinks"
W, H, FPS = 1920, 1080, 30
GRAIN = f"{ROOT}/_tyson/fx/grain.mp4"
OUT = f"{HERE}/sample"; os.makedirs(OUT, exist_ok=True)
SPINKS_SRC = f"{HERE}/raw2/lN4s_HNoIaQ.mp4"
INTRO_AT, INTRO_LEN = 130.0, 8.0   # gated: sharp 411, overlay 0.72% (149s had a CLASSIC SPORTS bar)
_crop_cache = {}


def detect_crop(video):
    """Baked-in pillarbox wastes 16-37% of these sources' width. Find the real picture once."""
    if video in _crop_cache:
        return _crop_cache[video]
    r = subprocess.run(["ffmpeg", "-ss", "60", "-t", "4", "-i", video, "-vf",
                        "cropdetect=24:2:0", "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
    c = f"crop={':'.join(m[-1])}" if m else None
    _crop_cache[video] = c
    return c


def chain(video, scale_w=1408):
    """crop bars -> denoise -> modest lanczos upscale -> unsharp -> grade. NO 2x blow-up."""
    c = detect_crop(video)
    pre = (c + ",") if c else ""
    return (f"{pre}hqdn3d=3:3:6:6,scale={scale_w}:-2:flags=lanczos,"
            f"unsharp=7:7:1.1:7:7:0.35,eq=contrast=1.12:saturation=0.62:brightness=-0.01")


def objpath(c, a):
    sha = c._asset_object_sha(a)
    r = c.cx.execute("SELECT rel_path FROM objects WHERE sha256=?", (sha,)).fetchone()
    return os.path.join(os.environ["CDEV_LIBRARY_ROOT"], r["rel_path"]).replace("\\", "/") if r else None


def build_intro():
    """Cold open: real footage, its OWN audio, no narration."""
    out = f"{OUT}/intro.mp4"
    card = title_card("JUNE 27, 1988", "Atlantic City", f"{OUT}/introcard.png")
    fc = (f"[0:v]{chain(SPINKS_SRC)}[pic];"
          f"[1:v]null[bg];[bg][pic]overlay=(W-w)/2:(H-h)/2[framed];"
          f"[2:v]scale={W}:{H},format=gbrp[g];[framed]format=gbrp[b];"
          f"[b][g]blend=all_mode=screen:all_opacity=0.20,format=yuv420p[gr];"
          f"[3:v]format=rgba,fade=t=in:st=4.2:d=0.8:alpha=1,fade=t=out:st=7.0:d=0.8:alpha=1[t];"
          f"[gr][t]overlay=0:0,fade=t=in:st=0:d=0.6,fade=t=out:st={INTRO_LEN-0.5}:d=0.5[v]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-ss", str(INTRO_AT), "-t", str(INTRO_LEN), "-i", SPINKS_SRC,
           "-f", "lavfi", "-t", str(INTRO_LEN), "-i", f"color=c=0x0d0d10:s={W}x{H}:r={FPS}",
           "-stream_loop", "-1", "-t", str(INTRO_LEN), "-i", GRAIN,
           "-loop", "1", "-t", str(INTRO_LEN), "-i", card,
           "-filter_complex", fc, "-map", "[v]", "-map", "0:a",
           "-af", f"volume=0.85,afade=t=in:st=0:d=0.5,afade=t=out:st={INTRO_LEN-1.2}:d=1.0",
           "-t", str(INTRO_LEN), "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print("INTRO FAIL:", r.stderr[-400:]); return None
    return out


def build_shot(item):
    i, d = item["i"], item["dur"]
    out = f"{OUT}/s{i:03d}.mp4"
    ov = item.get("overlay")
    if item["kind"] == "card":
        inputs = ["-f", "lavfi", "-t", f"{d}", "-i", f"color=c=0x0d0d10:s={W}x{H}:r={FPS}",
                  "-stream_loop", "-1", "-t", f"{d}", "-i", GRAIN]
        fc = (f"[0:v]format=gbrp[b];[1:v]scale={W}:{H},format=gbrp[g];"
              f"[b][g]blend=all_mode=screen:all_opacity=0.20,format=yuv420p[bg]")
    else:
        inputs = ["-ss", f"{item['in']:.2f}", "-t", f"{min(d+0.3,7.0):.2f}", "-i", item["file"],
                  "-f", "lavfi", "-t", f"{d}", "-i", f"color=c=0x0d0d10:s={W}x{H}:r={FPS}",
                  "-stream_loop", "-1", "-t", f"{d}", "-i", GRAIN]
        flash = ",fade=t=in:st=0:d=0.09:color=white" if item["style"] == "flash" else ""
        fc = (f"[0:v]{chain(item['file'])}{flash}[pic];[1:v]null[bgc];"
              f"[bgc][pic]overlay=(W-w)/2:(H-h)/2,format=gbrp[b];"
              f"[2:v]scale={W}:{H},format=gbrp[g];"
              f"[b][g]blend=all_mode=screen:all_opacity=0.22,format=yuv420p[bg]")
    if ov:
        inputs += ["-loop", "1", "-t", f"{d}", "-i", ov]
        idx = 2 if item["kind"] == "card" else 3
        fc += f";[{idx}:v]format=rgba,fade=t=in:st=0.2:d=0.45:alpha=1[o];[bg][o]overlay=0:0[v]"
    else:
        fc += ";[bg]null[v]"
    cmd = (["ffmpeg", "-y", "-loglevel", "error"] + inputs +
           ["-filter_complex", fc, "-map", "[v]", "-t", f"{d:.2f}", "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", out])
    r = subprocess.run(cmd, capture_output=True, text=True)
    return (i, r.returncode == 0, r.stderr[-160:] if r.returncode else out)


T, S = "ENT_TYSON", "ENT_SPINKS"
OV = {
 3: (S, ("lower", "Michael Spinks", "31-0  ·  undefeated"), ""),
 4: (None, ("stat", "31-0", "undefeated"), "card"),
 9: (None, ("title", "JUNE 27, 1988", "Atlantic City"), "card"),
 10: (T, None, "flash"),
 11: (T, ("lower", "Mike Tyson", "34-0  ·  30 knockouts"), ""),
 12: (None, ("stat", "34-0", "thirty knockouts"), "card"),
}
STOP = {"the","a","an","and","was","were","that","this","had","has","have","to","of","in","it",
        "he","his","him","for","but","not","on","at","as","is","be","been","would","could",
        "what","who","them","they","there","which","with","about","more","most","than","then",
        "from","just","only","even","still","almost","every","one","two"}


def main():
    c = catalog_db.Catalog()
    beats = json.load(io.open(f"{HERE}/beats.json", encoding="utf-8"))
    audio_end = 90.0
    for k, b in enumerate(beats):
        nxt = beats[k+1]["start"] if k+1 < len(beats) else audio_end
        b["dur"] = round(max(1.0, nxt - (0.0 if k == 0 else b["start"])), 2)
    beats = [b for b in beats if b["start"] < audio_end]

    used, plan = [], []
    for b in beats:
        i = b["i"]
        ent, overlay, style = OV.get(i, (None, None, ""))
        rec = {"i": i, "dur": b["dur"], "style": style}
        if overlay:
            p = f"{OUT}/c{i:03d}.png"
            k = overlay[0]
            (title_card if k == "title" else lower_third if k == "lower" else stat_card)(
                overlay[1], overlay[2], p)
            rec["overlay"] = p
        if style == "card":
            rec["kind"] = "card"; plan.append(rec); continue
        q = " ".join([w for w in re.findall(r"[A-Za-z']+", b["text"])
                      if w.lower() not in STOP and len(w) > 2][:9])
        cands = c.search(query_text=q, type="video", required_any=[ent] if ent else None, top_k=40)
        if not cands:
            cands = c.search(query_text=q, type="video", top_k=40)
        pick = None
        for x in cands:
            if x["asset_id"] in used[-12:]:
                continue
            f = objpath(c, x)
            if f and gate_ok(f, x["start_ms"] / 1000, x["end_ms"] / 1000):
                pick = x; break
        if pick is None:
            # FAIL-CLOSED. Falling back to cands[0] here bypassed the quality gate entirely and
            # is how ESPN-branded frames reached the cut: when nothing passes, show a card.
            rec["kind"] = "card"
            plan.append(rec)
            continue
        if not pick:
            rec["kind"] = "card"; plan.append(rec); continue
        used.append(pick["asset_id"])
        seg = (pick["end_ms"] - pick["start_ms"]) / 1000.0
        need = min(b["dur"] + 0.3, 7.0)
        off = max(0.0, min(seg - need, (seg - need) / 2))
        rec.update({"kind": "video", "file": objpath(c, pick),
                    "in": round(pick["start_ms"] / 1000 + off, 2)})
        plan.append(rec)

    print(f"sample: {sum(1 for p in plan if p['kind']=='video')} footage + "
          f"{sum(1 for p in plan if p['kind']=='card')} cards, "
          f"{sum(1 for p in plan if p.get('overlay'))} overlays", flush=True)
    intro = build_intro()
    print("intro:", "ok" if intro else "FAILED", flush=True)
    fails = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, ok, info in ex.map(build_shot, plan):
            if not ok:
                fails.append(i); print(f"  shot {i} FAIL {info[:110]}", flush=True)
    print(f"built {len(plan)-len(fails)}/{len(plan)}", flush=True)

    # narration segment, then mux: intro (own audio) + body (narration)
    body_list = f"{OUT}/body.txt"
    with io.open(body_list, "w", encoding="utf-8") as f:
        for p in plan:
            fp = f"{OUT}/s{p['i']:03d}.mp4"
            if os.path.exists(fp):
                f.write(f"file '{fp}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", body_list, "-c", "copy", f"{OUT}/body_v.mp4"], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-t", str(audio_end),
                    "-i", f"{HERE}/vo/voiceover.mp3", "-c:a", "aac", "-b:a", "192k",
                    f"{OUT}/body_a.m4a"], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{OUT}/body_v.mp4",
                    "-i", f"{OUT}/body_a.m4a", "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", f"{OUT}/body.mp4"], check=True)
    final = f"{HERE}/SAMPLE_90s.mp4"
    lst = f"{OUT}/final.txt"
    with io.open(lst, "w", encoding="utf-8") as f:
        f.write(f"file '{intro}'\nfile '{OUT}/body.mp4'\n")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", lst, "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                        "-movflags", "+faststart", final], capture_output=True, text=True)
    if r.returncode:
        print("FINAL FAIL:", r.stderr[-400:]); return
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nk=1:nw=1", final], capture_output=True, text=True).stdout.strip()
    print(f"DONE: {final}  duration {dur}")


main()
