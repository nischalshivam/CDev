#!/usr/bin/env python3
"""docs_source.py — the DOCUMENT layer: brochures, spec sheets, adverts, price lists.

Why this module exists. Three competitor videos were measured frame by frame against ours:

    COMP cars   44% stills   motion 3.3      MINE cars   3% stills   motion 26.7

Their stills are not pretty photographs. They are EVIDENCE — magazine advert scans, dealer
brochures, option lists with the relevant line highlighted, window stickers, price sheets. When the
narration says "the option cost $850", the screen shows the actual line on the actual price list.
That is the whole difference between a video that tells you something and one that proves it, and it
is why their cut reads as researched while ours reads as a montage.

It is also, conveniently, the cheapest thing to put on screen: a still costs one image decode and a
slow push, where a video shot costs a seek, a decode and a re-encode.

Documents are not on stock sites. The two free places they actually live:

  BROCHURE VIDEOS  enthusiasts film themselves turning the pages of old brochures and press kits,
                   and archive channels post whole advert reels. One such video is hundreds of
                   clean, flat, well-lit document scans. We take distinct PAGES out of it as stills.
  WIKIMEDIA        license-clear photographs and some scanned documents, by article.

Page extraction is the interesting part: a page-turn video is mostly static, so ordinary shot
detection finds almost nothing. Instead we sample densely, then keep a frame only when it differs
enough from the last KEPT frame — which is exactly "a new page is now on screen".
"""
from __future__ import annotations
import os
import subprocess
from pathlib import Path

import numpy as np

import frame_quality as FQ


def extract_pages(video, out_dir, fps: float = 0.5, min_change: float = 12.0,
                  max_pages: int = 60, min_detail: float = 22.0) -> list[str]:
    """Pull distinct document PAGES out of a brochure/advert video.

    min_change is a mean-absolute-difference threshold against the last frame we kept, not the last
    frame we saw: during a page turn many frames differ from their neighbour while showing nothing
    readable, and comparing against the last KEPT page ignores that entirely.

    min_detail rejects blur and motion during the turn — a page mid-flip has low detail, a page
    lying flat has high detail."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = FQ.decode_frames(video, fps=fps, width=480)
    if not frames:
        return []
    kept, last = [], None
    for t, f in frames:
        if float(f.std()) < min_detail:            # blank, dark, or mid-turn blur
            continue
        if last is not None and float(np.abs(f - last).mean()) < min_change:
            continue
        kept.append(t)
        last = f
        if len(kept) >= max_pages:
            break
    paths = []
    for i, t in enumerate(kept):
        p = out_dir / f"{Path(str(video)).stem}_p{i:03d}.jpg"
        if not p.exists():
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
                            "-frames:v", "1", "-q:v", "2", str(p)], capture_output=True)
        if p.exists():
            paths.append(str(p))
    return paths


def wikimedia_images(article: str, out_dir, want: int = 8, min_width: int = 1000) -> list[str]:
    """License-clear stills for a subject, straight from the Wikipedia article's own images."""
    try:
        import requests
    except ImportError:
        return []
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        d = requests.get("https://en.wikipedia.org/w/api.php",
                         params={"format": "json", "action": "query", "generator": "images",
                                 "titles": article, "gimlimit": "50", "prop": "imageinfo",
                                 "iiprop": "url|size", "iiurlwidth": "1600"},
                         timeout=30, headers={"User-Agent": "CDev/1.0"}).json()
    except Exception:
        return []
    got = []
    for _, v in (d.get("query", {}).get("pages", {}) or {}).items():
        ii = (v.get("imageinfo") or [{}])[0]
        url = ii.get("thumburl") or ii.get("url")
        title = v.get("title", "")
        if not url or not title.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        if ii.get("width", 0) < min_width:
            continue
        dest = out_dir / (title.replace("File:", "").replace(" ", "_")[:70])
        if not dest.exists():
            try:
                r = requests.get(url, timeout=60, headers={"User-Agent": "CDev/1.0"})
                if r.status_code == 200:
                    dest.write_bytes(r.content)
            except Exception:
                continue
        if dest.exists():
            got.append(str(dest))
        if len(got) >= want:
            break
    return got


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "pages":
        print("\n".join(extract_pages(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "pages")))
    elif len(sys.argv) > 2:
        print("\n".join(wikimedia_images(sys.argv[1], sys.argv[2])))
