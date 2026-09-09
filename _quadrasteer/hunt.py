#!/usr/bin/env python3
"""hunt.py — build the Quadrasteer (cars niche) library from scratch.

This is the real open-world test the whole project is about: unlike the boxing job, there is NO
pre-built library here. Everything is sourced cold, from free sources, and cataloged by the relay
vision model before anything can be retrieved.

Source mix is tuned to what the REFERENCE channel actually does (analysed from GreenHawkDrive):
~30% archival manufacturer promo, ~15% amateur walk-around b-roll, ~45% stills, the rest stock and
graphics. So the ladder here is deliberately NOT the boxing one:

  YOUTUBE   the entity-specific gold — the actual GM Quadrasteer TV commercials, the MotorWeek
            retro review, and owner demos where the rear wheels visibly turn. This footage exists
            nowhere else. Kept even when it is 4:3 and low-res, because that grainy early-2000s
            look IS the aesthetic of this niche (the strict HD/widescreen gate boxing used would
            throw away exactly the shots that make a car-failure documentary feel authentic).
  STOCK     Pexels/Pixabay ambience for the generic beats: a truck on a highway, a parking lot, a
            trailer being towed, hands on a wheel. Never the hero subject.
  STILLS    high-res photographs — the single biggest ingredient of the reference channel — badges,
            a Sierra Denali, a rear axle, given motion later with a slow push.

Every asset is cataloged by the relay (gemini-2.5-flash, openlux) so the library entry is honest
about what is on screen, and gated the same way everything else is.
"""
import sys, os, io, json, subprocess, time
from pathlib import Path

# Repo root, derived from THIS file. Never hard-code an absolute path: a machine change (or a
# different drive letter) silently sends every read and write somewhere else. One earlier build
# wrote 719 files into the wrong library for exactly this reason, and the same mistake was already
# sitting in two other files at the time.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

