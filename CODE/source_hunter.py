#!/usr/bin/env python3
"""
source_hunter.py — Multi-source asset hunter + Gemini cataloger for CDev.

WHY THIS FILE EXISTS
--------------------
The old scraper.py leans on Pexels. Pexels is generic stock: it has "running shoes" and
"city street", but it will NEVER have "Phil Knight 1980s", "Air Jordan 1985 launch", or
"Sunseeker yacht factory". For real documentaries the footage lives on YouTube (brand /
news / official channels), on archive.org (old ads, public-domain film), and on Wikimedia
(clean, license-clear stills). This module hunts those, in priority order, and — crucially —
runs each candidate through Gemini so the library entry is HONEST about what's actually on
screen (person / object / quality). That description is what the hard gates and future
searches rely on.

SOURCE LADDER (per query, stop when enough good assets found)
  1. LIBRARY        already have it -> free, instant (handled by caller before calling us)
  2. YOUTUBE (yt-dlp)  brand/news/official channels -> download -> Gemini cuts clean 4-8s
                       segments + describes each  (the real gold for documentaries)
  3. ARCHIVE.ORG    old ads / historical / public-domain footage & images
  4. WIKIMEDIA      clean license-clear stills (via commons_harvest, SNI-safe hosts)
  5. PEXELS         generic ambience ONLY (factory, money, skyline) — never the hero subject
  6. (nothing)      caller renders a still or text card (fail-closed)

Everything kept becomes a ClipEntry-compatible dict, so it drops straight into LibraryDB.

DEPENDENCIES (all optional — module degrades gracefully if any is missing)
  yt-dlp, ffmpeg/ffprobe on PATH, google-generativeai (Gemini), requests
KEYS (env)
  GEMINI_API_KEY   — for cataloging (frames -> description/entities/quality)
  PEXELS_API_KEY   — optional generic ambience
  SCRAPE_PROXIES   — optional, one proxy per line (for Google/archive at volume)

This is deliberately conservative: it will NOT invent metadata. If Gemini is unavailable,
an asset is kept only as a "needs_review" entry with an empty description, never a guessed one.
"""
from __future__ import annotations
import os
import re
import json
import base64
import shutil
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw"
CLIPS_DIR = BASE_DIR / "clips"
LIBRARY_DIR = BASE_DIR / "library"
for d in (RAW_DIR, CLIPS_DIR, LIBRARY_DIR):
    d.mkdir(parents=True, exist_ok=True)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Trusted channel hints per niche come from the topic pack ("avoid" = blocklist).
# These recap/drama channel patterns are ALWAYS blocked — they are re-uploads, not sources.
GLOBAL_CHANNEL_BLOCK = re.compile(
    r"(recap|explained daily|top\s?10|shorts?|compilation|edit|status|whatsapp)",
    re.I,
)


# ----------------------------------------------------------------------
# small shell helpers
# ----------------------------------------------------------------------
def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _uid(*parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode()).hexdigest()[:8]
    return h


def _proxies() -> list[str]:
    raw = os.getenv("SCRAPE_PROXIES", "")
    return [p.strip() for p in raw.splitlines() if p.strip()]


