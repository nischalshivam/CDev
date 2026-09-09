#!/usr/bin/env python3
"""Build the 3:41 Tyson documentary.

Editing grammar reverse-engineered from a 119K-view boxing doc (measured, not guessed):
  * fast cadence — median shot ~2.8s, several shots per narration line
  * hard cuts, white flashes only at section breaks
  * film grain screen-blended in RGB (the YUV blend bug tints shots — format=gbrp both sides)
  * desaturated high-contrast grade to unify disparate archival sources
  * bold white ALL-CAPS text: centre title cards + bottom-left labels
  * slow motion on the emotional peaks

Two-pass render (robust): each shot -> normalized clip, then concat + mux VO.
"""

import sys, os, json, subprocess, re
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, f"{ROOT}/CODE")
os.environ["CDEV_LIBRARY_ROOT"] = f"{ROOT}/_tyson/library"
import catalog_db

# Repo root, derived from THIS file. Never hard-code an absolute path: a machine change (or a
# different drive letter) silently sends every read and write somewhere else. One earlier build
# wrote 719 files into the wrong library for exactly this reason, and the same mistake was already
# sitting in two other files at the time.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

HERE = f"{ROOT}/_tyson"
W, H, FPS = 1920, 1080, 30
FONT = "C\\:/Windows/Fonts/arialbd.ttf"
GRAIN = f"{HERE}/fx/grain.mp4"
SHOTS_DIR = f"{HERE}/shots"
os.makedirs(SHOTS_DIR, exist_ok=True)

