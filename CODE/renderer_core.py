#!/usr/bin/env python3
"""
renderer_core.py — a small, CORRECT ffmpeg renderer for a timeline.

The legacy renderer mapped [v0][v1]... straight to output with no concat, which produces an invalid
graph. This builds ONE valid filter_complex: per-shot scale/crop (+ Ken Burns on stills) -> xfade
transition chain -> a single [vout], muxed with the voiceover. Proven with SYNTHETIC ffmpeg
fixtures (testsrc / color / sine) so correctness (concat, xfade, duration, audio-map, playable MP4)
is testable WITHOUT any real footage.

A timeline segment:
  {"file": path, "kind": "video"|"image", "duration": secs, "transition": "fade"|"slideleft"|...}
"""
from __future__ import annotations
import subprocess
from pathlib import Path

W, H, FPS, TD = 1920, 1080, 30, 0.5      # TD = transition duration (s)


def _have_ffmpeg() -> bool:
    import shutil
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def probe_duration(path: str | Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _shot_chain(i: int, seg: dict) -> str:
    dur = seg["duration"]
    if seg["kind"] == "image":
        n = int(dur * FPS)
        pre = (f"scale={W*4}:-2,zoompan=z='min(zoom+0.0006,1.12)':d={n}:"
               f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},setsar=1")
    else:
        pre = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
               f"zoompan=z='min(zoom+0.00035,1.06)':d=1:x='iw/2-(iw/zoom/2)':"
               f"y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},setsar=1")
    return f"[{i}:v]{pre},trim=duration={dur},setpts=PTS-STARTPTS[v{i}]"


def build_filtergraph(segments: list[dict]) -> tuple[list[str], str, float]:
    """Return (per-shot chains, final label, total_duration). One valid [vout], xfade-chained."""
    fc = [_shot_chain(i, s) for i, s in enumerate(segments)]
    if len(segments) == 1:
        fc.append("[v0]format=yuv420p[vout]")
        return fc, "[vout]", segments[0]["duration"]
    cur = "[v0]"
    off = segments[0]["duration"] - TD
    total = segments[0]["duration"]
    for i in range(1, len(segments)):
        tr = segments[i - 1].get("transition") or "fade"
        out = f"[x{i}]"
        fc.append(f"{cur}[v{i}]xfade=transition={tr}:duration={TD}:offset={off:.3f}{out}")
        cur = out
        off += segments[i]["duration"] - TD
        total += segments[i]["duration"] - TD
    fc.append(f"{cur}format=yuv420p[vout]")
    return fc, "[vout]", total


def render_timeline(segments: list[dict], out_path: str | Path, audio_path: str | Path = None,
                    fps: int = FPS) -> dict:
    """Render the timeline to a single MP4. Returns {out, duration, ok}."""
    if not _have_ffmpeg():
        raise RuntimeError("ffmpeg/ffprobe not found on PATH")
    if not segments:
        raise ValueError("no segments to render")

    inputs: list[str] = []
    for s in segments:
        if s["kind"] == "image":
            inputs += ["-loop", "1", "-t", str(s["duration"]), "-i", str(s["file"])]
        else:
            inputs += ["-i", str(s["file"])]

    fc, vout, total = build_filtergraph(segments)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"] + inputs

    maps = ["-map", vout]
    if audio_path:
        cmd += ["-i", str(audio_path)]
        maps += ["-map", f"{len(segments)}:a"]
        acodec = ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    else:
        acodec = ["-an"]

    cmd += ["-filter_complex", ";".join(fc)] + maps + [
        "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart"] + acodec + [str(out_path)]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-600:]}")
    return {"out": str(out_path), "duration": probe_duration(out_path),
            "expected": round(total, 2), "ok": Path(out_path).exists()}


# ---- synthetic fixtures (for tests / smoke, no real footage) -----------------
def make_fixtures(d: str | Path) -> dict:
    """testsrc video clips + a color still + a sine wav — enough to prove the renderer."""
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    clips = []
    for i, color in enumerate(["red", "green", "blue"]):
        p = d / f"clip{i}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"testsrc=size=640x360:rate=30:duration=3", "-t", "3",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)], check=True)
        clips.append(str(p))
    img = d / "still.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "color=c=orange:size=800x600", "-frames:v", "1", str(img)], check=True)
    wav = d / "voice.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=220:duration=6", "-t", "6", str(wav)], check=True)
    return {"clips": clips, "image": str(img), "audio": str(wav)}


if __name__ == "__main__":
    import tempfile
    tmp = tempfile.mkdtemp()
    fx = make_fixtures(tmp)
    segs = [{"file": fx["clips"][0], "kind": "video", "duration": 2.5, "transition": "slideleft"},
            {"file": fx["image"], "kind": "image", "duration": 2.0, "transition": "fade"},
            {"file": fx["clips"][1], "kind": "video", "duration": 2.5}]
    out = Path(tmp) / "out.mp4"
    print(render_timeline(segs, out, audio_path=fx["audio"]))