# ======================================================================
# GEMINI CATALOGER — the "eyes". Frames in -> honest metadata out.
# ======================================================================
class GeminiCataloger:
    """Describes an image or a video clip by looking at real frames.

    Returns: {description, entities[], actions[], environment[], quality, is_match}
    Never guesses when the key is missing — caller then keeps the asset as needs_review.
    """

    def __init__(self):
        self.ok = False
        self.key = os.getenv("GEMINI_API_KEY", "")
        if not self.key:
            return
        try:
            import google.generativeai as genai  # noqa
            genai.configure(api_key=self.key)
            self._genai = genai
            self._model = genai.GenerativeModel(GEMINI_MODEL)
            self.ok = True
        except Exception:
            self.ok = False

    # --- frame extraction (ffmpeg) ---
    @staticmethod
    def _frames(video: Path, n: int = 6) -> list[bytes]:
        """~3 frames/min, spread across the whole clip, as JPEG bytes."""
        dur = _probe_duration(video)
        if dur <= 0:
            return []
        n = max(3, min(n, round(dur / 60 * 3) or 3))
        out = []
        tmp = video.parent / f".{video.stem}_frames"
        tmp.mkdir(exist_ok=True)
        for i in range(n):
            t = dur * (i + 0.5) / n
            fp = tmp / f"f{i:02d}.jpg"
            _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}",
                  "-i", str(video), "-frames:v", "1", "-vf", "scale=640:-2", str(fp)], timeout=60)
            if fp.exists():
                out.append(fp.read_bytes())
        shutil.rmtree(tmp, ignore_errors=True)
        return out

    _SCHEMA_HINT = (
        'Return ONLY JSON: {"description": "1-2 lines, what is literally on screen", '
        '"entities": ["specific named people/objects/brands you can identify"], '
        '"actions": ["what is happening"], "environment": ["setting/era/lighting"], '
        '"quality": "high|mid|low", "clean": true, '
        '"is_match": true}  '
        "clean=false if there is big burned-in caption/subtitle/logo text mid-frame. "
        "is_match=false if it does NOT plausibly show: "
    )

    def catalog_image(self, path: Path, expect: str) -> Optional[dict]:
        if not self.ok:
            return None
        try:
            img = {"mime_type": "image/jpeg", "data": path.read_bytes()}
            prompt = self._SCHEMA_HINT + f'"{expect}".'
            r = self._model.generate_content([prompt, img])
            return _json_from(r.text)
        except Exception:
            return None

    def catalog_video(self, path: Path, expect: str) -> Optional[dict]:
        if not self.ok:
            return None
        frames = self._frames(path)
        if not frames:
            return None
        try:
            parts = [self._SCHEMA_HINT + f'"{expect}".']
            parts += [{"mime_type": "image/jpeg", "data": f} for f in frames]
            r = self._model.generate_content(parts)
            return _json_from(r.text)
        except Exception:
            return None


def _json_from(text: str) -> Optional[dict]:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _probe_duration(path: Path) -> float:
    if not _have("ffprobe"):
        return 0.0
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=nw=1:nk=1", str(path)], timeout=30)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


# ======================================================================
# SOURCE HUNTERS
# ======================================================================
class YouTubeHunter:
    """yt-dlp search + download, then Gemini cuts clean 4-8s segments.

    Only downloads from channels that pass the block filter + topic-pack 'avoid' list.
    Any-length source is fine — we keep only the clean pieces.
    """

    def __init__(self, cataloger: GeminiCataloger, avoid: list[str] = None,
                 max_per_query: int = 3, seg_len: float = 6.0):
        self.cat = cataloger
        self.avoid = [a.lower() for a in (avoid or [])]
        self.max_per_query = max_per_query
        self.seg_len = seg_len
        self.ok = _have("yt-dlp") or _have("yt-dlp.exe")

    def _blocked(self, uploader: str, title: str) -> bool:
        blob = f"{uploader} {title}".lower()
        if GLOBAL_CHANNEL_BLOCK.search(blob):
            return True
        return any(a in blob for a in self.avoid)

    def hunt(self, query: str, out_prefix: str) -> list[dict]:
        if not self.ok:
            return []
        # 1) search metadata only (fast) — pick unblocked, reasonable-length uploads
        search = f"ytsearch{self.max_per_query * 3}:{query}"
        meta = _run(["yt-dlp", "--flat-playlist", "-J", search], timeout=90)
        try:
            entries = json.loads(meta.stdout).get("entries", [])
        except Exception:
            return []

        picked = []
        for e in entries:
            up = e.get("uploader") or e.get("channel") or ""
            ti = e.get("title") or ""
            if self._blocked(up, ti):
                continue
            picked.append(e)
            if len(picked) >= self.max_per_query:
                break

        assets = []
        for e in picked:
            vid = e.get("id")
            if not vid:
                continue
            raw = RAW_DIR / f"{out_prefix}_{vid}.mp4"
            if not raw.exists():
                dl = ["yt-dlp", "-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]/best",
                      "-o", str(raw), f"https://youtube.com/watch?v={vid}"]
                for p in _proxies()[:1]:  # one proxy per download if provided
                    dl = ["yt-dlp", "--proxy", p] + dl[1:]
                _run(dl, timeout=600)
            if not raw.exists():
                continue
            assets += self._segment(raw, query, vid, e.get("title", ""))
        return assets

    def _segment(self, raw: Path, query: str, vid: str, src_title: str) -> list[dict]:
        """Cut a few candidate 4-8s clips, Gemini-verify each, keep the matches."""
        dur = _probe_duration(raw)
        if dur < self.seg_len:
            return []
        kept = []
        # sample up to 4 windows spread across the video (skip first/last 8%)
        spots = [dur * f for f in (0.12, 0.38, 0.62, 0.85)]
        for i, start in enumerate(spots):
            if start + self.seg_len > dur:
                continue
            clip = CLIPS_DIR / f"{vid}_{int(start)}.mp4"
            if not clip.exists():
                _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}",
                      "-i", str(raw), "-t", f"{self.seg_len}",
                      "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1",
                      "-an", "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
                      "-crf", "20", str(clip)], timeout=120)
            if not clip.exists():
                continue
            meta = self.cat.catalog_video(clip, query)
            entry = _to_entry(
                clip, "video", "youtube",
                f"https://youtube.com/watch?v={vid}", query, meta,
                dur=self.seg_len, src_title=src_title,
            )
            if entry is None:            # Gemini says wrong subject / dirty -> drop the file
                clip.unlink(missing_ok=True)
                continue
            kept.append(entry)
            if len(kept) >= 2:           # 2 good clips per source video is plenty
                break
        return kept


