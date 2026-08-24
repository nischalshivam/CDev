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
