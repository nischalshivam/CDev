#!/usr/bin/env python3
"""Tests for cheap-first local measures (HD gate, histogram cuts, motion/frozen)."""
import os, shutil, subprocess, tempfile
import pytest
import media_probe as MP

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                reason="ffmpeg not on PATH")


def _mk(path, spec, dur=3, extra=None):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", spec,
                    "-t", str(dur), *(extra or []), "-pix_fmt", "yuv420p", path], check=True)
    return path


def test_hd_gate():
    assert MP.passes_hd({"width": 1920, "height": 1080})[0] is True
    assert MP.passes_hd({"width": 640, "height": 360})[0] is False        # width < 1280
    assert MP.passes_hd({"width": 720, "height": 1280})[0] is False       # portrait (w<=h)
    assert MP.passes_hd({})[0] is False


def test_probe_real_file():
    d = tempfile.mkdtemp()
    p = _mk(os.path.join(d, "hd.mp4"), "testsrc=size=1280x720:rate=30:duration=3")
    info = MP.probe(p)
    assert info["width"] == 1280 and info["height"] == 720 and info["dur"] > 2.5
    assert MP.passes_hd(info)[0] is True


def test_find_cuts_detects_shot_changes():
    d = tempfile.mkdtemp()
    parts = []
    for i, col in enumerate(["red", "green", "blue"]):
        parts.append(_mk(os.path.join(d, f"{i}.mp4"),
                         f"color=c={col}:size=640x360:rate=10", dur=2))
    lst = os.path.join(d, "l.txt")
    open(lst, "w").write("\n".join(f"file '{p}'" for p in parts))
    joined = os.path.join(d, "j.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", joined], check=True)
    cuts = MP.find_cuts(joined)
    assert cuts is not None and len(cuts) >= 2          # two colour changes


def test_find_cuts_missing_file_returns_none():
    assert MP.find_cuts("/nonexistent/x.mp4") is None   # None, not [] (failure != "one shot")


def test_motion_moving_vs_frozen():
    d = tempfile.mkdtemp()
    moving = _mk(os.path.join(d, "mv.mp4"), "testsrc=size=640x360:rate=30:duration=3")
    frozen = _mk(os.path.join(d, "fz.mp4"), "color=c=gray:size=640x360:rate=30", dur=3)
    assert MP.motion_ok(MP.measure_motion(moving))[0] is True
    assert MP.motion_ok(MP.measure_motion(frozen))[0] is False   # frozen -> dropped


def test_segment_video_cheap_first():
    d = tempfile.mkdtemp()
    parts = [_mk(os.path.join(d, f"{i}.mp4"), f"testsrc=size=1280x720:rate=30", dur=3)
             for i in range(2)]
    lst = os.path.join(d, "l.txt"); open(lst, "w").write("\n".join(f"file '{p}'" for p in parts))
    joined = os.path.join(d, "j.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", joined], check=True)
    r = MP.segment_video(joined)
    assert r["hd"] is True
    assert len(r["segments"]) >= 1
    assert all("usable" in s for s in r["segments"])


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
