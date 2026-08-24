#!/usr/bin/env python3
"""
cataloger.py — turn a source video into cataloged, retrievable SEGMENTS in the Catalog.

Flow (per source):
  ingest master object (SHA-256, stored once)
  -> cache lookup on (content_hash + model + prompt_version + schema_version)   [never re-charge]
  -> vision.analyze() gives candidate segments (Gemini in prod, FakeVision in tests)
  -> write each as a VIRTUAL segment asset (timestamps only; clip cut later on assignment)
  -> full-auto approval guard (clean/fixable + confidence + file exists)

Segments are stored VIRTUAL (start_ms/end_ms). `materialize()` cuts the actual <=7s clip only when
a segment is chosen for a render, and applies delogo/blur if the segment is 'fixable' with a box.
"""
from __future__ import annotations
import subprocess
from pathlib import Path

import config
from vision import FakeVision


class Cataloger:
    def __init__(self, catalog, vision=None):
        self.cat = catalog
        self.vision = vision or FakeVision()

    def _cache_key(self, sha: str) -> str:
        return f"{sha}|{getattr(self.vision, 'name', '?')}|{config.CATALOG_PROMPT_VERSION}|{config.CATALOG_SCHEMA_VERSION}"

    def catalog_source(self, video_path, source_id: str, url: str = "", *, channel: str = "",
                       collections: list = None, entity_map: dict = None) -> dict:
        """Catalog one source video into segment assets. Idempotent + cached.
        entity_map maps a vision entity string -> canonical id; unmapped ones are kept as-is."""
        obj = self.cat.ingest_file(video_path)
        key = self._cache_key(obj["sha256"])
        cached = self.cat.get_cache(key)
        if cached is not None:
            segs, cache_hit = cached, True
        else:
            segs = self.vision.analyze(video_path)
            self.cat.put_cache(key, segs)
            cache_hit = False

        self.cat.add_source(source_id, url, kind="video", content_hash=obj["sha256"], channel=channel)

        cap_ms = int(config.MAX_CLIP_SECONDS * 1000)
        added = []
        for s in segs:
            start = int(s["start_ms"])
            end = min(int(s["end_ms"]), start + cap_ms)     # copyright posture: <=7s
            if end <= start:
                continue
            aid = f"AST_{obj['sha256'][:8]}_{start}"
            # link ONLY entities that resolve to a known canonical id (via entity_map or alias);
            # unknown vision strings are kept raw for later canonicalization (keeps the graph clean
            # and avoids linking to non-existent entities).
            raw = s.get("entities", [])
            ents, unresolved = [], []
            for e in raw:
                cid = (entity_map or {}).get(e) or self.cat.resolve_alias(e)
                (ents if cid else unresolved).append(cid or e)
            ok = self.cat.add_asset(
                aid, "video", source_id=source_id, start_ms=start, end_ms=end,
                description=s.get("description", ""),
                era_from=s.get("era_from"), era_to=s.get("era_to"),
                quality=s.get("quality", "medium"), clean_status=s.get("clean_status", "clean"),
                match_conf=float(s.get("match_conf", 0.0)), review_status="needs_review",
                entities=ents, collections=collections or [],
                catalog={"actions": s.get("actions", []), "environment": s.get("environment", []),
                         "raw_entities": unresolved, "logo_box": s.get("logo_box"),
                         "model": getattr(self.vision, "name", "?")})
            if ok:
                self.cat.auto_approve(aid)
                added.append(aid)
        return {"source_id": source_id, "sha256": obj["sha256"], "cache_hit": cache_hit,
                "segments": len(segs), "added": added}

    # ---- materialize a chosen segment (cut <=7s, delogo if fixable) --------
    def materialize(self, asset_id: str, out_path) -> dict:
        r = self.cat.cx.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        if r is None:
            raise KeyError(asset_id)
        sha = self.cat._asset_object_sha(r)
        src = self.cat.object_path(sha)
        if not (src and src.exists()):
            raise FileNotFoundError(f"master object missing for {asset_id}")
        start = (r["start_ms"] or 0) / 1000.0
        dur = min(((r["end_ms"] or 0) - (r["start_ms"] or 0)) / 1000.0, config.MAX_CLIP_SECONDS)
        import json as _json
        box = (_json.loads(r["catalog_json"] or "{}") or {}).get("logo_box")
        vf = []
        if r["clean_status"] == "fixable" and box:
            x, y, w, h = box
            vf.append(f"delogo=x={x}:y={y}:w={w}:h={h}")
        def run(with_vf):
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-i", str(src),
                   "-t", f"{dur:.2f}"]
            if with_vf and vf:
                cmd += ["-vf", ",".join(vf)]
            cmd += ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out_path)]
            return subprocess.run(cmd, capture_output=True, text=True)

        rr = run(True)
        used_delogo = bool(vf)
        if rr.returncode != 0 and vf:            # a bad logo_box breaks delogo -> retry clean
            rr = run(False); used_delogo = False
        if rr.returncode != 0:
            raise RuntimeError(f"materialize failed: {rr.stderr[-400:]}")
        return {"asset_id": asset_id, "out": str(out_path), "seconds": round(dur, 2),
                "delogo": used_delogo}
