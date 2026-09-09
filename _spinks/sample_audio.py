#!/usr/bin/env python3
"""90s sample, audio-first pass: punch-ins + score bed + section hits.

The complaint this answers: "flat audio ek boring video ka sanket deti hai" — correct. Narration
over pictures is not a documentary. Three things are added:

  PUNCH-INS  the narration stops for ~3.5s and the ORIGINAL match audio plays (crowd, corner, the
             punch). Video and audio are built from ONE ordered list, so inserting a punch-in
             lengthens both by exactly the same amount and sync cannot drift.
  SCORE BED  a dark drone under everything, side-chain ducked by the voice so speech always wins.
  HITS       a low impact on section breaks so cuts land instead of just happening.
"""

import sys, os, io, json, math, subprocess, re
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, f"{ROOT}/CODE")
os.environ["CDEV_LIBRARY_ROOT"] = f"{ROOT}/_tyson/library"
import catalog_db
import entity_bind as EB
import frame_quality as FQ
import audio_design as AD
from typography import title_card, lower_third, stat_card

# Repo root, derived from THIS file. Never hard-code an absolute path: a machine change (or a
# different drive letter) silently sends every read and write somewhere else. One earlier build
# wrote 719 files into the wrong library for exactly this reason, and the same mistake was already
# sitting in two other files at the time.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

HERE = f"{ROOT}/_spinks"
W, H, FPS = 1920, 1080, 30
GRAIN = f"{ROOT}/_tyson/fx/grain.mp4"
OUT = f"{HERE}/sa"; os.makedirs(OUT, exist_ok=True)
SPINKS = f"{HERE}/raw2/lN4s_HNoIaQ.mp4"
NARR = f"{HERE}/vo/voiceover.mp3"
BODY_END = 90.0
MAX_SHOT = 4.0       # no single picture holds longer than this; also keeps every grab under the
                     # 5-7s clip cap with room to spare
INTRO_AT, INTRO_LEN = 130.0, 8.0
# gated-clean windows found earlier (sharp, overlay < 0.8%)
PUNCH = [{"at": 15.9, "src_at": 60.0,  "dur": 3.2},
         {"at": 37.5, "src_at": 100.0, "dur": 3.4},
         {"at": 57.4, "src_at": 130.0, "dur": 3.4},
         {"at": 80.8, "src_at": 90.0,  "dur": 3.2}]

_crop, _fc, _dims = {}, {}, {}


def src_dims(v):
    if v not in _dims:
        o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", v],
                           capture_output=True, text=True).stdout.strip().split(",")
        _dims[v] = (int(o[0]), int(o[1])) if len(o) == 2 else (1280, 720)
    return _dims[v]


def detect_crop(v):
    """Pillarbox/letterbox removal. Returns (w, h, x, y) or None."""
    if v not in _crop:
        r = subprocess.run(["ffmpeg", "-ss", "60", "-t", "4", "-i", v, "-vf", "cropdetect=24:2:0",
                            "-f", "null", "-"], capture_output=True, text=True)
        m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
        _crop[v] = tuple(int(x) for x in m[-1]) if m else None
    return _crop[v]


SRC_CACHE = f"{OUT}/source_cache.json"
try:
    _brand = json.load(io.open(SRC_CACHE, encoding="utf-8"))
except Exception:
    _brand = {}


def brand_trim(v):
    """Fraction of the picture to cut off top and bottom to remove a rival channel's captions.

    Cached to disk and keyed on the object hash. Branding is a property of the SOURCE FILE, so it
    can never change for a given object — recomputing it is pure waste, and this measurement is
    the most expensive one in the build (a full decode of a half-hour source).

    It must also be warmed BEFORE the render thread pool starts. Left to be called lazily from
    inside chain(), six worker threads each began decoding the same source at the same time; the
    build did no visible work for over an hour. Cheap per-shot lookups can live in the pool;
    whole-source measurements cannot."""
    k = os.path.basename(v)
    if k not in _brand:
        _brand[k] = FQ.branding_box(FQ.decode_frames(v, fps=0.25, width=768))
        json.dump(_brand, io.open(SRC_CACHE, "w", encoding="utf-8"), indent=1)
    return _brand[k]


