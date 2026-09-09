#!/usr/bin/env python3
"""hunt.py — build the Lyle Alzado (sports-scandal niche) library from scratch.

This is the real open-world test the whole project is about: unlike the boxing job, there is NO
pre-built library here. Everything is sourced cold, from free sources, and cataloged by the relay
vision model before anything can be retrieved.

Source mix is tuned to the defence-explainer reference channel (dominiondefencereview):
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Repo root, derived from THIS file. Never hard-code an absolute path: a machine change (or a
# different drive letter) silently sends every read and write somewhere else. One earlier build
# wrote 719 files into the wrong library for exactly this reason, and the same mistake was already
# sitting in two other files at the time.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

HERE = Path(f"{ROOT}/_alzado")
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
    ("eKtBi2f3sxE", "Lyle Alzado on Up Close with Roy Firestone 1991", 1990, 1991, True),
    ("U6WeJuY0l4M", "Sports Century: Lyle Alzado (ESPN)", 1971, 1992, True),
    ("WG-xuXtYbqY", "Lyle Alzado NFL highlights", 1971, 1985, True),
    ("cSe65K53PMM", "Lyle Alzado #77 career footage", 1971, 1985, True),
    ("WZiYl4vr-9I", "Darth Raider: Lyle Alzado Raiders Broncos Browns", 1971, 1985, True),
    ("HYLXw0WHnWw", "Lyle Alzado rips off Jets helmet", 1982, 1982, True),
    ("7-1eqqDZkyM", "Muhammad Ali and Lyle Alzado boxing exhibition", 1979, 1979, True),
    ("Gflye0Icnns", "1971 Lyle Alzado rookie season mic'd up", 1971, 1971, True),
    ("9x4u5dymksw", "Sports Illustrated advert with Lyle Alzado 1985", 1985, 1985, True),
    ("yLc1iqOeHqs", "NFL pro Lyle Alzado did steroids kill him", 1990, 1992, True),
    ("Vy1zZaUs0t4", "Denver Broncos Orange Crush Defense NFL Films", 1976, 1986, True),
    ("rnT4sG1eAHk", "Orange Crush - The Franchise Denver Broncos", 1976, 1978, True),
    ("24vx0dH7wnA", "Super Bowl XVIII Redskins vs Raiders NFL", 1984, 1984, True),
    ("cBA0r9P7QLI", "Super Bowl XVIII LA Raiders 38 Washington 9", 1984, 1984, True),
    ("Snj0q26vHzE", "Super Bowl XVIII Washington vs Los Angeles Raiders", 1984, 1984, True),
    ("hhO2uyQ8V14", "Eye Ball to Eye Ball NFL Films John Facenda", 1970, 1980, True),
    ("u3YMR66hox0", "NFL 100 All-Time Team Defensive Line", 1960, 2000, True),
    ("Z-mVMGtj5Ic", "Senate committee hears NFL officials on steroid use", 1990, 1995, True),
    ("rb65QXaJoEs", "NFL investigated over drug abuse claims", 1990, 1995, True),
]

STOCK_V = [
    "american football stadium floodlights at night",
    "empty locker room bench and lockers",
    "barbell weight room heavy lifting gym",
    "american football helmet close up",
    "stadium crowd cheering wide aerial",
    "newspaper printing press rolling headlines",
    "glass medicine vials on laboratory bench",
    "syringe drawing liquid from vial close up",
    "pills spilling out of prescription bottle",
    "urine sample cup medical drug test",
    "empty hospital corridor",
    "MRI scanner empty room",
    "IV drip saline bag close up",
    "man lifting heavy barbell weight room",
    "vintage television static vhs glitch",
    "empty american football field goal posts",
]
STOCK_I = [
    "american football helmet studio",
    "vintage football stadium",
    "weight plates barbell gym",
    "medicine vial syringe still life",
    "hospital corridor empty",
    "newspaper front page headline",
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


def prepare_video(vis, vid, label):
    """Download + vision-analyze ONE source. Safe to run in parallel: touches no database."""
    dest = RAW / f"{vid}.mp4"
    if not dest.exists():
        try:
            ok = yt_source.download(vid, dest, max_height=1080)
        except Exception as e:
            print(f"  [yt] {vid} download error {repr(e)[:70]}", flush=True); return None
        if not ok or not dest.exists():
            print(f"  [yt] {vid} DOWNLOAD FAILED", flush=True); return None
    src = _maybe_trim(dest)
    try:
        segs = vis.analyze(src)
    except Exception as e:
        print(f"  [yt] {vid} analyze error: {repr(e)[:90]}", flush=True); return None
    print(f"  [yt] {vid} {label[:38]}: {len(segs)} segments", flush=True)
    return (vid, src, segs)


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

def store_video(cat, vid, src, segs, era_from, era_to):
    """Serial DB write. sqlite + one Catalog object is not thread-safe, so every write happens
    here on the main thread while only the slow API work was parallelised."""
    sid = f"SRC_AZ_{vid}"
    sha = cat.ingest_file(src)["sha256"]
    cat.add_source(sid, f"youtube:{vid}", "video", content_hash=str(sha))
    n = 0
    for s_ in segs[:CAP_SEG]:
        aid = f"AST_AZ_{vid}_{s_['start_ms']}"
        if cat.add_asset(aid, "video", source_id=sid, object_sha=str(sha),
                         start_ms=s_["start_ms"], end_ms=s_["end_ms"],
                         description=s_.get("description", ""), era_from=era_from, era_to=era_to,
                         quality=s_.get("quality", "medium"),
                         clean_status=s_.get("clean_status", "clean"),
                         match_conf=s_.get("match_conf", 0.8), catalog=s_):
            cat.auto_approve(aid); n += 1
    _drop_raw(src, RAW / f"{vid}.mp4")
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
INSTA = ["raiders", "broncos", "nfl"]
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
    todo = [(v, l, ef, et) for v, l, ef, et, _ in YT if not _already(cat, f"SRC_AZ_{v}")]
    print(f"  {len(YT)-len(todo)} cached, {len(todo)} to fetch", flush=True)
    with ThreadPoolExecutor(max_workers=5) as ex:
        prepared = list(ex.map(lambda t: prepare_video(vis, t[0], t[1]), todo))
    for (vid, label, ef, et), got in zip(todo, prepared):
        if got:
            tot += store_video(cat, got[0], got[1], got[2], ef, et)
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
