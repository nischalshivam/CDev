#!/usr/bin/env python3
"""reddit_source.py — Reddit as a source, via an exported cookies.txt.

MEASURED, 2026-09-04. Every unauthenticated route into Reddit is closed:

    www.reddit.com/r/<sub>/top.json          403 Blocked   (plain, and with a browser User-Agent)
    old.reddit.com/r/<sub>/top.json          404
    old.reddit.com + session warm-up         200 but text/html — a "Welcome to Reddit" wall
    + second warm-up / over18 / eu_cookie    same wall, five variants tried, JSON never returned

That last row matters because a popular scraper (ksanjeev284/reddit-universal-scraper, 591 stars)
advertises "No API keys required!" and works by warming up a session against old.reddit.com first.
That technique is what the wall now defeats — the README is simply out of date. Running it was the
only way to find that out.

So Reddit needs either OAuth credentials (what bdfr uses) or a logged-in session. This module takes
the SESSION route, because it reuses a mechanism that already works on this machine: the owner
already exports a cookies.txt for YouTube, and `--cookies-from-browser` is broken here (Chrome's
cookie DB cannot be copied, Edge fails DPAPI decryption, Firefox is not installed).

Export cookies.txt with any "Get cookies.txt" browser extension while logged into Reddit, then:

    set REDDIT_COOKIES=C:/path/to/reddit_cookies.txt

Nothing here ever sees a password.
"""
from __future__ import annotations
import http.cookiejar
import json
import os
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def cookies_path() -> str:
    return os.getenv("REDDIT_COOKIES", "")


def _session():
    """A requests session loaded with the exported cookie jar, or None if there is no jar."""
    import requests
    ck = cookies_path()
    if not ck or not Path(ck).exists():
        return None
    jar = http.cookiejar.MozillaCookieJar(ck)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        return None
    s = requests.Session()
    s.cookies = jar
    s.headers.update({"User-Agent": UA, "Accept": "application/json, text/javascript, */*; q=0.01",
                      "Accept-Language": "en-US,en;q=0.9"})
    return s


def available() -> bool:
    return _session() is not None


def listing(subreddit: str, sort: str = "top", period: str = "year", limit: int = 50) -> list[dict]:
    """Posts from a subreddit. Returns [] (never raises) when no cookie jar is configured.

    Each item: {id, title, url, width, height, is_video, permalink}."""
    s = _session()
    if s is None:
        return []
    url = (f"https://www.reddit.com/r/{subreddit}/{sort}.json"
           f"?t={period}&limit={min(limit, 100)}&raw_json=1")
    try:
        r = s.get(url, timeout=30)
        if not r.headers.get("content-type", "").startswith("application/json"):
            return []
        children = r.json()["data"]["children"]
    except Exception:
        return []
    out = []
    for c in children:
        d = c.get("data", {})
        src = (d.get("preview", {}).get("images", [{}])[0].get("source", {}) or {})
        out.append({"id": d.get("id"), "title": d.get("title", "")[:300],
                    "url": d.get("url", ""), "permalink": "https://www.reddit.com" + d.get("permalink", ""),
                    "width": int(src.get("width") or 0), "height": int(src.get("height") or 0),
                    "is_video": bool(d.get("is_video")), "over18": bool(d.get("over_18"))})
    return out


def fetch_images(subreddit: str, dest, sort="top", period="year", limit=50,
                 want=20, min_w=1280) -> list[str]:
    """Download direct still images from a subreddit.

    Only landscape stills at or above the library's width floor are taken: the HD gate is
    `width>=1280 AND height>=720 AND width>height`, so anything else cannot survive it anyway and
    downloading it would only cost time and disk."""
    s = _session()
    if s is None:
        return []
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    got = []
    for p in listing(subreddit, sort, period, limit):
        if len(got) >= want:
            break
        u = p["url"]
        if p["over18"] or p["is_video"] or not u.lower().endswith(IMG_EXT):
            continue
        if p["width"] < min_w or p["height"] <= 0 or p["width"] <= p["height"]:
            continue
        out = dest / f"{subreddit}_{p['id']}{Path(u).suffix.split('?')[0][:5]}"
        if not out.exists():
            try:
                r = s.get(u, timeout=60)
                if r.status_code != 200 or len(r.content) < 20000:
                    continue
                out.write_bytes(r.content)
            except Exception:
                continue
        got.append(str(out))
    return got


if __name__ == "__main__":
    import sys
    sub = sys.argv[1] if len(sys.argv) > 1 else "carporn"
    if not available():
        print("No REDDIT_COOKIES configured.")
        print("  1. log into reddit.com in your browser")
        print("  2. export cookies.txt with a 'Get cookies.txt' extension")
        print("  3. set REDDIT_COOKIES=C:/path/to/reddit_cookies.txt")
        sys.exit(1)
    posts = listing(sub)
    print(f"r/{sub}: {len(posts)} posts")
    for f in fetch_images(sub, "_reddit_test", want=5):
        print(" ", f)
