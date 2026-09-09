#!/usr/bin/env python3
"""Build the Tyson-Spinks documentary (7:00) from the shared library.

Improvements over the first cut, all of them causes of specific complaints:
  * beats come from TTS word timings -> clips land on exact words (was: hand-mapped Whisper)
  * retrieval scoring fixed (bm25 was inverted, so every pick was a near-miss)
  * PIL typography cards (title / lower-third / stat) instead of drawtext boxes
  * per-shot slow push-in so static archival frames still move
  * grade + film grain screen-blended in RGB, white flash on section breaks
"""

import sys, os, json, io, subprocess, re
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, f"{ROOT}/CODE")
os.environ["CDEV_LIBRARY_ROOT"] = f"{ROOT}/_tyson/library"
import catalog_db
from typography import title_card, lower_third, stat_card

# Repo root, derived from THIS file. Never hard-code an absolute path: a machine change (or a
# different drive letter) silently sends every read and write somewhere else. One earlier build
# wrote 719 files into the wrong library for exactly this reason, and the same mistake was already
# sitting in two other files at the time.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

HERE = f"{ROOT}/_spinks"
W, H, FPS = 1920, 1080, 30
GRAIN = f"{ROOT}/_tyson/fx/grain.mp4"
SHOTS = f"{HERE}/shots"; CARDS = f"{HERE}/cards"
for d in (SHOTS, CARDS): os.makedirs(d, exist_ok=True)
T, S = "ENT_TYSON", "ENT_SPINKS"
GRADE = "eq=contrast=1.20:saturation=0.58:brightness=-0.015,unsharp=5:5:0.30"

# beat index -> (query override | None, entity | None, overlay spec | None, style)
# overlay: ("title", main, sub) | ("lower", name, detail) | ("stat", value, label)
OV = {
 0:  ("boxing arena wide crowd before the fight", None, None, "flash"),
 2:  ("two heavyweight boxers facing off in the ring", None, None, ""),
 3:  ("Michael Spinks boxer standing in the ring", S, ("lower","Michael Spinks","31-0  ·  undefeated"), ""),
 4:  (None, None, ("stat","31-0","undefeated"), "card"),
 5:  ("boxer landing punches on Larry Holmes", None, None, ""),
 6:  ("Michael Spinks confident boxer portrait", S, None, ""),
 7:  ("boxer standing tall unbeaten in the ring", S, None, ""),
 9:  (None, None, ("title","JUNE 27, 1988","Atlantic City"), "card"),
 10: ("Mike Tyson menacing intense stare", T, None, "flash"),
 11: ("Mike Tyson champion belt celebration", T, ("lower","Mike Tyson","34-0  ·  30 knockouts"), ""),
 12: (None, None, ("stat","34-0","thirty knockouts"), "card"),
 13: ("Mike Tyson knockout opponent falls to the canvas", T, None, ""),
 14: ("boxer knocked down referee counting", None, None, ""),
 15: ("Mike Tyson devastating punch knockout", T, None, ""),
 19: ("Mike Tyson serious close up face", T, None, ""),
 20: ("Mike Tyson intense stare into camera", T, None, "slow"),
 24: ("two boxers face to face before the bell", None, None, ""),
 32: ("boxing bell rings round begins", None, None, "flash"),
 33: ("Mike Tyson advancing forward aggressive", T, None, ""),
 34: ("Mike Tyson stalking his opponent", T, None, ""),
 47: ("boxer drops to one knee knocked down", S, None, "slow"),
 49: ("boxer down on the canvas knocked down", S, ("lower","First knockdown","of his career"), ""),
 53: ("referee looks into the fighter's eyes", None, None, ""),
}

def clean_query(text: str) -> str:
    t = re.sub(r"[^A-Za-z0-9 ']", " ", text)
    stop = {"the","a","an","and","was","were","that","this","had","has","have","to","of","in",
            "it","he","his","him","for","but","not","on","at","as","is","be","been","would",
            "could","what","who","them","they","there","which","with","about","more","most",
            "than","then","from","just","only","even","still","almost","every","one","two"}
    ws = [w for w in t.split() if w.lower() not in stop and len(w) > 2]
    return " ".join(ws[:9]) or text[:60]

def objpath(c, a):
    sha = c._asset_object_sha(a)
    r = c.cx.execute("SELECT rel_path FROM objects WHERE sha256=?", (sha,)).fetchone()
    return os.path.join(os.environ["CDEV_LIBRARY_ROOT"], r["rel_path"]).replace("\\","/") if r else None