HERE = Path(f"{ROOT}/_quadrasteer")
sys.path.insert(0, f"{ROOT}/CODE")
os.environ["CDEV_LIBRARY_ROOT"] = str(HERE / "library")
# keys
for line in io.open(f"{ROOT}/keys.env", encoding="utf-8"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

import catalog_db, vision, yt_source, stock_source
import build_core as BC

RAW = HERE / "raw"; RAW.mkdir(parents=True, exist_ok=True)
CAP_SEG = 45           # max segments cataloged per source. Was 20 — a cost guard that
                       # directly starved the library: the richest sources (a 6-minute
                       # road test) had 40+ usable shots and we kept 20, then the cut
                       # repeated clips because there was nothing else to choose from.
TRIM_LONG = 420.0      # sources longer than this are trimmed to their middle TRIM_LONG seconds.
                       # Was 200 — which threw away ~90% of a 26-minute road test and was a real
                       # cause of the tiny library that forced clips to repeat.

# (video_id, label, era_from, era_to, is_archival) — archival = keep even if sub-HD/4:3
YT = [
    ("oMyeAyBqzzk", "2003 Silverado 1500 Quadrasteer TV commercial", 2003, 2003, True),
    ("7FAcEH3-Gio", "2003 GMC Sierra Denali Quadrasteer TV commercial", 2003, 2003, True),
    ("hYqJF6D5cp0", "GM introduction of the Silverado Quadrasteer system", 2002, 2003, True),
    ("OGuukdd-sMw", "MotorWeek retro review 2002 GMC Sierra Denali Quadrasteer", 2002, 2002, True),
    ("mCDfsRtXSQc", "Chevrolet Silverado GMC Quad-Steering demonstration", 2002, 2004, True),
    ("m2wYyfpAvK0", "owner demo of Quadrasteer rear wheels on a Sierra Denali", 2005, 2015, True),
    ("rzW12bC294w", "2002 Chevrolet Silverado Quadrasteer Commercial", 2002, 2005, True),
    ("Q0pbf4uNp3I", "2003 GMC Sierra Quadrasteer Commercial", 2002, 2005, True),
    ("UMTw_pS_3Kw", "2003 GMC Sierra 1500 Quadrasteer", 2002, 2005, True),
    ("moQPkLc2UdQ", "Quadristeer 2002 Yukon Rear Wheel Steering Parallel Parking", 2002, 2005, True),
    ("tC0XnS7kAo8", "2003 GMC Yukon XL Quadrasteer 4 wheel steering doing figure eights", 2002, 2005, True),
    ("tVnLJj3LO_w", "Silverado with Quad Steering.", 2002, 2005, True),
    ("KRDM2ViARI0", "2004 GMC Sierra Denali C3 Quadrasteer, Test the steering!!!", 2002, 2005, True),
    ("1yRypIGgX5c", "Quadrasteer In Action 2005 Gmc Sierra / 4 Wheel Steering", 2002, 2005, True),
    ("gwXIadxhQKE", "GM Delphi Quadrasteer independent control", 2002, 2005, True),
    ("OEVUTmaPpWg", "Sierra Denali Quadrasteer w/GoPro (4-Wheel Steering)", 2002, 2005, True),
    ("-AzJvRF-sK8", "2003 Yukon 4x4 QUADRASTEER", 2002, 2005, True),
    ("-yDOg7wUJ5k", "2002 Chevy Silverado HD Giants Commercial", 2002, 2005, True),
    ("C97eYCbCTKA", "2002 GMC Sierra SLT Quadrasteer Walkaround", 2002, 2005, True),
    ("Xc7ZWnlvfgg", "Insanely Rare! Full Walkaround of a Quadrasteer GMC Yukon XL", 2002, 2005, True),
    ("TASVJhT7FGU", "2004 GMC Sierra 2500 6.0 4x4 SLT Crew Quadrasteer Wheel Kinetics", 2002, 2005, True),
    ("eeiGj9ezLK8", "Quadrasteer POV And Maneuverability! Turns On A Dime!!!", 2002, 2005, True),
    ("WfNRa2Cilpk", "Introduction to the 03 1500hd Quadrasteer", 2002, 2005, True),
    ("jnJT_ZQkrPA", "GMC Quadrasteer (4 wheel steer) Repair", 2002, 2005, True),
    ("juqHNHQ3iHg", "Quadrasteer control module - inner workings - cut open", 2002, 2005, True),
    ("kI1d8yVV4XY", "Rear Axle Removal!  1999-2005 Silverado, Sierra, Tahoe, Suburban, ", 2002, 2005, True),
    ("sVCRg_wNqDQ", "TOWING WITH A QUADRASTEER YUKON", 2002, 2005, True),
    ("diWb0Mlb98Q", "TOWING A JOHN DEERE WITH THE QUADRASTEER YUKON", 2002, 2005, True),
    ("peJI3KLnXgI", "2002 GMC Sierra Denali 4WS Sport Truck Connection Archive road tes", 2002, 2005, True),
    ("9R62pZlLXnM", "2003 Chevy Silverado 4WS Sport Truck Connection Archive road tests", 2002, 2005, True),
    ("LzvM8fu6wYE", "Interior view 2003 Chevy Silverado, Walk-Around Review", 2002, 2005, True),
]

STOCK_V = [
    "pickup truck rear wheel close up turning",
    "truck towing trailer tight turn parking lot",
    "full size pickup truck reversing with trailer",
    "close up tire steering knuckle suspension",
    "pickup truck maneuvering narrow street aerial",
    "boat trailer backing down ramp truck",
    "car dealership lot pickup trucks rows",
    "automotive assembly line truck axle factory",
    "truck driving highway rear three quarter tracking shot",
    "steering wheel hands driver interior close up",
    "pickup truck driving highway",
    "pickup truck towing trailer road",
    "truck rear wheel close up turning",
    "hands on steering wheel driving truck",
    "truck tires asphalt tight turn",
    "pickup truck parking lot maneuvering aerial",
    "american highway desert truck driving",
    "car dealership lot pickup trucks",
    "truck bed loading cargo worker",
    "automotive factory assembly line chassis",
]
STOCK_I = [
    "GMC Sierra pickup truck",
    "full size pickup truck studio",
    "pickup truck emblem badge chrome",
    "car rear axle suspension underneath",
    "pickup truck dashboard steering wheel",
    "pickup truck rear wheel",
    "truck towing trailer highway",
    "car dealership lot trucks",
]


def _dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nk=1:nw=1", str(p)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _maybe_trim(src: Path) -> Path:
    d = _dur(src)
    if d <= TRIM_LONG:
        return src
    out = src.with_name(src.stem + "_trim.mp4")
    if not out.exists():
        ss = max(0.0, (d - TRIM_LONG) / 2)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{ss:.1f}", "-t",
                        f"{TRIM_LONG:.1f}", "-i", str(src), "-c", "copy", str(out)],
                       capture_output=True)
    return out if out.exists() else src