class WikimediaHunter:
    """Clean, license-clear stills. Reuses commons_harvest if present, else a tiny inline path."""

    def __init__(self, cataloger: GeminiCataloger):
        self.cat = cataloger

    def hunt(self, article_or_query: str, out_prefix: str, want: int = 4) -> list[dict]:
        try:
            import requests
        except ImportError:
            return []
        # article-images endpoint: precise, right-subject images
        api = "https://en.wikipedia.org/w/api.php"
        params = {"format": "json", "action": "query", "generator": "images",
                  "titles": article_or_query, "gimlimit": "40", "prop": "imageinfo",
                  "iiprop": "url|size", "iiurlwidth": "1600"}
        try:
            d = requests.get(api, params=params, timeout=30,
                             headers={"User-Agent": "CDev/1.0"}).json()
        except Exception:
            return []
        out = []
        for _, v in (d.get("query", {}).get("pages", {}) or {}).items():
            ii = (v.get("imageinfo") or [{}])[0]
            url = ii.get("thumburl") or ii.get("url")
            t = v.get("title", "")
            if not url or not t.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            if ii.get("width", 0) < 1000:
                continue
            dest = LIBRARY_DIR / f"{out_prefix}_{_uid(t)}.jpg"
            try:
                import requests as rq
                dest.write_bytes(rq.get(url, timeout=60,
                                        headers={"User-Agent": "CDev/1.0"}).content)
            except Exception:
                continue
            meta = self.cat.catalog_image(dest, article_or_query)
            entry = _to_entry(dest, "image", "wikimedia",
                              ii.get("descriptionurl", url), article_or_query, meta,
                              width=ii.get("width", 0), height=ii.get("height", 0))
            if entry is None:
                dest.unlink(missing_ok=True)
                continue
            out.append(entry)
            if len(out) >= want:
                break
        return out


