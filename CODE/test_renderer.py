#!/usr/bin/env python3
"""Renderer correctness via SYNTHETIC ffmpeg fixtures (no real footage needed)."""
import os
import shutil
import tempfile
import pytest
import renderer_core as R

pytestmark = pytest.mark.skipif(not R._have_ffmpeg(), reason="ffmpeg/ffprobe not on PATH")


def _fixtures():
    return R.make_fixtures(tempfile.mkdtemp())


def test_single_segment_renders():
    fx = _fixtures()
    out = os.path.join(tempfile.mkdtemp(), "one.mp4")
    r = R.render_timeline([{"file": fx["clips"][0], "kind": "video", "duration": 2.0}], out)
    assert r["ok"] and abs(r["duration"] - 2.0) < 0.4


def test_multi_segment_concat_and_xfade_duration():
    fx = _fixtures()
    segs = [{"file": fx["clips"][0], "kind": "video", "duration": 2.5, "transition": "slideleft"},
            {"file": fx["image"], "kind": "image", "duration": 2.0, "transition": "fade"},
            {"file": fx["clips"][1], "kind": "video", "duration": 2.5}]
    out = os.path.join(tempfile.mkdtemp(), "multi.mp4")
    r = R.render_timeline(segs, out)
    # xfade total = 2.5 + 2.0 + 2.5 - 2*0.5 = 6.0
    assert abs(r["expected"] - 6.0) < 0.01
    assert abs(r["duration"] - 6.0) < 0.5


def test_audio_is_mapped():
    fx = _fixtures()
    out = os.path.join(tempfile.mkdtemp(), "av.mp4")
    R.render_timeline([{"file": fx["clips"][0], "kind": "video", "duration": 2.0}],
                      out, audio_path=fx["audio"])
    import subprocess
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                              "-of", "csv=p=0", out], capture_output=True, text=True).stdout
    assert "video" in streams and "audio" in streams


def test_image_only_ken_burns():
    fx = _fixtures()
    out = os.path.join(tempfile.mkdtemp(), "img.mp4")
    r = R.render_timeline([{"file": fx["image"], "kind": "image", "duration": 3.0}], out)
    assert r["ok"] and abs(r["duration"] - 3.0) < 0.4


def test_empty_timeline_raises():
    with pytest.raises(ValueError):
        R.render_timeline([], os.path.join(tempfile.mkdtemp(), "x.mp4"))


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
