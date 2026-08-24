#!/usr/bin/env python3
"""P0d: cataloger wiring, caching, <=7s cap, materialize+delogo — via FakeVision (no spend)."""
import os
import subprocess
import shutil
import tempfile
import pytest
import config
from vision import FakeVision
from cataloger import Cataloger

_HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
pytestmark = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not on PATH")


def fresh_catalog():
    root = tempfile.mkdtemp()
    os.environ["CDEV_LIBRARY_ROOT"] = root
    import importlib, config as cfg, catalog_db
    importlib.reload(cfg)
    importlib.reload(catalog_db)
    return catalog_db.Catalog(), root


def _make_video(root, name="src.mp4", dur=12):
    p = os.path.join(root, name)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"testsrc=size=640x360:rate=30:duration={dur}", "-t", str(dur),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", p], check=True)
    return p


class CountingVision(FakeVision):
    def __init__(self):
        self.calls = 0

    def analyze(self, video_path):
        self.calls += 1
        return super().analyze(video_path)


def test_catalog_source_adds_approved_segments():
    c, root = fresh_catalog()
    vid = _make_video(root, dur=12)          # FakeVision -> 2 segments
    r = Cataloger(c, FakeVision()).catalog_source(vid, "SRC1", "http://x")
    assert r["segments"] == 2 and len(r["added"]) == 2
    assert c.stats()["objects"] == 1 and c.stats()["assets"] == 2
    # segments were auto-approved and are retrievable
    got = c.search(query_text="synthetic scene", type="video")
    assert len(got) == 2


def test_cache_prevents_second_vision_call():
    c, root = fresh_catalog()
    vid = _make_video(root, dur=12)
    v = CountingVision()
    cat = Cataloger(c, v)
    cat.catalog_source(vid, "SRC1")
    assert v.calls == 1
    # second catalog of the SAME file -> cache hit, vision NOT called again
    r2 = cat.catalog_source(vid, "SRC1")
    assert v.calls == 1 and r2["cache_hit"] is True


def test_clip_capped_to_max_seconds():
    c, root = fresh_catalog()
    vid = _make_video(root, dur=12)
    Cataloger(c, FakeVision()).catalog_source(vid, "SRC1")
    # FakeVision makes 6s windows; cap is 7s so they stay <=7s; verify stored range
    rows = c.cx.execute("SELECT start_ms,end_ms FROM assets").fetchall()
    for r in rows:
        assert (r["end_ms"] - r["start_ms"]) <= config.MAX_CLIP_SECONDS * 1000 + 1


def test_materialize_cuts_and_delogos():
    c, root = fresh_catalog()
    vid = _make_video(root, dur=12)
    cat = Cataloger(c, FakeVision())
    r = cat.catalog_source(vid, "SRC1")
    first = r["added"][0]                      # segment 0 is 'fixable' with a logo_box
    out = os.path.join(tempfile.mkdtemp(), "clip.mp4")
    m = cat.materialize(first, out)
    assert os.path.exists(out) and m["delogo"] is True and m["seconds"] <= config.MAX_CLIP_SECONDS


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
