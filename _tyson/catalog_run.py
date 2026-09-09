#!/usr/bin/env python3
"""Catalog the locally-segmented Tyson sources with gemini-2.5-flash via the relay.
Cheap-first already done (HD + histogram cuts + motion) — we only pay for usable shots."""

import sys, os, json, base64, subprocess, tempfile, re
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, f"{ROOT}/CODE")
os.environ["CDEV_LIBRARY_ROOT"] = f"{ROOT}/_tyson/library"
import config, catalog_db, urllib.request

# Repo root, derived from THIS file. Never hard-code an absolute path: a machine change (or a
# different drive letter) silently sends every read and write somewhere else. One earlier build
# wrote 719 files into the wrong library for exactly this reason, and the same mistake was already
# sitting in two other files at the time.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

RAW = f"{ROOT}/_tyson/raw/"
KEY, BASE, MODEL = config.GEMINI_RELAY_KEY, config.GEMINI_RELAY_BASE, "gemini-2.5-flash"

SRC_META = {
    "k5PXszeZ05c.mp4": ("SRC_GOLOTA_FIGHT", "Tyson vs Golota, 20 Oct 2000",
                        ["COL_PROJECT_TYSON-GOLOTA", "COL_DOMAIN_BOXING"], 1),
    "1ee-NU7Lp5Y.mp4": ("SRC_TYSON_KOS", "Tyson best knockouts 1985-1990",
                        ["COL_ENTITY_TYSON", "COL_DOMAIN_BOXING"], 1),
    "sGxhMI-IEGs.mp4": ("SRC_GOLOTA_KOS", "Golota top knockouts",
                        ["COL_ENTITY_GOLOTA", "COL_DOMAIN_BOXING"], 1),
    "3yYRQIQN8jQ.mp4": ("SRC_RIBALTA", "Tyson vs Ribalta knockout",
                        ["COL_ENTITY_TYSON", "COL_DOMAIN_BOXING"], 5),   # every 5th shot
    "0vnOfawuQF4.mp4": ("SRC_MCNEELEY", "Tyson vs McNeeley",
                        ["COL_ENTITY_TYSON", "COL_DOMAIN_BOXING"], 1),
}

PROMPT = ("You are cataloging archival boxing documentary footage. Look at this frame and return "
          "ONLY JSON: {"
          '"description":"1 literal line — who/what is on screen and what is happening",'
          '"keywords":["8-14 words: subject, shot-type, camera, light/mood, colour, use"],'
          '"shot":"wide|medium|close-up|extreme close-up",'
          '"camera":"static|pan|tilt|push|handheld|aerial",'
          '"people":["ONLY boxers/people clearly VISIBLE — e.g. Mike Tyson, Andrew Golota, referee, '
          'crowd. [] if none identifiable"],'
          '"serves":["what a narrator could say over this — e.g. the fall, menace, the crowd waits, '
          'the moment it ended"],'
          '"objects":[things],"places":[setting],'
          '"talking_head":true_if_a_person_speaks_straight_to_camera_or_is_a_studio_pundit,'
          '"quality":"low|medium|high","clean_status":"clean|fixable|unusable",'
          '"era":"1980s|1990s|2000s|unknown","match_conf":0.0_to_1.0}. '
          "clean_status='fixable' if a broadcast score-bug/logo sits in a corner; 'unusable' only if "
          "text covers the fighters. Be honest — do not name a boxer you cannot actually see.")


def frame(path, t):
    fp = tempfile.mktemp(suffix=".jpg")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", path,
                    "-frames:v", "1", "-vf", "scale=720:-2", fp], capture_output=True)
    if os.path.exists(fp):
        b = open(fp, "rb").read(); os.remove(fp); return b
    return None


def describe(img):
    body = {"model": MODEL, "max_tokens": 420, "messages": [{"role": "user", "content": [
        {"type": "text", "text": PROMPT},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}}]}]}
    req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=120))
    m = re.search(r"\{.*\}", d["choices"][0]["message"]["content"], re.S)
    return json.loads(m.group(0)) if m else {}