def _already(cat, sid) -> int:
    return cat.cx.execute("SELECT COUNT(*) c FROM assets WHERE source_id=?", (sid,)).fetchone()["c"]


def _drop_raw(*paths):
    """Delete the download once it is safely in the content-addressed object store.

    ingest_file COPIES into library/objects/, so every source existed twice. Across two niches that
    was 12.4 GB of pure duplication and it filled the disk mid-build ("not enough space on the
    disk"). Retrieval resolves through objects/, never through raw/, and re-runs skip cataloged
    sources via the database, so the download has no reason to survive ingestion."""
    for p in paths:
        try:
            if p and Path(p).exists():
                Path(p).unlink()
        except OSError:
            pass

def ingest_video(cat, vis, vid, label, era_from, era_to):
    sid = f"SRC_QS_{vid}"
    if _already(cat, sid):          # already cataloged — never re-spend vision on it
        print(f"  [yt] {vid} cached ({_already(cat, sid)} segments)", flush=True)
        return 0
    dest = RAW / f"{vid}.mp4"
    if not dest.exists():
        ok = yt_source.download(vid, dest, max_height=1080)
        if not ok or not dest.exists():
            print(f"  [yt] {vid} DOWNLOAD FAILED", flush=True); return 0
    src = _maybe_trim(dest)
    sha = cat.ingest_file(src)["sha256"]
    cat.add_source(sid, f"youtube:{vid}", "video", content_hash=str(sha))
    try:
        segs = vis.analyze(src)
    except Exception as e:
        print(f"  [yt] {vid} analyze error: {repr(e)[:120]}", flush=True); return 0
    n = 0
    for k, s in enumerate(segs[:CAP_SEG]):
        aid = f"AST_QS_{vid}_{s['start_ms']}"
        ok = cat.add_asset(aid, "video", source_id=sid, object_sha=str(sha),
                           start_ms=s["start_ms"], end_ms=s["end_ms"],
                           description=s.get("description", ""), era_from=era_from, era_to=era_to,
                           quality=s.get("quality", "medium"), clean_status=s.get("clean_status", "clean"),
                           match_conf=s.get("match_conf", 0.8), catalog=s)
        if ok:
            cat.auto_approve(aid); n += 1
    _drop_raw(src, dest)
    print(f"  [yt] {vid} {label[:40]}: {n} segments", flush=True)
    return n


def describe_image(vis, path: Path) -> dict:
    b = Path(path).read_bytes()
    try:
        return vis._describe([b])
    except Exception:
        return {}


def ingest_stock(cat, vis, query, kind):
    try:
        got = stock_source.fetch(query, 4, RAW / "stock", kind=kind)
    except Exception as e:                     # a transient DNS/network blip must not kill the run
        print(f"  [stock:{kind}] {query[:30]} fetch error: {repr(e)[:80]} — skipping", flush=True)
        return 0
    n = 0
    for h in got:
        f = Path(h["file"])
        if not f.exists():
            continue
        sid = f"SRC_STOCK_{h['provider']}_{h['id']}"
        if _already(cat, sid):                 # already cataloged — don't re-spend vision on it
            continue
        sha = cat.ingest_file(f)["sha256"]
        cat.add_source(sid, h.get("url", ""), kind, content_hash=str(sha))
        if kind == "video":
            try:
                segs = vis.analyze(f)
            except Exception:
                segs = []
            for s in segs[:14]:
                aid = f"AST_STK_{h['id']}_{s['start_ms']}"
                if cat.add_asset(aid, "video", source_id=sid, object_sha=str(sha),
                                 start_ms=s["start_ms"], end_ms=s["end_ms"],
                                 description=s.get("description", ""),
                                 quality=s.get("quality", "medium"),
                                 clean_status=s.get("clean_status", "clean"),
                                 match_conf=s.get("match_conf", 0.7), catalog=s):
                    cat.auto_approve(aid); n += 1
        else:
            meta = describe_image(vis, f)
            meta.setdefault("keywords", query.split())
            aid = f"AST_IMG_{h['id']}"
            if cat.add_asset(aid, "image", object_sha=str(sha),
                             description=meta.get("description", query),
                             quality=meta.get("quality", "high"),
                             clean_status=meta.get("clean_status", "clean"),
                             match_conf=meta.get("match_conf", 0.7), catalog=meta):
                cat.auto_approve(aid); n += 1
    print(f"  [stock:{kind}] {query[:38]}: {n}", flush=True)
    return n