T = "ENT_TYSON"; G = "ENT_GOLOTA"
# (start, end, query, required_any, text, style)   style: ''|'flash'|'slow'|'title'
PLAN = [
 (0.0,  2.6,  "Mike Tyson standing looking down defeated older",       [T], "", "flash"),
 (2.6,  5.4,  "Mike Tyson face close up serious",                      [T], "", ""),
 (5.4,  9.0,  "Mike Tyson hurt taking punches on the ropes",           [T], "", ""),
 (9.0,  12.7, "boxer knocked down on the canvas defeat",               [],  "", ""),
 (12.7, 15.6, "arena crowd wide shot before the fight",                [],  "", ""),
 (15.6, 19.0, "empty ring ropes lights arena",                         [],  "", ""),
 (19.0, 22.0, "Mike Tyson walking to the ring menacing entrance",      [T], "", "flash"),
 (22.0, 25.0, "Mike Tyson intense stare before fight",                 [T], "", "slow"),
 (25.0, 27.3, "",                                                      [],  "OCTOBER 20, 2000\nLAS VEGAS", "title"),
 (27.3, 30.0, "packed arena crowd cheering wide",                      [],  "", ""),
 (30.0, 32.5, "crowd spectators watching ringside",                    [],  "", ""),
 (32.5, 35.6, "boxing ring under lights wide arena",                   [],  "", ""),
 (35.6, 39.1, "Mike Tyson in the corner waiting",                      [T], "", ""),
 (39.1, 41.6, "Mike Tyson landing a devastating knockout punch",       [T], "", "flash"),
 (41.6, 44.0, "Mike Tyson knockout opponent falls",                    [T], "", ""),
 (44.0, 47.3, "Mike Tyson celebrating victory raising arms",           [T], "", ""),
 (47.3, 49.6, "Mike Tyson serious portrait",                           [T], "", ""),
 (49.6, 51.2, "boxer down defeat canvas",                              [],  "", ""),
 (51.2, 53.1, "Mike Tyson head down corner",                           [T], "", ""),
 (53.1, 56.2, "Mike Tyson looking tired vulnerable",                   [T], "", "slow"),
 # --- Golota ---
 (56.2, 59.2, "Andrew Golota standing in the ring",                    [G], "", "flash"),
 (59.2, 62.0, "Andrew Golota close up face",                           [G], "", ""),
 (62.0, 64.6, "Andrew Golota tall heavyweight boxer standing",         [G], "ANDREW GOLOTA", ""),
 (64.6, 67.4, "Andrew Golota in the ring with trainer",                [G], "6'4\"  ·  240 LBS", ""),
 (67.4, 70.6, "Andrew Golota boxer portrait",                          [G], "", ""),
 (70.6, 74.0, "Andrew Golota walking with team",                       [G], "36 WINS  ·  4 LOSSES", ""),
 (74.0, 76.6, "Andrew Golota throwing a jab punch",                    [G], "", ""),
 (76.6, 80.1, "Andrew Golota landing heavy punch power",               [G], "", ""),
 (80.1, 83.4, "Andrew Golota referee warning foul",                    [G], "", ""),
 (83.4, 87.5, "boxers clinching referee separating chaos",             [],  "", ""),
 # --- fight begins ---
 (87.5, 90.0, "boxers entering the ring before the bell",              [],  "", "flash"),
 (90.0, 93.0, "Mike Tyson black trunks ready to fight",                [T], "", ""),
 (93.0, 96.7, "boxing bell round begins fighters advance",             [],  "", ""),
 (96.7, 99.9, "Mike Tyson pressing forward inside",                    [T], "", ""),
 (99.9, 102.5,"Mike Tyson throwing punches aggressive",                [T], "", ""),
 (102.5,104.3,"Andrew Golota defending guard up",                      [G], "", ""),
 (104.3,106.5,"two boxers facing each other in the ring",              [],  "", ""),
 (106.5,109.5,"referee giving instructions centre of the ring",        [],  "", ""),
 (109.5,112.9,"boxers touching gloves before the round",               [],  "", ""),
 (112.9,115.0,"Mike Tyson explosive punch attack",                     [T], "", "flash"),
 (115.0,116.9,"Mike Tyson hook to the head",                           [T], "", ""),
 (116.9,119.0,"Mike Tyson body shot close range",                      [T], "", ""),
 (119.0,121.4,"Mike Tyson landing right hand",                         [T], "", ""),
 (121.4,123.6,"Andrew Golota hit head snaps back",                     [G], "", ""),
 (123.6,126.0,"Mike Tyson relentless combination punches",             [T], "", ""),
 (126.0,128.6,"Andrew Golota hurt covering up",                        [G], "", ""),
 (128.6,132.3,"Andrew Golota bleeding cut face",                       [G], "", "slow"),
 (132.3,135.0,"Mike Tyson intense angry face",                         [T], "", "flash"),
 (135.0,138.4,"Mike Tyson ferocious attack in the corner",             [T], "", ""),
 (138.4,141.0,"Mike Tyson dominant standing over opponent",            [T], "", ""),
 (141.0,145.1,"Mike Tyson stalking forward",                           [T], "", ""),
 # --- climax ---
 (145.1,147.6,"boxer sitting on the stool in the corner",              [],  "", "flash"),
 (147.6,150.3,"Andrew Golota corner trainer talking",                  [G], "", ""),
 (150.3,153.0,"corner men arguing with the fighter",                   [],  "", ""),
 (153.0,156.0,"Andrew Golota shaking his head refusing",               [G], "", ""),
 (156.0,159.2,"trainer shouting at boxer in corner",                   [],  "", ""),
 (159.2,163.0,"Andrew Golota sitting refusing to continue",            [G], "", "slow"),
 (163.0,167.9,"referee and officials in the ring",                     [],  "", ""),
 (167.9,171.0,"Andrew Golota leaving the ring",                        [G], "", ""),
 (171.0,173.7,"crowd reacting shocked arena",                          [],  "", ""),
 (173.7,176.5,"corner chaos handlers around fighter",                  [],  "", ""),
 (176.5,179.3,"Mike Tyson watching from the ring",                     [T], "", ""),
 (179.3,182.5,"Mike Tyson power punch replay",                         [T], "", ""),
 (182.5,186.0,"Andrew Golota face swollen after the fight",            [G], "", ""),
 (186.0,189.5,"Mike Tyson standing in the ring waiting",               [T], "", ""),
 (189.5,191.3,"crowd cheering reaction",                               [],  "", ""),
 (191.3,194.5,"ring announcer with microphone",                        [],  "", "flash"),
 (194.5,198.0,"referee raising the fighter's hand",                    [],  "", ""),
 (198.0,201.8,"Mike Tyson victory celebration in the ring",            [T], "", ""),
 (201.8,205.2,"Mike Tyson arms raised winner",                         [T], "", ""),
 (205.2,208.2,"Mike Tyson celebrating the win",                        [T], "", ""),
 (208.2,212.2,"Mike Tyson victorious close up",                        [T], "", "slow"),
 (212.2,215.5,"Mike Tyson walking away from the ring",                 [T], "", "flash"),
 (215.5,218.8,"Mike Tyson portrait intense",                           [T], "", ""),
 (218.8,221.4,"Mike Tyson standing alone in the ring",                 [T], "", "slow"),
]

