#!/usr/bin/env python3
"""
stock_source.py — free STOCK footage/images (Pexels + Pixabay).

This is the "generic ambience" tier of the source ladder (FOUNDATION §2): city skyline, money,
factory line, crowd, ocean — the atmospheric shots where entity-specific footage isn't needed.
In the R107 test these beats fell to text cards; stock fills them properly. All results are
HD-filtered (w>=1280 & h>=720 & w>h) BEFORE download, same gate as everything else.

Keys live in keys.env (PEXELS_KEY, PIXABAY_KEY). Both are free tiers — fine for ambience b-roll.
"""
from __future__ import annotations
import json
import urllib.request
import urllib.parse
from pathlib import Path

import config
from media_probe import MIN_W, MIN_H


def _get(url, headers=None):
    h = {"User-Agent": "CDev/1.0"}         # Pexels' Cloudflare 403s (code 1010) without a UA
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    return json.load(urllib.request.urlopen(req, timeout=45))


def _hd(w, h) -> bool:
    return w >= MIN_W and h >= MIN_H and w > h


def _download(url, dest) -> bool:
    dest = Path(dest)
    if dest.exists():
        return True
    try:
        data = urllib.request.urlopen(urllib.request.Request(
            url, headers={"User-Agent": "CDev/1.0"}), timeout=120).read()
        if len(data) > 20000:
            dest.write_bytes(data)
            return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------- Pexels
def pexels(query: str, n: int, kind: str = "video") -> list[dict]:
    if not config.PEXELS_KEY:
        return []
    hdr = {"Authorization": config.PEXELS_KEY}
    q = urllib.parse.quote(query)
    out = []
    if kind == "video":
        d = _get(f"https://api.pexels.com/videos/search?query={q}&per_page={n*2}", hdr)
        for v in d.get("videos", []):
            # pick the largest HD-landscape file
            best = None
            for f in v.get("video_files", []):
                w, h = f.get("width", 0), f.get("height", 0)
                if _hd(w, h) and (best is None or w * h > best[0] * best[1]):
                    best = (w, h, f.get("link"))
            if best:
                out.append({"provider": "pexels", "kind": "video", "w": best[0], "h": best[1],
                            "url": best[2], "src": v.get("url", ""), "id": f"px_v{v.get('id')}"})
            if len(out) >= n:
                break
    else:
        d = _get(f"https://api.pexels.com/v1/search?query={q}&per_page={n*2}", hdr)
        for p in d.get("photos", []):
            w, h = p.get("width", 0), p.get("height", 0)
            if _hd(w, h):
                out.append({"provider": "pexels", "kind": "image", "w": w, "h": h,
                            "url": p["src"]["large2x"], "src": p.get("url", ""),
                            "id": f"px_i{p.get('id')}"})
            if len(out) >= n:
                break
    return out


# ---------------------------------------------------------------- Pixabay
def pixabay(query: str, n: int, kind: str = "video") -> list[dict]:
    if not config.PIXABAY_KEY:
        return []
    q = urllib.parse.quote(query)
    out = []
    if kind == "video":
        d = _get(f"https://pixabay.com/api/videos/?key={config.PIXABAY_KEY}&q={q}&per_page={max(3,n*2)}")
        for v in d.get("hits", []):
            f = (v.get("videos") or {}).get("large") or (v.get("videos") or {}).get("medium") or {}
            w, h = f.get("width", 0), f.get("height", 0)
            if _hd(w, h) and f.get("url"):
                out.append({"provider": "pixabay", "kind": "video", "w": w, "h": h,
                            "url": f["url"], "src": v.get("pageURL", ""), "id": f"pb_v{v.get('id')}"})
            if len(out) >= n:
                break
    else:
        d = _get(f"https://pixabay.com/api/?key={config.PIXABAY_KEY}&q={q}&per_page={max(3,n*2)}"
                 f"&image_type=photo&min_width={MIN_W}")
        for p in d.get("hits", []):
            w, h = p.get("imageWidth", 0), p.get("imageHeight", 0)
            if _hd(w, h) and p.get("largeImageURL"):
                out.append({"provider": "pixabay", "kind": "image", "w": w, "h": h,
                            "url": p["largeImageURL"], "src": p.get("pageURL", ""),
                            "id": f"pb_i{p.get('id')}"})
            if len(out) >= n:
                break
    return out


def fetch(query: str, n: int, out_dir, kind: str = "video") -> list[dict]:
    """Search both providers, HD-filter, download. Returns [{...meta, file}]. Pexels first, Pixabay
    tops up. Use for generic ambience only — the cataloger still describes + gates each clip."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    hits = pexels(query, n, kind) + pixabay(query, n, kind)
    got = []
    ext = "mp4" if kind == "video" else "jpg"
    for h in hits:
        dest = out_dir / f"{h['id']}.{ext}"
        if _download(h["url"], dest):
            got.append({**h, "file": str(dest)})
        if len(got) >= n:
            break
    return got


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "city skyline aerial"
    print("pexels key:", bool(config.PEXELS_KEY), "| pixabay key:", bool(config.PIXABAY_KEY))
    print("video hits:", [(h["provider"], h["w"], h["h"]) for h in
                          pexels(q, 3, "video") + pixabay(q, 3, "video")])
    print("image hits:", [(h["provider"], h["w"], h["h"]) for h in
                          pexels(q, 3, "image") + pixabay(q, 3, "image")])