def full_crop(v):
    """Pillarbox removal AND branding removal, as one crop expression.

    Order matters: cropdetect first (its bars are part of the encoded frame), then the branding
    trim applied to what is left. The branding rows are measured on the uncropped source, which is
    safe here because these sources are pillarboxed — bars on the sides, so every row index is
    unchanged. A letterboxed source would shift the rows, so the trim is skipped when cropdetect
    removed height."""
    c = detect_crop(v)
    sw_, sh_ = src_dims(v)
    cw, ch, cx, cy = c if c else (sw_, sh_, 0, 0)
    b = brand_trim(v)
    if ch >= sh_ - 2:                      # cropdetect took no height -> row indices still valid
        top, bot = int(ch * b["top"]), int(ch * b["bottom"])
        if top or bot:
            nh = ch - top - bot
            # Keep the ORIGINAL aspect by taking the same proportion off the width, centred.
            # Trimming height alone made the picture far wider than 16:9; the render fits it to a
            # 1408px width and centres it, so it came back as a short strip with big black bands
            # above and below — six new near-black stretches, one of them 13 seconds. Cropping
            # both axes zooms in instead, which costs some side framing and nothing else.
            nw = max(16, int(cw * nh / ch) // 2 * 2)
            cx, cw = cx + (cw - nw) // 2, nw
            cy, ch = cy + top, nh // 2 * 2
    return (cw, ch, cx, cy) if (cw, ch, cx, cy) != (sw_, sh_, 0, 0) else None


TARGET_Y = 108.0     # 0-255 mean luma aimed for BEFORE the grade's own slight darkening
_lvl = {}


def autolevel(v, at):
    """Per-shot exposure correction, measured on the CROPPED picture.

    A single fixed grade for every shot is why 30 seconds of the last cut sat below YAVG 40 —
    visibly black on a normal screen. Archival sources vary enormously in exposure and a grade
    tuned for the bright ones buries the dark ones.

    Measured after cropdetect on purpose: these sources carry baked-in pillarbox (one has picture
    in only 808 of its 1280 columns), and those black bars drag an uncropped mean far below what
    the viewer actually sees, so the correction would be computed from bars rather than picture.

    Gamma, not brightness: gamma lifts shadows while leaving highlights alone, where a brightness
    offset would raise the black floor and wash the image out."""
    key = (v, round(at, 1))
    if key not in _lvl:
        c = full_crop(v)
        vf = ((f"crop={c[0]}:{c[1]}:{c[2]}:{c[3]}," if c else "")
              + "fps=4,signalstats,metadata=print:key=lavfi.signalstats.YAVG")
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{max(0.0,at):.2f}",
                            "-t", "2.0", "-i", v, "-vf", vf, "-f", "null", "-"],
                           capture_output=True, text=True)
        ys = [float(x) for x in re.findall(r"YAVG=([\d.]+)", r.stderr)]
        y = min(250.0, max(10.0, sum(ys) / len(ys) if ys else TARGET_Y))
        # ffmpeg's eq gamma is out = in**(1/g) on normalised values, so the g that lands a mean of
        # y exactly on TARGET_Y is ln(y/255) / ln(TARGET_Y/255). Solving it beats the ratio-to-a-
        # power guess it replaces, which under-corrected the darkest shots and left them black.
        g_ideal = math.log(y / 255.0) / math.log(TARGET_Y / 255.0)
        # damped 0.85 toward neutral: shots should still differ in exposure, just not be invisible
        _lvl[key] = round(max(0.80, min(2.40, 1.0 + (g_ideal - 1.0) * 0.85)), 3)
    return _lvl[key]


def chain(v, sw=1408, at=None):
    c = full_crop(v)
    g = autolevel(v, at) if at is not None else 1.0
    return ((f"crop={c[0]}:{c[1]}:{c[2]}:{c[3]}," if c else "")
            + (f"hqdn3d=3:3:6:6,scale={sw}:-2:flags=lanczos,"
            f"unsharp=7:7:1.1:7:7:0.35,"
            f"eq=gamma={g}:contrast=1.10:saturation=0.66:brightness=0.005"))


def gate_ok(v, a, b):
    try:
        if v not in _fc:
            fr = FQ.decode_frames(v, fps=2.0)
            _fc[v] = (fr, FQ.source_edge_median(fr))
        fr, em = _fc[v]
        return FQ.assess_batch(fr, a, min(b, a + 4.0), src_edge_median=em)["usable"]
    except Exception:
        return False          # fail-closed