def assign():
    c = catalog_db.Catalog()
    beats = json.load(io.open(f"{HERE}/beats.json", encoding="utf-8"))
    # GAP-INCLUSIVE durations: a beat's shot must hold until the NEXT beat starts, otherwise the
    # pauses between spoken lines have no picture and the video ends short of the audio.
    audio_end = float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=nk=1:nw=1", f"{HERE}/vo/voiceover.mp3"],
        capture_output=True, text=True).stdout.strip())
    for k, b in enumerate(beats):
        nxt = beats[k+1]["start"] if k+1 < len(beats) else audio_end
        lo = 0.0 if k == 0 else b["start"]
        b["dur"] = round(max(1.0, nxt - lo), 2)

    used, out = [], []
    for b in beats:
        i, dur = b["i"], b["dur"]
        q_ov, ent, overlay, style = OV.get(i, (None, None, None, ""))
        rec = {"i": i, "dur": dur, "style": style, "text": b["text"][:90]}
        if overlay:
            kind = overlay[0]
            p = f"{CARDS}/c{i:03d}.png"
            if kind == "title":  title_card(overlay[1], overlay[2], p)
            elif kind == "lower": lower_third(overlay[1], overlay[2], p)
            else:                 stat_card(overlay[1], overlay[2], p)
            rec["overlay"] = p; rec["overlay_kind"] = kind
        if style == "card":
            rec["kind"] = "card"; out.append(rec); continue
        q = q_ov or clean_query(b["text"])
        cands = c.search(query_text=q, type="video", required_any=[ent] if ent else None, top_k=40)
        if not cands: cands = c.search(query_text=q, type="video", top_k=40)
        pick = next((x for x in cands if x["asset_id"] not in used[-16:]), cands[0] if cands else None)
        if not pick:
            rec["kind"] = "card"; rec.setdefault("overlay", None); out.append(rec); continue
        used.append(pick["asset_id"]); c.mark_used(pick["asset_id"], channel="spinks")
        seg = (pick["end_ms"] - pick["start_ms"]) / 1000.0
        need = min(dur * (1.6 if style == "slow" else 1.0) + 0.3, 7.0)   # <=7s cap
        off = max(0.0, min(seg - need, (seg - need) / 2))
        rec.update({"kind":"video","file":objpath(c,pick),"in":round(pick["start_ms"]/1000+off,2),
                    "asset":pick["asset_id"],"desc":pick["description"][:70],"query":q})
        out.append(rec)
    json.dump(out, io.open(f"{HERE}/assign.json","w",encoding="utf-8"), indent=1, ensure_ascii=False)
    return out

def build(item):
    i, d = item["i"], item["dur"]
    out = f"{SHOTS}/s{i:03d}.mp4"
    ov = item.get("overlay")
    if item["kind"] == "card":
        inputs = ["-f","lavfi","-i",f"color=c=0x0a0a0c:s={W}x{H}:r={FPS}:d={d}",
                  "-stream_loop","-1","-t",f"{d}","-i",GRAIN]
        fc = (f"[0:v]format=gbrp[b];[1:v]scale={W}:{H},format=gbrp[g];"
              f"[b][g]blend=all_mode=screen:all_opacity=0.22,format=yuv420p[bg]")
        if ov:
            inputs += ["-loop","1","-t",f"{d}","-i",ov]
            fc += f";[2:v]format=rgba,fade=t=in:st=0:d=0.5:alpha=1[o];[bg][o]overlay=0:0[v]"
        else:
            fc += ";[bg]null[v]"
    else:
        speed = "setpts=1.6*PTS," if item["style"]=="slow" else ""
        grab = min(d*(1.6 if item["style"]=="slow" else 1.0)+0.25, 7.0)
        flash = ",fade=t=in:st=0:d=0.10:color=white" if item["style"]=="flash" else ""
        n = int((d+0.2)*FPS)
        inputs = ["-ss",f"{item['in']:.2f}","-t",f"{grab:.2f}","-i",item["file"],
                  "-stream_loop","-1","-t",f"{grab:.2f}","-i",GRAIN]
        # zoompan REMOVED: it truncates its crop origin (and, in a zoom, the crop height) to whole
        # pixels, so a smooth push arrives as uneven steps. Measured on our own stills: 0.352px
        # per-frame shake vs 0.001px with the subpixel `perspective` path in build_core.ken_burns.
        import sys as _s; _s.path.insert(0, f"{ROOT}/CODE")
        import build_core as _BC
        _kb, _n = _BC.ken_burns(W, H, FPS, d, index=i)
        fc = (f"[0:v]scale={W*2}:-2,{_kb},"
              f"{speed}{GRADE}{flash},setsar=1,format=gbrp[b];"
              f"[1:v]scale={W}:{H},format=gbrp[g];"
              f"[b][g]blend=all_mode=screen:all_opacity=0.24,format=yuv420p[bg]")
        if ov:
            inputs += ["-loop","1","-t",f"{d}","-i",ov]
            fc += f";[2:v]format=rgba,fade=t=in:st=0.15:d=0.4:alpha=1[o];[bg][o]overlay=0:0[v]"
        else:
            fc += ";[bg]null[v]"
    cmd = (["ffmpeg","-y","-loglevel","error"] + inputs +
           ["-filter_complex",fc,"-map","[v]","-t",f"{d:.2f}","-r",str(FPS),
            "-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",out])
    r = subprocess.run(cmd, capture_output=True, text=True)
    return (i, r.returncode == 0, r.stderr[-160:] if r.returncode else out)

def main():
    plan = assign()
    nv = sum(1 for p in plan if p["kind"]=="video"); nc = len(plan)-nv
    no = sum(1 for p in plan if p.get("overlay"))
    print(f"assigned {len(plan)} beats: {nv} footage, {nc} cards, {no} text overlays", flush=True)
    fails=[]
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i,ok,info in ex.map(build, plan):
            if not ok: fails.append(i); print(f"  shot {i} FAIL {info[:110]}", flush=True)
    print(f"built {len(plan)-len(fails)}/{len(plan)}", flush=True)
    lst=f"{HERE}/concat.txt"
    with io.open(lst,"w",encoding="utf-8") as f:
        for p in plan:
            fp=f"{SHOTS}/s{p['i']:03d}.mp4"
            if os.path.exists(fp): f.write(f"file '{fp}'\n")
    out=f"{HERE}/TYSON_SPINKS.mp4"
    r=subprocess.run(["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0","-i",lst,
        "-i",f"{HERE}/vo/voiceover.mp3","-map","0:v","-map","1:a","-c:v","libx264",
        "-preset","medium","-crf","19","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",
        "-shortest","-movflags","+faststart",out],capture_output=True,text=True)
    if r.returncode: print("CONCAT FAIL:",r.stderr[-400:]); return
    dur=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of",
        "default=nk=1:nw=1",out],capture_output=True,text=True).stdout.strip()
    print(f"DONE: {out}  duration {dur}")

main()
