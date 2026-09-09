#!/usr/bin/env python3
"""build.py — assemble the Quadrasteer sample (cars niche, ~3 min = beats 0-26).

This is the SAME engine as the boxing build, driven by a different STYLE PROFILE. Nothing about the
retrieval, gating, or QC changed; what changed is the look, and that is the point — proving one
system serves many niches instead of one hand-built pipeline per channel.

What the cars profile changes, and why (all from analysing the reference channel):
  GRADE      near-natural, not the dark sports-doc grade. Archival car footage is supposed to look
             like archival car footage, not a thriller.
  TYPOGRAPHY the 'clean' style: white Arial, almost no tracking, a data-green accent for numbers —
             the opposite of the heavy red Impact a fight doc wants.
  ASPECT     4:3 and low-res archival is KEPT, blurred-filled instead of pillarboxed, because that
             early-2000s promo look is the aesthetic here (boxing threw sub-HD away; this niche
             would be throwing away its best material).
  STILLS     first-class citizens with a slow Ken Burns push — the reference channel is ~45% stills.
  AUDIO      no punch-ins (a calm explainer, not a fight), a lighter bed, and soft whooshes only on
             the two structural cards instead of impact hits.
"""
import sys, os, io, json, math, subprocess, re, time
from concurrent.futures import ThreadPoolExecutor

# Repo root, derived from THIS file. Never hard-code an absolute path: a machine change (or a
# different drive letter) silently sends every read and write somewhere else. One earlier build
# wrote 719 files into the wrong library for exactly this reason, and the same mistake was already
# sitting in two other files at the time.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

HERE = f"{ROOT}/_quadrasteer"
sys.path.insert(0, f"{ROOT}/CODE")
os.environ["CDEV_LIBRARY_ROOT"] = f"{HERE}/library"
import catalog_db
import build_core as BC
import frame_quality as FQ
import audio_design as AD
from typography import title_card, stat_card

# 720p: all three competitor videos ship 1280x720. 1080p was 2.2x the pixels per
# frame for a resolution the reference channels do not even use.
W, H, FPS = 1280, 720, 30
OUT = f"{HERE}/sa"; os.makedirs(OUT, exist_ok=True)
NARR = f"{HERE}/vo/voiceover.mp3"
BODY_END = 187.3       # end of beat 26 ("It actually worked.") — a complete first act
STYLE = "clean"
ST = BC.style(STYLE)
MAX_SHOT = ST["max_shot"]   # per-niche cut rate, measured from the reference channel
SRC_CACHE = f"{OUT}/source_cache.json"
GRADE = "eq=contrast=1.05:saturation=1.06:brightness=0.008,unsharp=5:5:0.5:5:5:0.0"


def grade(v, at):
    return BC.grade(v, at, ST, SRC_CACHE)

# beat -> (query | None, card | None, style). card = ("title", main, sub) | ("stat", value, label)
OV = {
# Every query is deliberately DISTINCT. The first version reused near-identical phrasings — four
# beats all asked for a "cone slalom course" — so bm25 handed the same asset back every time and one
# clip won four different beats. Distinct wording is what lets a big library actually be used.
 0:  ("GMC Sierra pickup truck driving highway front", None, ""),
 1:  ("Chevrolet GMC dealership lot trucks for sale", None, ""),
 2:  ("hands turning steering wheel truck interior driver", None, ""),
 3:  ("rear wheels turning opposite four wheel steering close up", None, ""),
 4:  ("pickup truck driving highway speed stable", None, ""),
 5:  ("pickup truck hooking up towing trailer hitch", None, ""),
 6:  (None, ("title", "Quadrasteer", ""), "whoosh"),
 7:  (None, ("stat", "37 ft", "turning circle  ·  was 47 ft"), "whoosh"),
 8:  ("GMC Sierra Denali pickup truck exterior walkaround", None, ""),
 9:  ("pickup truck tight turn parking maneuver cones", None, ""),
 10: ("truck window sticker price dealership showroom", None, ""),
 11: ("full size pickup trucks lineup parked 2002", None, ""),
 12: ("pickup truck towing boat camper horse trailer", None, ""),
 13: ("aerial suburban street houses pickup truck driveway", None, ""),
 14: ("long wheelbase pickup truck narrow space", None, ""),
 15: ("pickup truck backing up parking lot reverse", None, ""),
 16: ("truck multi point turn figure eight maneuver", None, ""),
 17: ("Delphi engineering rear steering unit mechanism", None, ""),
 18: ("rear axle steering actuator underneath truck", None, ""),
 19: ("rear wheel turning left right steering demonstration", None, ""),
 20: ("truck short wheelbase tight turning circle", None, ""),
 21: ("pickup truck rotating around corner turn", None, ""),
 22: ("pickup truck lane change highway same direction", None, ""),
 23: ("pickup truck towing trailer highway stable", None, ""),
 24: ("truck dashboard mode selector switch controls", None, ""),
 25: ("steering wheel dashboard interior conventional steering", None, ""),
 26: ("GMC Sierra pickup truck driving away confident", None, ""),
}
STOP = set("the a an and was were that this had has have to of in it he his him for but not on at as "
           "is be been would could what who them they there which with about more most than then "
           "from just only even still almost every one two too its into your you can".split())