def objpath(c, a):
    sha = c._asset_object_sha(a)
    r = c.cx.execute("SELECT rel_path FROM objects WHERE sha256=?", (sha,)).fetchone()
    return os.path.join(os.environ["CDEV_LIBRARY_ROOT"], r["rel_path"]).replace("\\", "/") if r else None



def build_intro():
    """8s cold open: real footage with its OWN audio, no narration. This existed in the earlier
    sample and was dropped here by mistake — the variable stayed, the call did not."""
    out = f"{OUT}/intro.mp4"
    card = title_card("JUNE 27, 1988", "Atlantic City", f"{OUT}/introcard.png")
    fc = (f"[0:v]{chain(SPINKS, at=INTRO_AT)}[pic];[1:v]null[bg];[bg][pic]overlay=(W-w)/2:(H-h)/2[fr];"
          f"[2:v]scale={W}:{H},format=gbrp[g];[fr]format=gbrp[b];"
          f"[b][g]blend=all_mode=screen:all_opacity=0.20,format=yuv420p[gr];"
          f"[3:v]format=rgba,fade=t=in:st=4.0:d=0.7:alpha=1,fade=t=out:st=6.9:d=0.7:alpha=1[t];"
          f"[gr][t]overlay=0:0,fade=t=in:st=0:d=0.6,fade=t=out:st={INTRO_LEN-0.5}:d=0.5[v]")
    r = subprocess.run(["ffmpeg","-y","-loglevel","error",
        "-ss",str(INTRO_AT),"-t",str(INTRO_LEN),"-i",SPINKS,
        "-f","lavfi","-t",str(INTRO_LEN),"-i",f"color=c=0x0d0d10:s={W}x{H}:r={FPS}",
        "-stream_loop","-1","-t",str(INTRO_LEN),"-i",GRAIN,
        "-loop","1","-t",str(INTRO_LEN),"-i",card,
        "-filter_complex",fc,"-map","[v]","-map","0:a",
        "-af",f"volume=1.0,afade=t=in:st=0:d=0.5,afade=t=out:st={INTRO_LEN-1.2}:d=1.0",
        "-t",str(INTRO_LEN),"-r",str(FPS),"-c:v","libx264","-preset","veryfast","-crf","19",
        "-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-ar","48000","-ac","2", out],
        capture_output=True, text=True)
    if r.returncode:
        print("INTRO FAIL:", r.stderr[-300:]); return None
    return out


def render_shot(item):
    i, d = item["i"], item["dur"]
    out = f"{OUT}/v{i:03d}.mp4"
    ov = item.get("overlay")
    if item["kind"] == "card":
        # A card is now a LAST resort, and it moves. Two 9-second stretches of a motionless
        # near-black card shipped in the last cut (YAVG 26 of 255, 21% of the runtime frozen);
        # the animated grain made it look alive to a naive freeze test but not to a viewer.
        # A slow drifting gradient gives it real motion and lifts it out of black.
        inp = ["-f", "lavfi", "-t", f"{d}",
               "-i", f"gradients=s={W}x{H}:r={FPS}:c0=0x14141b:c1=0x05050a:speed=0.012:"
                     f"x0={W//3}:y0={H//2}:x1={W}:y1=0:d={d}",
               "-stream_loop", "-1", "-t", f"{d}", "-i", GRAIN]
        fc = (f"[0:v]format=gbrp[b];[1:v]scale={W}:{H},format=gbrp[g];"
              f"[b][g]blend=all_mode=screen:all_opacity=0.20,format=yuv420p[bg]")
        nxt = 2
    else:
        # d is clamped to the fetched length: if the grab is ever shorter than the slot, overlay's
        # eof_action=repeat silently freezes the last frame for the remainder. That is exactly how
        # a 9.4s slot fed by a 7s grab produced 2.4s of frozen picture nobody asked for.
        d = min(d, 7.0)
        inp = ["-ss", f"{item['in']:.2f}", "-t", f"{min(d+0.3,7.0):.2f}", "-i", item["file"],
               "-f", "lavfi", "-t", f"{d}", "-i", f"color=c=0x0d0d10:s={W}x{H}:r={FPS}",
               "-stream_loop", "-1", "-t", f"{d}", "-i", GRAIN]
        fl = ",fade=t=in:st=0:d=0.09:color=white" if item["style"] == "flash" else ""
        fc = (f"[0:v]{chain(item['file'], at=item['in'])}{fl}[pic];[1:v]null[bgc];"
              f"[bgc][pic]overlay=(W-w)/2:(H-h)/2,format=gbrp[b];"
              f"[2:v]scale={W}:{H},format=gbrp[g];"
              f"[b][g]blend=all_mode=screen:all_opacity=0.22,format=yuv420p[bg]")
        nxt = 3
    if ov:
        inp += ["-loop", "1", "-t", f"{d}", "-i", ov]
        fc += f";[{nxt}:v]format=rgba,fade=t=in:st=0.2:d=0.45:alpha=1[o];[bg][o]overlay=0:0[v]"
    else:
        fc += ";[bg]null[v]"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + inp +
        ["-filter_complex", fc, "-map", "[v]", "-t", f"{d:.2f}", "-r", str(FPS),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", out],
        capture_output=True, text=True)
    return (i, r.returncode == 0, r.stderr[-150:] if r.returncode else out)