# Instagram accounts to pull STILLS from. Empty is fine — the phase skips itself.
INSTA = ["gmc", "chevrolet"]
INSTA_SESSION = os.environ.get("INSTA_SESSION_USER", "")   # set once you have logged in


def ingest_insta(cat, vis):
    """Official accounts as a stills source. Skips cleanly when no session exists.

    Anonymous Instagram now 429s on the first request, so a session is required. The owner creates
    it once themselves with `python -m instaloader --login <user>`; this code never sees a password.
    Added because sourcing measured 80-95% YouTube across every library built so far, which is a
    single point of failure — and for celebrity/sports subjects the stills are often the only
    freely available material of the actual person."""
    if not INSTA:
        return 0
    try:
        import insta_source as IS
    except ImportError:
        print("  [insta] instaloader not installed - skipping", flush=True); return 0
    if not INSTA_SESSION or not IS.have_session(INSTA_SESSION):
        print(f"  [insta] no session -> SKIPPED. To enable, run once yourself:", flush=True)
        print(f"          python -m instaloader --login <your_username>", flush=True)
        print(f"          then set INSTA_SESSION_USER=<your_username>", flush=True)
        return 0
    n = 0
    for acct in INSTA:
        try:
            got = IS.profile_stills(acct, RAW / "insta", session_user=INSTA_SESSION, want=15)
        except Exception as e:
            print(f"  [insta] {acct}: {repr(e)[:90]}", flush=True); continue
        for g in got:
            f = Path(g["path"])
            if not f.exists() or f.suffix.lower() == ".mp4":
                continue
            sid = f"SRC_IG_{acct}_{g['shortcode']}"
            if _already(cat, sid):
                continue
            sha = cat.ingest_file(f)["sha256"]
            cat.add_source(sid, f"instagram:{acct}/{g['shortcode']}", "image", content_hash=str(sha))
            meta = describe_image(vis, f)
            meta.setdefault("keywords", (g.get("caption") or acct).split()[:12])
            aid = f"AST_IG_{g['shortcode']}"
            if cat.add_asset(aid, "image", object_sha=str(sha),
                             description=meta.get("description", g.get("caption") or acct),
                             quality=meta.get("quality", "high"),
                             clean_status=meta.get("clean_status", "clean"),
                             match_conf=meta.get("match_conf", 0.7), catalog=meta):
                cat.auto_approve(aid); n += 1
        print(f"  [insta] {acct}: {n} stills so far", flush=True)
    return n

def main():
    cat = catalog_db.Catalog()
    vis = vision.RelayVision()
    print("relay:", vis.name, "ok:", vis.ok, flush=True)
    t0 = time.time()
    tot = 0
    print("== YOUTUBE (entity-specific) ==", flush=True)
    for vid, label, ef, et, _ in YT:
        tot += ingest_video(cat, vis, vid, label, ef, et)
    print("== STOCK VIDEO (ambience) ==", flush=True)
    for q in STOCK_V:
        tot += ingest_stock(cat, vis, q, "video")
    print("== INSTAGRAM STILLS ==", flush=True)
    tot += ingest_insta(cat, vis)

    print("== STILLS ==", flush=True)
    for q in STOCK_I:
        for attempt in range(3):               # stills phase is where the DNS blip hit; retry
            try:
                tot += ingest_stock(cat, vis, q, "image")
                break
            except Exception as e:
                print(f"  retry {q[:24]} ({repr(e)[:60]})", flush=True); time.sleep(4)
    # Build the small analysis proxies now, once, as part of the library. Measured 10x faster
    # gating and 45x less data to read; doing it here keeps it out of every future video build.
    import glob as _g
    objs = _g.glob(str(HERE / "library" / "objects" / "**" / "*.mp4"), recursive=True)
    print(f"building {len(objs)} analysis proxies...", flush=True)
    BC.build_proxies(objs, workers=4, cache_dir=HERE / "library" / "proxy")

    vv = cat.cx.execute("SELECT COUNT(*) c FROM assets WHERE type='video' AND review_status='approved'").fetchone()["c"]
    ii = cat.cx.execute("SELECT COUNT(*) c FROM assets WHERE type='image' AND review_status='approved'").fetchone()["c"]
    print(f"\nDONE in {time.time()-t0:.0f}s — {tot} assets cataloged "
          f"({vv} video + {ii} image approved)", flush=True)


if __name__ == "__main__":
    main()