_probe, _fc = {}, {}


def dims(v):
    return BC.src_dims(v)


def gate_ok(v, a, b):
    return BC.gate_ok(v, a, b)


def objpath(c, a):
    return BC.objpath(c, a)


def vfit(v, at=0.0):
    """Take [0:v], fill 1920x1080 without stretching, output [bg]. 16:9-ish sources cover-crop;
    4:3/other archival gets a blurred fill of itself behind a fit-to-frame foreground, which is how
    a modern archival doc presents old promo footage instead of hard pillarbox bars. Uses unique
    internal labels so it never collides with the caller's [bg]/[fg]."""
    w, h = dims(v)
    ar = w / max(1, h)
    gr = grade(v, at)
    ck = BC.crop_expr(v, SRC_CACHE)   # pillarbox + ANOTHER CHANNEL'S branding
    if 1.62 <= ar <= 1.85:
        return (f"[0:v]{ck}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"{gr},format=yuv420p[bg]")
    return (f"[0:v]{ck}split=2[vfa][vfb];"
            f"[vfa]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=20:2,eq=brightness=-0.04:saturation=0.7[vfbg];"
            f"[vfb]scale={W}:{H}:force_original_aspect_ratio=decrease,{gr}[vffg];"
            f"[vfbg][vffg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[bg]")


CARD_BG = [("0x3c414c", "0x282c34", 0, 0, W, H),          # diagonal, cool grey
           ("0x2f3a44", "0x1d242c", W, 0, 0, H)]         # opposite diagonal, deeper blue-grey


def clean_bg(d, seed=0):
    """A calm CHARCOAL base for cards, not pure black. Two reasons: a car explainer's title cards
    read as designed rather than as a dropout, and a near-black card trips the dark-frame QC that
    exists to catch missing footage — the same rule, correctly, does not want 9 seconds of black.

    Each card gets a DIFFERENT background. When every card shared one gradient, the repeat detector
    correctly reported the title card and the stat card six seconds later as the same picture: at
    hash resolution they were, because the text is small and the background is everything. Two
    identical-looking cards in a row is a real visual flaw, not just a QC artefact."""
    c0, c1, x0, y0, x1, y1 = CARD_BG[seed % len(CARD_BG)]
    return (f"gradients=s={W}x{H}:r={FPS}:d={d}:c0={c0}:c1={c1}:"
            f"x0={x0}:y0={y0}:x1={x1}:y1={y1}", None)




def render(item):
    i, d = item["i"], round(item["dur"], 2)
    out = f"{OUT}/v{i:03d}.mp4"
    ov = item.get("overlay")
    if item["kind"] == "card":
        col, _ = clean_bg(d, item.get("card_n", 0))
        fc = f"[0:v]format=yuv420p[bg]"
        inp = ["-f", "lavfi", "-t", f"{d}", "-i", col]
        nxt = 1
    elif item["kind"] == "image":
        # Ken Burns via build_core: subpixel `perspective`, not `zoompan`. Measured shake on our
        # own stills went from 0.35px per frame to 0.001px. Exposure is still lifted per image —
        # scanned brochure pages are often dim and a dark still trips the near-black check.
        try:
            from PIL import Image as _I
            import numpy as _np
            y = float(_np.asarray(_I.open(item["file"]).convert("L").resize((160, 90))).mean())
        except Exception:
            y = 112.0
        y = min(240.0, max(12.0, y))
        g = round(max(0.85, min(1.9, 1.0 + (math.log(y / 255.0) / math.log(112.0 / 255.0) - 1.0) * 0.8)), 3)
        kb, n = BC.ken_burns(W, H, FPS, d, index=i)
        fc = f"[0:v]{kb},eq=gamma={g},{GRADE},format=yuv420p[bg]"
        inp = ["-loop", "1", "-framerate", str(FPS), "-t", f"{d}", "-i", item["file"]]
        nxt = 1
    else:
        inp = ["-ss", f"{item['in']:.2f}", "-t", f"{min(d+0.3,7.0):.2f}", "-i", item["file"]]
        fc = vfit(item["file"], item["in"])   # already [0:v] ... [bg]
        nxt = 1
    if ov:
        inp += ["-loop", "1", "-t", f"{d}", "-i", ov]
        fc += (f";[{nxt}:v]scale={W}:{H},format=rgba,fade=t=in:st=0.25:d=0.5:alpha=1[o];[bg][o]overlay=0:0[vv]")
    else:
        fc += ";[bg]null[vv]"
    # gentle fades between every shot so cuts breathe (the reference never hard-cuts on stills)
    fc += f";[vv]fade=t=in:st=0:d=0.18,fade=t=out:st={max(0.1,d-0.18):.2f}:d=0.18[vout]"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + inp +
        ["-filter_complex", fc, "-map", "[vout]", "-t", f"{d:.2f}", "-r", str(FPS),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", out],
        capture_output=True, text=True)
    return (i, r.returncode == 0, r.stderr[-160:] if r.returncode else out)


# Subjects that are simply not this film. The Suzuki Jimny in a desert reached the last cut because
# "driving on a road" is a strong text match and nothing checked WHAT was driving.
DENY = ("jimny", "motorcycle", "motorbike", "scooter", "bicycle", "longhorn", "cattle")
# Terms that prove a clip really is a full-size truck, for beats that ask for one.
TRUCK = ("truck", "pickup", "silverado", "sierra", "gmc", "chevrolet", "chevy", "suburban",
         "yukon", "denali", "trailer", "towing", "tow ", "ute", "f-150", "ram ")


def relevant(desc: str, q: str) -> bool:
    """Cheap subject check on top of bm25 relevance.

    bm25 ranks by word overlap, so a clip of a small SUV on a dirt road scores well against
    "pickup truck driving road" — every word matched except the one that mattered. This asserts the
    SUBJECT, not just the vocabulary."""
    d = (desc or "").lower()
    if any(w in d for w in DENY):
        return False
    if any(t in q.lower() for t in ("truck", "pickup", "sierra", "silverado", "gmc")):
        return any(t in d for t in TRUCK)
    return True


STILLS_TARGET = 0.4   # measured from the reference channel (competitor cars = 44% stills)
_MIX = {"img": 0, "vid": 0}
SEEN_HASHES = []


def pick_query(c, q, used):
    tot = _MIX["img"] + _MIX["vid"]
    want = "image" if (tot and _MIX["img"] / tot < STILLS_TARGET) else "video"
    r = BC.pick(c, q, used, seen_hashes=SEEN_HASHES, prefer=want, deny=DENY, require=TRUCK,
                   require_when=("truck", "pickup", "sierra", "silverado", "gmc"))
    if r[1]:
        _MIX["img" if r[1] == "image" else "vid"] += 1
    return r


_T0 = [time.time()]


def lap(label):
    now = time.time()
    print(f"  [T] {label:<28} {now-_T0[0]:7.1f}s", flush=True)
    _T0[0] = now


def main():
    c = catalog_db.Catalog()
    beats = json.load(io.open(f"{HERE}/beats.json", encoding="utf-8"))
    BC.assert_alignment(beats)          # fail closed on misaligned narration
    for k, b in enumerate(beats):
        nxt = beats[k+1]["start"] if k+1 < len(beats) else BODY_END
        b["dur"] = round(max(1.0, nxt - (0.0 if k == 0 else b["start"])), 2)
    beats = [b for b in beats if b["start"] < BODY_END and b["i"] in OV]

    # split long beats into <=MAX_SHOT slots (same anti-slideshow rule as boxing)
    slots = []
    for b in beats:
        n = max(1, int(math.ceil(b["dur"] / MAX_SHOT)))
        per = b["dur"] / n
        for j in range(n):
            slots.append({**b, "dur": round(per, 2), "start": b["start"] + j * per,
                          "beat_i": b["i"], "sub": j})
    print(f"{len(beats)} beats -> {len(slots)} slots (avg {sum(s['dur'] for s in slots)/len(slots):.1f}s)",
          flush=True)

    # Pre-gate every plausible candidate in parallel; the pick loop below then only does lookups.
    qs = [v[0] for v in OV.values() if v[0]]
    cands = BC.collect_candidates(c, qs, per_query=8)
    lap("setup+search")
    print(f"pre-gating {len(cands)} candidate windows...", flush=True)
    BC.warm_gates(cands, workers=6)
    lap("parallel pre-gate")

    used, plan, starved = set(), [], 0
    for si, b in enumerate(slots):
        q_ov, card, style = OV.get(b["beat_i"], (None, None, ""))
        rec = {"i": si, "dur": b["dur"], "style": style, "beat_i": b["beat_i"]}
        if card and b["sub"] == 0:
            p = f"{OUT}/card{b['beat_i']:03d}.png"
            (title_card if card[0] == "title" else stat_card)(card[1], card[2], p,
                                                              style=STYLE, size_px=(W, H))
            rec.update({"kind": "card", "overlay": None, "cardimg": p,
                        "card_n": sum(1 for x in plan if x.get("kind") == "card")})
            # a card shows the graphic centered on the dark base
            rec["overlay"] = p
            plan.append(rec); continue
        q = q_ov or " ".join([w for w in re.findall(r"[A-Za-z']+", b["text"])
                              if w.lower() not in STOP and len(w) > 2][:8])
        pick, typ, f = pick_query(c, q, used)
        if pick is None:
            # POOL EXHAUSTED for this beat. Fail loudly rather than re-using a clip: a repeat is the
            # defect a viewer notices first, and a silent one hides the real problem (small library).
            starved += 1
            rec["kind"] = "card"; rec["overlay"] = None; plan.append(rec); continue
        used.add(pick["asset_id"])
        rec["kind"] = typ; rec["file"] = f
        if typ == "video":
            seg = (pick["end_ms"] - pick["start_ms"]) / 1000.0
            need = min(b["dur"] + 0.3, 7.0)
            off = max(0.0, min(seg - need, (seg - need) / 2))
            rec["in"] = round(pick["start_ms"] / 1000 + off, 2)
        plan.append(rec)

    lap("pick loop")
    nv = sum(1 for p in plan if p["kind"] == "video")
    ni = sum(1 for p in plan if p["kind"] == "image")
    nc = sum(1 for p in plan if p["kind"] == "card")
    print(f"plan: {nv} video + {ni} stills + {nc} cards | {len(used)} UNIQUE assets for "
          f"{len(slots)} slots", flush=True)
    if starved:
        print(f"  !! LIBRARY TOO SMALL: {starved} slots had no unused on-topic clip left. "
              f"Source more footage — do not ship this.", flush=True)

    BC.warm([p["file"] for p in plan if p.get("file")], SRC_CACHE)
    lap("branding warm")
    for v in sorted({p["file"] for p in plan if p.get("file")}):
        b = BC.brand_trim(v, SRC_CACHE)
        if b.get("strength"):
            print(f"  branding x{b['strength']:.0f} cropped on {os.path.basename(v)[:14]}", flush=True)

    fails = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, ok, info in ex.map(render, plan):
            if not ok:
                fails.append(i); print(f"  slot {i} FAIL {info[:110]}", flush=True)
    print(f"built {len(plan)-len(fails)}/{len(plan)}", flush=True)
    lap("RENDER 60 shots")

    # ---- audio: narration + light bed + soft whooshes on the two cards ----
    import shutil
    voice = f"{OUT}/voice.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", NARR, "-t", f"{BODY_END}",
                    "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", voice], check=True)
    hits = []
    for b in slots:
        _, card, _ = OV.get(b["beat_i"], (None, None, ""))
        if card and b["sub"] == 0:
            hits.append({"at": b["start"], "kind": "whoosh"})
    mixed = AD.final_mix(voice, BODY_END, f"{OUT}/mix.m4a", hits=hits, bed_db=-7.0, hit_db=-12.0)
    print(f"mix: light bed + {len(hits)} soft whooshes", flush=True)
    lap("audio mix")

    lst = f"{OUT}/body.txt"
    with io.open(lst, "w", encoding="utf-8") as f:
        for p in plan:
            fp = f"{OUT}/v{p['i']:03d}.mp4"
            if os.path.exists(fp):
                f.write(f"file '{fp}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", f"{OUT}/body_v.mp4"], check=True)
    final = f"{HERE}/QUADRASTEER_SAMPLE.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{OUT}/body_v.mp4", "-i", mixed,
        # -c:v copy: the concatenated video is already the finished picture at the settings we
        # chose. Re-encoding it here changed nothing and cost 96 seconds of a 14-minute build.
        "-map", "0:v", "-map", "1:a", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-shortest", "-movflags", "+faststart", final], check=True)
    lap("concat + final mux")
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
        "default=nk=1:nw=1", final], capture_output=True, text=True).stdout.strip()
    print(f"DONE: {final}  duration {dur}", flush=True)


main()