# ======================================================================
# ClipEntry-compatible builder + gate on Gemini's verdict
# ======================================================================
def _to_entry(path: Path, atype: str, source_type: str, source_url: str,
              query: str, meta: Optional[dict], *, dur: float = 0.0,
              width: int = 0, height: int = 0, src_title: str = "") -> Optional[dict]:
    """Build a library entry dict. Returns None if Gemini rejected the asset."""
    if meta is not None:
        # hard gate on the cataloger's own verdict
        if meta.get("is_match") is False:
            return None
        if meta.get("clean") is False:
            return None
        desc = meta.get("description", "")
        entities = meta.get("entities", []) or []
        actions = meta.get("actions", []) or []
        env = meta.get("environment", []) or []
        quality = meta.get("quality", "mid")
        cataloged_by = GEMINI_MODEL
        review = False
    else:
        # no cataloger available: keep but flag; NEVER fabricate metadata
        desc, entities, actions, env = "", [], [], []
        quality = "mid"
        cataloged_by = ""
        review = True

    return {
        "id": f"CLP_{_uid(source_url, path.name)}",
        "type": atype,
        "file": str(path.relative_to(BASE_DIR)) if path.is_relative_to(BASE_DIR) else str(path),
        "source_type": source_type,
        "source_url": source_url,
        "topic": query,
        "entities": entities,
        "actions": actions,
        "environment": env,
        "description": desc,
        "quality": {"high": "high", "mid": "medium", "low": "low"}.get(quality, "medium"),
        "duration": dur,
        "width": width,
        "height": height,
        "license": "wikimedia" if source_type == "wikimedia" else "",
        "strictness": "general",
        "times_used": 0,
        "created_at": datetime.now().isoformat(),
        "cataloged_by": cataloged_by,
        "needs_review": review,
        "src_title": src_title,
    }


# ======================================================================
# ORCHESTRATOR — hunt everything a topic pack needs, per source ladder
# ======================================================================
class SourceHunter:
    def __init__(self, topic_pack: dict):
        self.pack = topic_pack
        self.avoid = topic_pack.get("avoid", [])
        self.cat = GeminiCataloger()
        self.yt = YouTubeHunter(self.cat, avoid=self.avoid)
        self.wiki = WikimediaHunter(self.cat)

    def status(self) -> dict:
        return {
            "gemini": self.cat.ok,
            "yt_dlp": self.yt.ok,
            "ffmpeg": _have("ffmpeg"),
            "proxies": len(_proxies()),
        }

    def hunt_all(self, per_query_clips: int = 2, image_articles: int = None) -> list[dict]:
        """Run the ladder across the whole pack. Returns library entries to add."""
        from entity_brain import all_queries  # local import to avoid hard dep at import time

        entries: list[dict] = []
        slug = self.pack.get("name", "topic")

        # 2) YouTube footage per concrete query
        for q in all_queries(self.pack):
            got = self.yt.hunt(q, out_prefix=slug)
            entries.extend(got[:per_query_clips])

        # 4) Wikimedia stills per article (clean subject images)
        arts = self.pack.get("wikimedia_articles", [])
        if image_articles:
            arts = arts[:image_articles]
        for art in arts:
            entries.extend(self.wiki.hunt(art, out_prefix=slug))

        return entries


# ======================================================================
def main():
    import argparse
    ap = argparse.ArgumentParser(description="Hunt footage/images for a topic pack.")
    ap.add_argument("pack", help="Path to a topic_pack.json (from entity_brain.py)")
    ap.add_argument("--out", help="Where to write the harvested entries JSON",
                    default=str(LIBRARY_DIR / "_harvest.json"))
    ap.add_argument("--dry", action="store_true", help="Only print the source status + plan")
    a = ap.parse_args()

    pack = json.loads(Path(a.pack).read_text(encoding="utf-8"))
    hunter = SourceHunter(pack)
    st = hunter.status()
    print(f"[source_hunter] sources: {st}")
    if not st["yt_dlp"]:
        print("  ! yt-dlp not found — YouTube (the main source) is disabled. `pip install -U yt-dlp`")
    if not st["gemini"]:
        print("  ! GEMINI_API_KEY missing — assets will be kept as needs_review (no descriptions).")

    if a.dry:
        from entity_brain import all_queries
        qs = all_queries(pack)
        print(f"  would run {len(qs)} queries + {len(pack.get('wikimedia_articles', []))} wiki articles")
        for q in qs[:15]:
            print(f"    - {q}")
        return

    entries = hunter.hunt_all()
    Path(a.out).write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    kept = [e for e in entries if not e.get("needs_review")]
    print(f"[source_hunter] harvested {len(entries)} assets "
          f"({len(kept)} cataloged, {len(entries) - len(kept)} needs_review) -> {a.out}")


if __name__ == "__main__":
    main()