def job(args):
    fname, seg, idx = args
    path = RAW + fname
    img = frame(path, seg["start"] + (seg["end"] - seg["start"]) * 0.45)
    if not img:
        return None
    try:
        meta = describe(img)
    except Exception as e:
        return {"err": str(e)[:60], "f": fname, "i": idx}
    return {"f": fname, "seg": seg, "meta": meta, "i": idx}


def main():
    local = json.load(open(f"{ROOT}/_tyson/local_segments.json"))
    tasks = []
    for fname, (sid, title, cols, step) in SRC_META.items():
        segs = [s for s in local[fname]["segments"] if s["usable"]]
        for i, s in enumerate(segs):
            if i % step == 0:
                tasks.append((fname, s, i))
    print(f"cataloging {len(tasks)} segments with {MODEL}", flush=True)

    c = catalog_db.Catalog()
    for eid, kind, name, al in [
            ("ENT_TYSON", "person", "Mike Tyson", ["Tyson", "Iron Mike", "Mike"]),
            ("ENT_GOLOTA", "person", "Andrew Golota", ["Golota", "Galota", "Andrew Golota"])]:
        c.upsert_entity(eid, kind, name, al)
    for cid, layer in [("COL_PROJECT_TYSON-GOLOTA", "PROJECT"), ("COL_ENTITY_TYSON", "ENTITY"),
                       ("COL_ENTITY_GOLOTA", "ENTITY"), ("COL_DOMAIN_BOXING", "DOMAIN"),
                       ("COL_COMMON", "COMMON")]:
        c.ensure_collection(cid, layer)
    for fname, (sid, title, cols, step) in SRC_META.items():
        obj = c.ingest_file(RAW + fname)
        c.add_source(sid, f"youtube:{fname[:-4]}", "video", content_hash=obj["sha256"],
                     channel="archive", meta={"title": title})

    done = err = skipped = 0
    with ThreadPoolExecutor(max_workers=7) as ex:
        futs = [ex.submit(job, t) for t in tasks]
        for fu in as_completed(futs):
            r = fu.result()
            if not r or r.get("err"):
                err += 1; continue
            fname, seg, meta = r["f"], r["seg"], r["meta"]
            sid, title, cols, step = SRC_META[fname]
            if meta.get("talking_head") or meta.get("clean_status") == "unusable":
                skipped += 1; continue
            people = meta.get("people", []) or []
            ents = []
            blob = " ".join(people).lower()
            if "tyson" in blob or "mike" in blob:
                ents.append("ENT_TYSON")
            if "golota" in blob or "galota" in blob:
                ents.append("ENT_GOLOTA")
            era = meta.get("era", "unknown")
            ef, et = (None, None)
            if era == "1980s": ef, et = 1980, 1989
            elif era == "1990s": ef, et = 1990, 1999
            elif era == "2000s": ef, et = 2000, 2009
            aid = f"AST_{sid[4:12]}_{int(seg['start']*1000)}"
            ok = c.add_asset(aid, "video", source_id=sid,
                             start_ms=int(seg["start"] * 1000), end_ms=int(seg["end"] * 1000),
                             description=(meta.get("description") or "")[:300],
                             era_from=ef, era_to=et,
                             quality=meta.get("quality", "medium"),
                             clean_status=meta.get("clean_status", "clean"),
                             match_conf=float(meta.get("match_conf", 0.8) or 0.8),
                             review_status="needs_review", entities=ents,
                             collections=cols + (["COL_PROJECT_TYSON-GOLOTA"] if "TYSON" in sid or "GOLOTA" in sid else []),
                             catalog={"keywords": meta.get("keywords", []),
                                      "serves": meta.get("serves", []),
                                      "objects": meta.get("objects", []),
                                      "places": meta.get("places", []),
                                      "people": people, "shot": meta.get("shot", ""),
                                      "camera": meta.get("camera", ""),
                                      "motion": seg.get("motion"), "src_title": title,
                                      "model": MODEL})
            if ok:
                c.auto_approve(aid); done += 1
            if (done + err + skipped) % 25 == 0:
                print(f"  ...{done} cataloged, {skipped} gated, {err} err", flush=True)

    print(f"DONE: {done} cataloged, {skipped} gated out, {err} errors")
    print("STATS:", c.stats())


if __name__ == "__main__":
    main()