GRADE = "eq=contrast=1.22:saturation=0.55:brightness=-0.02,unsharp=5:5:0.35"


def objpath(c, asset):
    sha = c._asset_object_sha(asset)
    row = c.cx.execute("SELECT rel_path FROM objects WHERE sha256=?", (sha,)).fetchone()
    return os.path.join(os.environ["CDEV_LIBRARY_ROOT"], row["rel_path"]).replace("\\", "/") if row else None


def assign():
    c = catalog_db.Catalog()
    used, plan_out = [], []
    for i, (s, e, q, ents, txt, style) in enumerate(PLAN):
        dur = round(e - s, 2)
        if style == "title" or not q:
            plan_out.append({"i": i, "dur": dur, "kind": "title", "text": txt, "style": style,
                             "asset": "TITLE", "query": q})
            continue
        cands = c.search(query_text=q, type="video", required_any=ents or None, top_k=40)
        if not cands:
            cands = c.search(query_text=q, type="video", top_k=40)
        # prefer shots with NO burned-in broadcast graphic; 'fixable' ones only if nothing else
        cands.sort(key=lambda x: (x.get("clean_status") != "clean", -x.get("score", 0)))
        pick = next((x for x in cands if x["asset_id"] not in used[-14:]), cands[0] if cands else None)
        if not pick:
            plan_out.append({"i": i, "dur": dur, "kind": "title", "text": txt or "", "style": "title",
                             "asset": "TITLE", "query": q}); continue
        used.append(pick["asset_id"])
        c.mark_used(pick["asset_id"], channel="tyson")
        src = objpath(c, pick)
        # take from the middle of the catalogued segment so we never sit on its edges
        seg_len = (pick["end_ms"] - pick["start_ms"]) / 1000.0
        need = dur * (1.6 if style == "slow" else 1.0) + 0.3
        off = max(0.0, min(seg_len - need, (seg_len - need) / 2))
        plan_out.append({"i": i, "dur": dur, "kind": "video", "text": txt, "style": style,
                         "asset": pick["asset_id"], "file": src,
                         "in": round(pick["start_ms"] / 1000.0 + off, 2),
                         "desc": pick["description"][:70], "query": q})
    json.dump(plan_out, open(f"{HERE}/assign.json", "w"), indent=1)
    return plan_out


def esc(t):
    return t.replace("\\", "").replace(":", r"\:").replace("'", "").replace(",", r"\,")


_CROP_CACHE = {}


