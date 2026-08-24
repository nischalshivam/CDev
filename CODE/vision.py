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

    _PROMPT = ("Describe this single documentary video frame. Return ONLY JSON: "
               '{"description":"1 line, literal; name any car make/model or subject",'
               '"entities":[named things],"actions":[what happens],"environment":[setting],'
               '"quality":"low|medium|high","clean_status":"clean|fixable|unusable",'
               '"logo_box":[x,y,w,h] or null,"match_conf":0.0_to_1.0}. '
               "clean_status='fixable' + logo_box for a corner logo/subscribe/watermark; "
               "'unusable' if a caption covers the subject; else 'clean'.")

    def _describe(self, jpg_bytes) -> dict:
        import base64, urllib.request
        b64 = base64.b64encode(jpg_bytes).decode()
        body = {"model": self.model, "max_tokens": 300, "messages": [{"role": "user", "content": [
            {"type": "text", "text": self._PROMPT},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}]}
        req = urllib.request.Request(self.base + "/chat/completions",
              data=json.dumps(body).encode(),
              headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        d = json.load(urllib.request.urlopen(req, timeout=120))
        txt = d["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", txt, re.S)
        return json.loads(m.group(0)) if m else {}

    def _scene_cuts(self, video_path, thresh=0.35) -> list[float]:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video_path), "-filter:v",
                            f"select='gt(scene,{thresh})',showinfo", "-an", "-f", "null", "-"],
                           capture_output=True, text=True)
        return sorted(float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr))

    def _midframe(self, video_path, t) -> bytes:
        import tempfile, pathlib
        fp = pathlib.Path(tempfile.mktemp(suffix=".jpg"))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video_path),
                        "-frames:v", "1", "-vf", "scale=768:-2", str(fp)], capture_output=True)
        b = fp.read_bytes() if fp.exists() else b""
        if fp.exists():
            fp.unlink()
        return b

    def analyze(self, video_path) -> list[dict]:
        if not self.ok:
            raise RuntimeError("RelayVision not configured (set GEMINI_RELAY_* in keys.env)")
        dur = _duration(video_path)
        cuts = self._scene_cuts(video_path)
        bounds = [0.0] + cuts + [dur]
        shots = []
        for a, b in zip(bounds, bounds[1:]):
            if b - a < 1.5:
                continue
            shots.append((a, min(b, a + config.MAX_CLIP_SECONDS)))   # cap at <=7s
        if len(shots) < 3:                                            # fallback: fixed windows
            shots = [(t, min(t + 6, dur)) for t in range(0, int(dur), 6) if dur - t >= 1.5]
        segs = []
        for a, b in shots:
            frame = self._midframe(video_path, (a + b) / 2)
            if not frame:
                continue
            try:
                meta = self._describe(frame)
            except Exception:
                continue
            segs.append({"start_ms": int(a * 1000), "end_ms": int(b * 1000),
                         "description": meta.get("description", ""),
                         "entities": meta.get("entities", []), "actions": meta.get("actions", []),
                         "environment": meta.get("environment", []),
                         "quality": meta.get("quality", "medium"),
                         "clean_status": meta.get("clean_status", "clean"),
                         "match_conf": float(meta.get("match_conf", 0.8) or 0.8),
                         "logo_box": meta.get("logo_box")})
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