T, S = "ENT_TYSON", "ENT_SPINKS"
OVR = {3: (S, ("lower", "Michael Spinks", "31-0  ·  undefeated"), ""),
       4: (None, ("stat", "31-0", "undefeated"), "card"),
       9: (None, ("title", "JUNE 27, 1988", "Atlantic City"), "card"),
       10: (T, None, "flash"),
       11: (T, ("lower", "Mike Tyson", "34-0  ·  30 knockouts"), ""),
       12: (None, ("stat", "34-0", "thirty knockouts"), "card")}
STOP = set("the a an and was were that this had has have to of in it he his him for but not on at "
           "as is be been would could what who them they there which with about more most than "
           "then from just only even still almost every one two".split())


# Broad queries tried when a beat's own words retrieve nothing that passes the gate. These are
# still gated exactly like a primary pick — this widens the SEARCH, it does not lower the bar.
GENERIC = ["boxing ring crowd arena wide", "boxer punches combination ring",
           "heavyweight boxer close up face", "crowd audience arena night fight",
           "boxer training heavy bag gym", "referee boxing ring canvas"]


def try_queries(c, queries, ent, used):
    """First candidate that is not a recent repeat AND passes the frame-quality gate.

    Every search is roster-bound. Dropping the entity requirement when a specific person yields
    nothing is fine — showing the crowd instead of Tyson is a weaker shot, not a wrong one — but
    the roster is never dropped, because that is what keeps another fighter's footage out."""
    for q in queries:
        cands = c.search(query_text=q, type="video", roster=EB.SPINKS_ROSTER,
                         scope_collections=EB.SPINKS_SCOPE,
                         required_any=[ent] if ent else None, top_k=90)
        if not cands and ent:
            cands = c.search(query_text=q, type="video", roster=EB.SPINKS_ROSTER,
                             scope_collections=EB.SPINKS_SCOPE, top_k=90)
        for x in cands:
            if x["asset_id"] in used[-12:]:
                continue
            f = objpath(c, x)
            if f and gate_ok(f, x["start_ms"] / 1000, x["end_ms"] / 1000):
                return x
    return None


BEAT_ENT = {}