def detect_crop(path, t):
    """Archival sources are 4:3 pillarboxed inside 16:9 — those black bars survive scale+crop and
    look amateur. Measure the real picture area with cropdetect and cut the bars off first."""
    key = (path, round(t / 30))
    if key in _CROP_CACHE:
        return _CROP_CACHE[key]
    r = subprocess.run(["ffmpeg", "-hide_banner", "-ss", f"{max(0,t):.2f}", "-i", path, "-t", "2",
                        "-vf", "cropdetect=limit=24:round=2:reset=0", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
    val = None
    if m:
        w, h, x, y = map(int, m[-1])
        src = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
                             capture_output=True, text=True).stdout.strip().split(",")
        try:
            sw, sh = int(src[0]), int(src[1])
        except Exception:
            sw = sh = 0
        # only trust a sane crop: keeps >45% of the frame and actually removes something
        if w > 100 and h > 100 and sw and (w * h) > 0.45 * sw * sh and (w < sw - 8 or h < sh - 8):
            val = f"crop={w}:{h}:{x}:{y},"
    _CROP_CACHE[key] = val or ""
    return _CROP_CACHE[key]


def build_shot(item):
    out = f"{SHOTS_DIR}/s{item['i']:03d}.mp4"
    d = item["dur"]
    if item["kind"] == "title":
        vf = (f"scale={W}:{H},{GRADE},format=gbrp[b];[1:v]scale={W}:{H},format=gbrp[g];"
              f"[b][g]blend=all_mode=screen:all_opacity=0.30,format=yuv420p")
        # two-line title card as two drawtext calls — embedding "\n" in a filtergraph string
        # silently renders a literal "n" (seen in the first build)
        lines = [esc(l) for l in (item["text"] or "").split("\n") if l.strip()]
        draw = ""
        for li, ln in enumerate(lines):
            yy = f"(h/2)-{70 if len(lines) > 1 else 40}+{li*112}"
            draw += (f",drawtext=fontfile='{FONT}':text='{ln}':x=(w-text_w)/2:y={yy}:"
                     f"fontsize=88:fontcolor=white:alpha='min(1,t*4)'")
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={d}",
               "-stream_loop", "-1", "-t", f"{d}", "-i", GRAIN,
               "-filter_complex", vf + draw + "[v]", "-map", "[v]",
               "-t", f"{d}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "20", "-pix_fmt", "yuv420p", out]
    else:
        speed = "setpts=1.6*PTS," if item["style"] == "slow" else ""
        grab = d * (1.6 if item["style"] == "slow" else 1.0) + 0.25
        flash = (f",fade=t=in:st=0:d=0.10:color=white") if item["style"] == "flash" else ""
        txt = esc(item["text"] or "")
        draw = (f",drawtext=fontfile='{FONT}':text='{txt}':x=70:y=h-165:fontsize=52:"
                f"fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=22") if txt else ""
        bars = detect_crop(item["file"], item["in"])          # strip pillar/letterbox first
        chain = (f"[0:v]{bars}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                 f"{speed}fps={FPS},{GRADE}{flash}{draw},setsar=1,format=gbrp[b];"
                 f"[1:v]scale={W}:{H},format=gbrp[g];"
                 f"[b][g]blend=all_mode=screen:all_opacity=0.26,format=yuv420p[v]")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{item['in']:.2f}",
               "-t", f"{grab:.2f}", "-i", item["file"],
               "-stream_loop", "-1", "-t", f"{grab:.2f}", "-i", GRAIN,
               "-filter_complex", chain, "-map", "[v]",
               "-t", f"{d:.2f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "20", "-pix_fmt", "yuv420p", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return (item["i"], False, r.stderr[-200:])
    return (item["i"], True, out)


def main():
    plan = assign()
    print(f"assigned {len(plan)} shots "
          f"({sum(1 for p in plan if p['kind']=='video')} video, "
          f"{sum(1 for p in plan if p['kind']=='title')} title)", flush=True)
    fails = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, ok, info in ex.map(build_shot, plan):
            if not ok:
                fails.append((i, info)); print(f"  shot {i} FAILED: {info[:120]}", flush=True)
    print(f"built {len(plan)-len(fails)}/{len(plan)} shots", flush=True)

    lst = f"{HERE}/concat.txt"
    with open(lst, "w") as f:
        for p in plan:
            fp = f"{SHOTS_DIR}/s{p['i']:03d}.mp4"
            if os.path.exists(fp):
                f.write(f"file '{fp}'\n")
    out = f"{HERE}/TYSON_DOC.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
           "-i", f"{HERE}/vo.wav", "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("CONCAT FAIL:", r.stderr[-400:]); return
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nk=1:nw=1", out], capture_output=True, text=True).stdout.strip()
    print(f"DONE: {out}  duration {dur}")


if __name__ == "__main__":
    main()
