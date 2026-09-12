#!/usr/bin/env python3
"""
serper_source.py — Google Images (open-web stills) via serper.dev.

The gap this fills: until now stills came only from Wikimedia (weak) and brochure/document
extraction (cars only). Google Images through Serper is a broad open-web still source — exactly the
"open-web image search" tier of the pipeline. It returns width/height in the search result, so the
quality gate runs BEFORE any download, same discipline as yt_source / stock_source.

Key lives in keys.env (SERPER_KEY). Returns the SAME dict shape as stock_source images, so any
consumer (a niche hunt flow, source_hunter) treats a Serper hit exactly like a Pexels/Pixabay hit:

    {"provider": "serper", "kind": "image", "w": W, "h": H,
     "url": <full-res image url>, "src": <page url>, "id": "sr_i<hash>", "title": <str>}

fetch() then adds "file": <downloaded path>.

STILLS GATE (not the landscape video gate): Google Images stills are often portrait or square
(a 1080x1350 poster, a 1200x1200 crop). Those are GOOD — the render turns any non-16:9 still into a
postcard, never stretches it. So the gate here is a minimum SIZE (long edge + short edge), NOT the
w>h landscape rule used for video. Downstream still de-dupes, catalogs and gates each image.
"""
from __future__ import annotations
import hashlib
import json
import urllib.request
from pathlib import Path

import config

ENDPOINT = "https://google.serper.dev/images"

# Stills quality floor. A still gets postcarded to a 1280x720 canvas, so the long edge should be at
# least ~HD and the short edge not tiny. Portrait/square allowed (postcard handles aspect).
SERP_MIN_LONG = 900     # longest edge
SERP_MIN_SHORT = 500    # shortest edge


def _ok(w: int, h: int) -> bool:
    if not w or not h:
        return False
    return max(w, h) >= SERP_MIN_LONG and min(w, h) >= SERP_MIN_SHORT


def _uid(url: str) -> str:
    return "sr_i" + hashlib.sha1(url.encode("utf-8", "replace")).hexdigest()[:10]


def _download(url: str, dest: Path) -> bool:
    dest = Path(dest)
    if dest.exists():
        return True
    try:
        data = urllib.request.urlopen(urllib.request.Request(
            url, headers={"User-Agent": "CDev/1.0"}), timeout=120).read()
        if len(data) > 20000:          # a few KB = an error/placeholder image, not a real still
            dest.write_bytes(data)
            return True
    except Exception:
        return False
    return False


def search_images(query: str, n: int = 8, gl: str = "us", hl: str = "en") -> list[dict]:
    """Google Images via Serper. Returns HD-gated hits (not downloaded). [] if no key / on error."""
    if not config.SERPER_KEY:
        return []
    body = json.dumps({"q": query, "gl": gl, "hl": hl}).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=body,
        headers={"X-API-KEY": config.SERPER_KEY, "Content-Type": "application/json"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=45))
    except Exception:
        return []
    out, seen = [], set()
    for im in d.get("images", []):
        url = im.get("imageUrl")
        if not url or url in seen:
            continue
        w, h = int(im.get("imageWidth") or 0), int(im.get("imageHeight") or 0)
        if not _ok(w, h):
            continue
        seen.add(url)
        out.append({"provider": "serper", "kind": "image", "w": w, "h": h, "url": url,
                    "src": im.get("link") or im.get("source") or "",
                    "id": _uid(url), "title": (im.get("title") or "")[:200]})
        if len(out) >= n:
            break
    return out


def fetch(query: str, n: int, out_dir, kind: str = "image") -> list[dict]:
    """Search Google Images, gate by size, download. Returns [{...meta, file}].

    kind is accepted for a uniform signature with stock_source.fetch; Serper is images only, so a
    non-image kind returns []. Use for open-web stills; the cataloger still describes + gates each.
    """
    if kind != "image":
        return []
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    got = []
    for h in search_images(query, max(n * 3, n)):   # over-fetch: some URLs fail to download
        dest = out_dir / f"{h['id']}.jpg"
        if _download(h["url"], dest):
            got.append({**h, "file": str(dest)})
        if len(got) >= n:
            break
    return got


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "mike tyson 1988"
    print("serper key:", bool(config.SERPER_KEY))
    hits = search_images(q, 6)
    print(f"gated hits for {q!r}:", len(hits))
    for h in hits:
        print(f"  {h['w']}x{h['h']}  {h['id']}  {h['title'][:50]}")
