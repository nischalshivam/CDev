#!/usr/bin/env python3
"""
yt_source.py — cookie-aware YouTube search + HD-pre-filtered download.

Two FOOTAGE-WORKFLOW lessons baked in:
  * Cookies, not proxies, are the first unblock. Measured: 250 videos on one account's cookies,
    zero 403/429. Without cookies YouTube stops at "confirm you're not a bot" before download.
  * FILTER BEFORE DOWNLOAD. Measured: 73% of a library was sub-HD and had to be deleted later, and
    ~70/100 results never download once you check first. `best_format()` reads the resolution with
    `yt-dlp -J` BEFORE downloading; the HD gate (w>=1280 & h>=720 & w>h) rejects sub-HD + Shorts.

Cookies path comes from keys.env (YT_COOKIES); proxies from SCRAPE_PROXIES if present.
"""
from __future__ import annotations
import os
import json
import subprocess
from pathlib import Path

import config
from media_probe import MIN_W, MIN_H

YTDLP = "yt-dlp"


def _cookie_args() -> list[str]:
    ck = config.YT_COOKIES
    return ["--cookies", ck] if ck and Path(ck).exists() else []


def _run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def search(query: str, n: int = 5) -> list[dict]:
    """Flat metadata for the top n results (no download). Returns [{id,title,uploader,duration}]."""
    r = _run([YTDLP, "--no-warnings", "--flat-playlist", "-J", *_cookie_args(),
              f"ytsearch{n}:{query}"], timeout=120)
    try:
        entries = json.loads(r.stdout).get("entries", [])
    except Exception:
        return []
    return [{"id": e.get("id"), "title": e.get("title", ""),
             "uploader": e.get("uploader") or e.get("channel", ""),
             "duration": e.get("duration") or 0} for e in entries if e.get("id")]


def best_format(video_id: str) -> tuple[int, int]:
    """Max (width,height) available for a video — read BEFORE downloading (yt-dlp -J)."""
    r = _run([YTDLP, "--no-warnings", "-J", *_cookie_args(),
              f"https://youtube.com/watch?v={video_id}"], timeout=90)
    try:
        info = json.loads(r.stdout)
    except Exception:
        return (0, 0)
    w = h = 0
    for f in info.get("formats", []):
        if f.get("width") and f.get("height"):
            if f["width"] * f["height"] > w * h:
                w, h = f["width"], f["height"]
    return (w, h)


def hd_ok(video_id: str) -> tuple[bool, str]:
    w, h = best_format(video_id)
    if w == 0:
        return False, "no formats / could not read"
    if w < MIN_W or h < MIN_H:
        return False, f"best is {w}x{h} (sub-HD)"
    if w <= h:
        return False, f"portrait/square ({w}x{h})"
    return True, f"{w}x{h}"


def download(video_id: str, dest: str | Path, max_height: int = 720) -> bool:
    dest = Path(dest)
    if dest.exists():
        return True
    fmt = (f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/b[height<={max_height}][ext=mp4]/"
           f"b[height<={max_height}]/18/best")
    cmd = [YTDLP, "--no-warnings", "--no-playlist", *_cookie_args(), "-f", fmt,
           "-o", str(dest), f"https://youtube.com/watch?v={video_id}"]
    raw = os.getenv("SCRAPE_PROXIES", "")
    prox = [p.strip() for p in raw.splitlines() if p.strip()]
    if prox:
        cmd = [YTDLP, "--proxy", prox[0]] + cmd[1:]
    _run(cmd, timeout=900)
    return dest.exists()


def fetch_hd(query: str, n: int, out_dir: str | Path, avoid: list[str] = None,
             max_height: int = 720) -> list[dict]:
    """Search -> HD-pre-filter -> download the passers. Returns [{id,title,file}].
    This is the real acquisition entry point (replaces ad-hoc yt-dlp calls)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    avoid = [a.lower() for a in (avoid or [])]
    got = []
    for e in search(query, n * 3):
        blob = f"{e['uploader']} {e['title']}".lower()
        if any(a in blob for a in avoid):
            continue
        ok, why = hd_ok(e["id"])
        if not ok:
            print(f"  skip {e['id']} — {why}")
            continue
        dest = out_dir / f"{e['id']}.mp4"
        if download(e["id"], dest, max_height):
            got.append({"id": e["id"], "title": e["title"], "file": str(dest)})
            print(f"  got  {e['id']} — {why} — {e['title'][:50]}")
        if len(got) >= n:
            break
    return got


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "Mercedes R107 SL review"
    print("cookies:", bool(_cookie_args()))
    for r in fetch_hd(q, 2, "raw_test"):
        print(r)
