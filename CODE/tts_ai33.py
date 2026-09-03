#!/usr/bin/env python3
"""
tts_ai33.py — voiceover via ai33.pro, WITH word-level timestamps.

Why this matters more than "we can make audio": the API returns a word-level JSON alongside the
mp3. That kills the whole transcription-error class. Previously we ran Whisper over a supplied
voiceover and it produced "Galata" for "Golota" and "lost Vegas" for "Las Vegas" — those errors
flowed straight into the clue script and therefore into wrong clip searches. With TTS we already
KNOW the exact text and get exact word times, so the locked trio (script = audio = beats) holds by
construction.

    from tts_ai33 import speak
    r = speak(script_text, out_dir)        # -> {"audio": ..., "words": [...], "duration": secs}

Verified against the live API: POST /v3/text-to-speech (multipart) -> task_id, then poll
GET /v3/task/{id} until status == "done"; metadata carries audio_url / srt_url / json_url.
A browser User-Agent is REQUIRED on every call (Cloudflare 403s the default urllib UA).
"""
from __future__ import annotations
import io
import json
import time
import uuid
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

import config

BASE = "https://api.ai33.pro"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
SPEED = "0.95"                       # tested read speed — steadier than 1.0
MAX_WORDS = 220                      # never submit the whole script in one call


def _headers(extra=None):
    h = {"xi-api-key": config.AI33_KEY, "User-Agent": UA}
    h.update(extra or {})
    return h


def _multipart(fields: dict):
    b = "----CDev" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n")
    parts.append(f"--{b}--\r\n")
    return "".join(parts).encode("utf-8"), b


def _submit(text: str, voice_id: str) -> str:
    body, b = _multipart({"text": text, "voice_id": voice_id,
                          "speed": SPEED, "with_transcript": "true"})
    req = urllib.request.Request(f"{BASE}/v3/text-to-speech", data=body, method="POST",
                                 headers=_headers({"Content-Type":
                                                   f"multipart/form-data; boundary={b}"}))
    d = json.load(urllib.request.urlopen(req, timeout=120))
    if not d.get("task_id"):
        raise RuntimeError(f"ai33 submit failed: {str(d)[:200]}")
    return d["task_id"]


def _poll(task_id: str, timeout_s: int = 600) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        req = urllib.request.Request(f"{BASE}/v3/task/{task_id}", headers=_headers())
        d = json.load(urllib.request.urlopen(req, timeout=60))
        data = d.get("data") or {}
        st = data.get("status")
        if st == "done":
            return data.get("metadata") or {}
        if st in ("failed", "error"):
            raise RuntimeError(f"ai33 task failed: {str(d)[:200]}")
        time.sleep(3)
    raise TimeoutError(f"ai33 task {task_id} did not finish")


def _get(url: str) -> bytes:
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180).read()


def _chunks(text: str, max_words: int = MAX_WORDS) -> list[str]:
    """Split on blank lines, then pack paragraphs up to max_words. Never split mid-sentence."""
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    out, cur, n = [], [], 0
    for p in paras:
        w = len(p.split())
        if cur and n + w > max_words:
            out.append("\n".join(cur)); cur, n = [], 0
        cur.append(p); n += w
    if cur:
        out.append("\n".join(cur))
    return out


def _duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nk=1:nw=1", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def speak(text: str, out_dir, voice_id: str = None, progress=print) -> dict:
    """TTS the whole script. Chunks -> per-chunk mp3 + word json -> concat -> ONE timeline.

    Returns {"audio": path, "words": [{"w","s","e"}...], "duration": secs, "chunks": n}.
    Word times are stitched onto the global timeline using each chunk's MEASURED duration
    (ffprobe), not the model's estimate."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    voice_id = voice_id or config.AI33_VOICE
    parts = _chunks(text)
    progress(f"[tts] {len(text.split())} words -> {len(parts)} chunks")

    mp3s, words, offset = [], [], 0.0
    for i, part in enumerate(parts):
        tid = _submit(part, voice_id)
        md = _poll(tid)
        mp3 = out_dir / f"chunk{i:02d}.mp3"
        mp3.write_bytes(_get(md["audio_url"]))
        mp3s.append(mp3)
        dur = _duration(mp3)
        try:
            wj = json.loads(_get(md["json_url"]).decode("utf-8"))
            for blk in (wj if isinstance(wj, list) else [wj]):
                for w in blk.get("words", []):
                    if w.get("type") != "word":
                        continue
                    words.append({"w": w["text"].strip(),
                                  "s": round(offset + float(w["start"]), 3),
                                  "e": round(offset + float(w["end"]), 3)})
        except Exception as e:                       # audio still usable without word times
            progress(f"[tts] chunk {i}: word json unavailable ({str(e)[:50]})")
        offset += dur
        # PERSIST AFTER EVERY CHUNK. Paid-API results must survive a later local failure — an
        # ffmpeg concat error once destroyed a full run's word timings because they were only
        # written at the end.
        with io.open(out_dir / "words.json", "w", encoding="utf-8") as f:
            json.dump(words, f, ensure_ascii=False)
        progress(f"[tts] chunk {i+1}/{len(parts)}  {dur:6.1f}s  (total {offset:6.1f}s)")

    lst = out_dir / "concat.txt"
    with io.open(lst, "w", encoding="utf-8") as f:
        for m in mp3s:
            # ABSOLUTE paths: the concat demuxer resolves relative entries against the LIST file's
            # own directory, so relative paths silently look in the wrong place.
            f.write(f"file '{m.resolve().as_posix()}'\n")
    audio = out_dir / "voiceover.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(audio)], check=True)
    total = _duration(audio)
    progress(f"[tts] done: {audio.name}  {total:.1f}s  {len(words)} word timings")
    return {"audio": str(audio), "words": words, "duration": total, "chunks": len(parts)}


if __name__ == "__main__":
    import sys
    src = Path(sys.argv[1]); out = sys.argv[2] if len(sys.argv) > 2 else "vo_out"
    print(speak(src.read_text(encoding="utf-8"), out)["duration"])