def main():
    global BEAT_ENT
    try:
        BEAT_ENT = {int(k): v for k, v in EB.load(f"{HERE}/beat_entities.json").items()}
        print(f"beat->entity map: {len(BEAT_ENT)} of 100 beats bound to a named person", flush=True)
    except Exception as e:
        print(f"beat->entity map MISSING ({e}) — falling back to the 6 hand-written beats",
              flush=True)
    c = catalog_db.Catalog()
    beats = json.load(io.open(f"{HERE}/beats.json", encoding="utf-8"))
    for k, b in enumerate(beats):
        nxt = beats[k+1]["start"] if k+1 < len(beats) else BODY_END
        b["dur"] = round(max(1.0, nxt - (0.0 if k == 0 else b["start"])), 2)
    beats = [b for b in beats if b["start"] < BODY_END]

    # ---- 1a. SPLIT long beats into shot-length slots -------------------------------------
    # A beat is a unit of SPEECH, not a unit of PICTURE, and gap-inclusive durations made some
    # beats 9.4s long. Three separate defects came out of that one fact:
    #   * the 5-7s clip cap means only 7s of source is fetched, so overlay's eof_action=repeat
    #     froze the last frame for the remaining 2.4s — a freeze nobody wrote
    #   * a 9.4s hold is a slideshow, not a documentary
    #   * one unlucky dark clip then owned nine seconds of screen
    # Splitting into <=MAX_SHOT slots fixes all three: every slot retrieves its own clip, so the
    # cut rate roughly doubles and no single pick can dominate.
    slots = []
    for b in beats:
        n = max(1, int(math.ceil(b["dur"] / MAX_SHOT)))
        per = b["dur"] / n
        for j in range(n):
            slots.append({**b, "dur": round(per, 2), "start": b["start"] + j * per,
                          "i": b["i"] * 10 + j, "beat_i": b["i"], "sub": j})
    print(f"{len(beats)} beats -> {len(slots)} shot slots "
          f"(max {MAX_SHOT:.1f}s each, avg {sum(s['dur'] for s in slots)/len(slots):.1f}s)",
          flush=True)
    beats = slots

    # ---- 1. audio first: punch-in source audio, then the spliced voice track ----
    pins = []
    for j, p in enumerate(PUNCH):
        wav = f"{OUT}/pin{j}.wav"
        AD.cut_source_audio(SPINKS, p["src_at"], p["dur"], wav)
        pins.append({"at": p["at"], "audio": wav, "dur": p["dur"], "src_at": p["src_at"]})
    voice, _tl = AD.build_voice_track(NARR, pins, BODY_END, f"{OUT}/vt", f"{OUT}/voice.wav")
    vdur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nk=1:nw=1", voice], capture_output=True, text=True).stdout.strip())
    print(f"voice track: {vdur:.1f}s ({BODY_END:.0f}s narration + "
          f"{sum(p['dur'] for p in pins):.1f}s punch-ins)", flush=True)

    # ---- 2. video plan in the SAME order, punch-ins inserted as shots ----
    used, plan, pi = [], [], 0
    for b in beats:
        while pi < len(pins) and pins[pi]["at"] <= b["start"]:
            p = pins[pi]
            plan.append({"i": 900 + pi, "dur": p["dur"], "kind": "video", "style": "flash",
                         "file": SPINKS, "in": p["src_at"], "punch": True})
            pi += 1
        i = b["i"]
        # overlays are keyed on the BEAT and only fire on its first slot; the entity applies to
        # every slot of the beat, because the same sentence is still being spoken over all of them
        _ent, overlay, style = OVR.get(b["beat_i"], (None, None, "")) if b["sub"] == 0 \
            else (OVR.get(b["beat_i"], (None, None, ""))[0], None, "")
        # BEAT_ENT is resolved for ALL beats, pronouns included. It replaces a hand-written table
        # that covered six of a hundred; the other ninety-four took whatever the words matched,
        # which is how a Muhammad Ali clip ended up under narration about Tyson.
        ent = BEAT_ENT.get(b["beat_i"], _ent)
        rec = {"i": i, "dur": b["dur"], "style": style}
        if overlay:
            pth = f"{OUT}/c{i:03d}.png"
            k = overlay[0]
            (title_card if k == "title" else lower_third if k == "lower" else stat_card)(
                overlay[1], overlay[2], pth)
            rec["overlay"] = pth
        if style == "card":
            rec["kind"] = "fill"; plan.append(rec); continue      # overlay goes OVER footage
        q = " ".join([w for w in re.findall(r"[A-Za-z']+", b["text"])
                      if w.lower() not in STOP and len(w) > 2][:9])
        pick = try_queries(c, [q], ent, used) or try_queries(c, GENERIC, None, used)
        if pick is None:
            rec["kind"] = "fill"; plan.append(rec); continue      # filled below, never left dead
        used.append(pick["asset_id"])
        seg = (pick["end_ms"] - pick["start_ms"]) / 1000.0
        need = min(b["dur"] + 0.3, 7.0)
        off = max(0.0, min(seg - need, (seg - need) / 2))
        rec.update({"kind": "video", "file": objpath(c, pick),
                    "in": round(pick["start_ms"]/1000 + off, 2)})
        plan.append(rec)

    # ---- 2b. fill: NO BARE CARDS ----------------------------------------------------------
    # The last cut spent 21% of its runtime on motionless near-black filler cards, including two
    # 9-second stretches. Cause: when retrieval found nothing that passed the gate, the fallback
    # was a card — and a beat's card ran for the beat's full gap-inclusive duration.
    #
    # Fail-closed is unchanged: nothing ungated reaches the cut. What changes is the fallback.
    # A beat retrieval cannot serve now re-uses a clip that DID pass the gate, at its own gated
    # in-point, chosen as far from its neighbours in the plan as possible. Overlays composite on
    # top of that footage instead of on black — which is what a documentary does anyway.
    pool = [(p["file"], p["in"]) for p in plan if p["kind"] == "video" and not p.get("punch")]
    fills = [k for k, p in enumerate(plan) if p["kind"] == "fill"]
    for n, k in enumerate(fills):
        if not pool:
            plan[k]["kind"] = "card"; continue
        # stride through the pool by a step coprime-ish to its length so consecutive fills are
        # never the same clip and re-uses spread across the whole pool
        f, at = pool[(n * 5 + 2) % len(pool)]
        plan[k].update({"kind": "video", "file": f, "in": at, "reused": True})
    print(f"filled {len(fills)} un-served beats from a pool of {len(pool)} gated clips "
          f"({sum(1 for p in plan if p['kind']=='card')} bare cards remain)", flush=True)

    nv = sum(1 for p in plan if p["kind"] == "video" and not p.get("punch"))
    print(f"plan: {nv} footage + {sum(1 for p in plan if p['kind']=='card')} cards + "
          f"{len(pins)} punch-ins", flush=True)

    # warm every whole-source measurement single-threaded before the pool (see brand_trim)
    for v in sorted({p["file"] for p in plan if p["kind"] == "video"}):
        c = full_crop(v)
        b = brand_trim(v)
        if b.get("strength"):
            print(f"  branding x{b['strength']:.0f} on {os.path.basename(v)[:12]} "
                  f"-> crop {c}", flush=True)

    fails = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, ok, info in ex.map(render_shot, plan):
            if not ok:
                fails.append(i); print(f"  shot {i} FAIL {info[:100]}", flush=True)
    print(f"built {len(plan)-len(fails)}/{len(plan)}", flush=True)

    # ---- 3. final mix: voice + bed + section hits ----
    hits = [{"at": 0.4, "kind": "hit"}]
    for p in pins:
        hits.append({"at": p["at"], "kind": "hit"})
    for b in beats:
        if b["beat_i"] in (9, 12) and b["sub"] == 0:
            hits.append({"at": b["start"], "kind": "whoosh"})
    mixed = AD.final_mix(voice, vdur, f"{OUT}/mix.m4a", hits=hits)
    print(f"mix: bed + {len(hits)} hits, sidechain-ducked", flush=True)

    lst = f"{OUT}/body.txt"
    with io.open(lst, "w", encoding="utf-8") as f:
        for p in plan:
            fp = f"{OUT}/v{p['i']:03d}.mp4"
            if os.path.exists(fp):
                f.write(f"file '{fp}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", f"{OUT}/body_v.mp4"], check=True)
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",f"{OUT}/body_v.mp4","-i",mixed,
        "-map","0:v","-map","1:a","-c:v","libx264","-preset","medium","-crf","19",
        "-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-ar","48000","-ac","2","-shortest",
        f"{OUT}/body_full.mp4"], check=True)
    intro = build_intro()
    print("intro:", "ok" if intro else "FAILED", flush=True)
    final = f"{HERE}/SAMPLE_AUDIO.mp4"
    cl = f"{OUT}/final.txt"
    with io.open(cl,"w",encoding="utf-8") as f:
        if intro:
            f.write("file '" + intro + "'\n")
        f.write("file '" + OUT + "/body_full.mp4'\n")
    r = subprocess.run(["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0","-i",cl,
        "-c:v","libx264","-preset","medium","-crf","19","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k","-movflags","+faststart", final], capture_output=True, text=True)
    if r.returncode:
        print("FINAL FAIL:", r.stderr[-400:]); return
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nk=1:nw=1", final], capture_output=True, text=True).stdout.strip()
    print(f"DONE: {final}  duration {d}")


main()
