#!/usr/bin/env python3
"""
vision.py — the pluggable "eyes". A vision client turns a source video into candidate SEGMENTS,
each honestly described. Prod uses Gemini; tests use FakeVision (deterministic, zero spend).

analyze(video_path) -> list of segment dicts:
  {start_ms, end_ms, description, entities[], actions[], environment[], era_from?, era_to?,
   quality: low|medium|high, clean_status: clean|fixable|unusable, match_conf: 0..1,
   logo_box?: [x,y,w,h]}   # logo_box present when a corner logo/watermark should be blurred
"""
from __future__ import annotations
import os
import re
import json
import subprocess

import config


def _duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


class FakeVision:
    """Deterministic stand-in for tests/offline: one ~6s segment per 6s of source."""
    name = "fake-vision"

    def analyze(self, video_path) -> list[dict]:
        dur = _duration(video_path) or 6.0
        segs = []
        n = max(1, int(dur // 6))
        for i in range(n):
            start = int(i * 6 * 1000)
            segs.append({
                "start_ms": start, "end_ms": start + 6000,
                "description": f"synthetic scene {i}: a subject in a plain setting",
                "entities": ["TEST_ENTITY"], "actions": ["standing"],
                "environment": ["studio"], "quality": "high",
                "clean_status": "fixable" if i == 0 else "clean",
                "match_conf": 0.9,
                "logo_box": [560, 10, 70, 24] if i == 0 else None,
            })
        return segs


class RelayVision:
    """OpenAI-compatible relay (openlux/yunwu) vision cataloger. Scene-detects a source video,
    then describes each shot's middle frame with gemini-2.5-flash. Returns virtual segments."""
    def __init__(self, base=None, key=None, model=None):
        self.base = (base or config.GEMINI_RELAY_BASE).rstrip("/")
        self.key = key or config.GEMINI_RELAY_KEY
        self.model = model or config.GEMINI_RELAY_MODEL
        self.name = f"relay:{self.model}"
        self.ok = bool(self.base and self.key)

    # richer prompt (FOOTAGE-WORKFLOW lessons): serves + 6-shape keywords + talking_head + NAMES.
    _PROMPT = (
        "You are cataloging documentary footage. Look at these frames of ONE shot and return ONLY "
        "JSON: {"
        '"description":"1 line, literal; name any make/model or subject",'
        '"keywords":["8-15 words covering subject, shot-type, camera, light/mood, colour, use"],'
        '"shot":"wide|medium|close-up|extreme close-up",'
        '"camera":"static|pan|tilt|push|pull|handheld|aerial",'
        '"objects":[things],"places":[settings],'
        '"people":["ONLY names/roles of people ACTUALLY VISIBLE in frame — [] if none"],'
        '"serves":["what a narrator could say over this — e.g. a fresh start, passage of time"],'
        '"entities":[named things],"actions":[what happens],"environment":[setting/era],'
        '"talking_head":true_if_someone_speaks_straight_to_camera_studio_or_piece_to_camera,'
        '"quality":"low|medium|high","clean_status":"clean|fixable|unusable",'
        '"logo_box":[x,y,w,h]_or_null,"match_conf":0.0_to_1.0}. '
        "Rules: people must list only who is VISIBLE (a title is not proof). clean_status='fixable' "
        "+ logo_box for a corner logo/subscribe/watermark; 'unusable' if a caption covers the "
        "subject; else 'clean'. Judge across BOTH frames and report the WORST case.")

    def _describe(self, frames: list[bytes]) -> dict:
        import base64, urllib.request
        content = [{"type": "text", "text": self._PROMPT}]
        for f in frames:
            content.append({"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(f).decode()}})
        body = {"model": self.model, "max_tokens": 500, "messages": [{"role": "user", "content": content}]}
        req = urllib.request.Request(self.base + "/chat/completions",
              data=json.dumps(body).encode(),
              headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        d = json.load(urllib.request.urlopen(req, timeout=120))
        m = re.search(r"\{.*\}", d["choices"][0]["message"]["content"], re.S)
        return json.loads(m.group(0)) if m else {}

    def _frame_at(self, video_path, t) -> bytes:
        import tempfile, pathlib
        fp = pathlib.Path(tempfile.mktemp(suffix=".jpg"))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video_path),
                        "-frames:v", "1", "-vf", "scale=768:-2", str(fp)], capture_output=True)
        b = fp.read_bytes() if fp.exists() else b""
        if fp.exists():
            fp.unlink()
        return b

    def analyze(self, video_path) -> list[dict]:
        """Cheap-first: local HD/cut/motion gates, then Gemini ONLY on segments that survive.
        Skips talking-head shots. Samples 2 moments/segment and reports the worst (captions can
        appear late; a frame is not a measurement)."""
        if not self.ok:
            raise RuntimeError("RelayVision not configured (set GEMINI_RELAY_* in keys.env)")
        import media_probe
        plan = media_probe.segment_video(video_path, max_seconds=config.MAX_CLIP_SECONDS)
        base_q = "high" if plan["hd"] else "low"
        segs = []
        for sh in plan["segments"]:
            if not sh["usable"]:                       # frozen/short — never spend vision on it
                continue
            a, b = sh["start"], sh["end"]
            frames = [f for f in (self._frame_at(video_path, a + (b - a) * r) for r in (0.25, 0.65)) if f]
            if not frames:
                continue
            try:
                meta = self._describe(frames)
            except Exception:
                continue
            if meta.get("talking_head"):               # presenter/anchor — not a real scene
                continue
            q = meta.get("quality", base_q)
            if not plan["hd"] and q == "high":         # a sub-HD source can't be 'high'
                q = "medium"
            segs.append({"start_ms": int(a * 1000), "end_ms": int(b * 1000),
                         "description": meta.get("description", ""),
                         "keywords": meta.get("keywords", []),
                         "entities": meta.get("entities", []), "actions": meta.get("actions", []),
                         "environment": meta.get("environment", []),
                         "objects": meta.get("objects", []), "places": meta.get("places", []),
                         "people": meta.get("people", []), "serves": meta.get("serves", []),
                         "shot": meta.get("shot", ""), "camera": meta.get("camera", ""),
                         "quality": q, "clean_status": meta.get("clean_status", "clean"),
                         "match_conf": float(meta.get("match_conf", 0.8) or 0.8),
                         "motion": sh["motion"], "logo_box": meta.get("logo_box")})
        return segs


class GeminiVision:
    """Real Gemini cataloger. Not exercised by tests (no spend). Frames -> structured segments."""
    name = config.GEMINI_MODEL

    def __init__(self):
        self.ok = False
        key = os.getenv("GEMINI_API_KEY", "")
        if not key:
            return
        try:
            import google.generativeai as genai
            genai.configure(api_key=key)
            self._model = genai.GenerativeModel(config.GEMINI_MODEL)
            self.ok = True
        except Exception:
            self.ok = False

    _PROMPT = (
        "You are cataloging a source video for a documentary library. Return ONLY JSON: a list of "
        "4-8 second candidate segments, each: {start_ms,end_ms,description,entities,actions,"
        "environment,quality(low|medium|high),clean_status(clean|fixable|unusable),match_conf(0..1),"
        "logo_box:[x,y,w,h] or null}. clean_status='fixable' + logo_box when a corner logo/"
        "subscribe/watermark is present (it can be blurred); 'unusable' when a caption covers the "
        "subject; else 'clean'. Be honest; do not invent entities."
    )

    def analyze(self, video_path) -> list[dict]:
        if not self.ok:
            raise RuntimeError("GeminiVision unavailable (set GEMINI_API_KEY, install google-generativeai)")
        dur = _duration(video_path)
        frames = self._frames(video_path, max(3, min(24, int(dur / 5) or 3)))
        parts = [self._PROMPT] + [{"mime_type": "image/jpeg", "data": f} for f in frames]
        r = self._model.generate_content(parts)
        m = re.search(r"\[.*\]", r.text, re.S)
        return json.loads(m.group(0)) if m else []

    @staticmethod
    def _frames(video_path, n) -> list[bytes]:
        import tempfile, pathlib
        dur = _duration(video_path)
        out = []
        tmp = pathlib.Path(tempfile.mkdtemp())
        for i in range(n):
            t = dur * (i + 0.5) / n
            fp = tmp / f"f{i}.jpg"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}",
                            "-i", str(video_path), "-frames:v", "1", "-vf", "scale=640:-2", str(fp)],
                           capture_output=True)
            if fp.exists():
                out.append(fp.read_bytes())
        return out
