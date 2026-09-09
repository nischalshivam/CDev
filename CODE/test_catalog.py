#!/usr/bin/env python3
"""
Regression tests for the hardened CDev catalog (foundation contracts).
Run:  cd CODE && python -m pytest test_catalog.py -q     (or: python test_catalog.py)

Each test locks one foundation rule that, if broken, silently poisons the library.
"""
import os
import tempfile
import sqlite3
import pytest


def fresh():
    """A Catalog whose library_root is a fresh temp dir (objects land there)."""
    root = tempfile.mkdtemp()
    os.environ["CDEV_LIBRARY_ROOT"] = root
    import importlib, config, catalog_db
    importlib.reload(config)
    importlib.reload(catalog_db)
    return catalog_db.Catalog(), root


def _file(root, name, data=b"hello-media-bytes"):
    p = os.path.join(root, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


def _img(c, root, aid, data=None, **kw):
    """Ingest a real object file and add an APPROVED image asset referencing it."""
    src = _file(root, f"{aid}.jpg", data or aid.encode() + b"-bytes")
    obj = c.ingest_file(src)
    kw.setdefault("review_status", "approved")
    kw.setdefault("quality", "high")
    kw.setdefault("match_conf", 0.9)
    c.add_asset(aid, "image", object_sha=obj["sha256"], **kw)
    return obj


# 1. content-hash dedup: same bytes -> ONE object, second ingest is 'existing'
def test_object_dedup():
    c, root = fresh()
    a = c.ingest_file(_file(root, "a.mp4", b"same"))
    b = c.ingest_file(_file(root, "b.mp4", b"same"))     # different name, same bytes
    assert a["sha256"] == b["sha256"]
    assert b["existing"] is True
    assert c.stats()["objects"] == 1


# 2. relative paths only (drive-letter safe): no absolute path / drive letter in the DB
def test_relative_paths():
    c, root = fresh()
    o = c.ingest_file(_file(root, "a.mp4"))
    assert o["rel_path"].startswith("objects/")
    assert ":" not in o["rel_path"] and not o["rel_path"].startswith("/")


# 3. fail-closed: unreviewed asset never surfaces
def test_needs_review_rejected():
    c, root = fresh()
    _img(c, root, "A", review_status="needs_review")
    assert c.search(type="image") == []


# 4. fail-closed: missing object file -> not retrievable (even if approved)
def test_missing_file_rejected():
    c, root = fresh()
    o = _img(c, root, "A")
    os.remove(os.path.join(root, o["rel_path"]))          # object gone from disk
    assert c.search(type="image") == []


# 5. fail-closed: 'unusable' clip (caption over subject) never surfaces; 'fixable' does
def test_clean_status_gate():
    c, root = fresh()
    _img(c, root, "BAD", clean_status="unusable")
    _img(c, root, "FIX", clean_status="fixable")
    assert [r["asset_id"] for r in c.search(type="image")] == ["FIX"]


# 6. approved + file present -> surfaces
def test_approved_surfaces():
    c, root = fresh()
    _img(c, root, "A", description="nike shoe factory")
    assert [r["asset_id"] for r in c.search(type="image")] == ["A"]


# 7. media type honored (video request must not return an image)
def test_media_type_honored():
    c, root = fresh()
    _img(c, root, "IMG")
    assert c.search(type="video") == []
    assert [r["asset_id"] for r in c.search(type="image")] == ["IMG"]


# 8. required_all: EVERY entity must be present
def test_required_all():
    c, root = fresh()
    c.upsert_entity("ORG_NIKE", "org", "Nike")
    c.upsert_entity("PERSON_PHIL", "person", "Phil Knight")
    _img(c, root, "ONE", entities=["ORG_NIKE"])
    _img(c, root, "BOTH", entities=["ORG_NIKE", "PERSON_PHIL"])
    got = [r["asset_id"] for r in c.search(type="image", required_all=["ORG_NIKE", "PERSON_PHIL"])]
    assert got == ["BOTH"]


# 9. forbidden entity excludes the asset
def test_forbidden():
    c, root = fresh()
    c.upsert_entity("ORG_NIKE", "org", "Nike")
    c.upsert_entity("ORG_ADIDAS", "org", "Adidas")
    _img(c, root, "MIX", entities=["ORG_NIKE", "ORG_ADIDAS"])
    assert c.search(type="image", required_any=["ORG_NIKE"], forbidden=["ORG_ADIDAS"]) == []


# 10. alias: unique resolves; AMBIGUOUS returns None + >1 candidates (never an arbitrary pick)
def test_alias_ambiguity():
    c, _ = fresh()
    c.upsert_entity("ORG_NIKE", "org", "Nike", aliases=["耐克"])
    c.upsert_entity("PERSON_NIKE_GREEK", "person", "Nike (goddess)", aliases=["victory"])
    assert c.resolve_alias("耐克") == "ORG_NIKE"
    # give both entities the SAME alias -> must be ambiguous
    c.upsert_entity("ORG_NIKE", "org", "Nike", aliases=["nike"])
    c.upsert_entity("PERSON_NIKE_GREEK", "person", "Nike (goddess)", aliases=["nike"])
    assert c.resolve_alias("Nike") is None
    assert len(c.resolve_alias_candidates("nike")) == 2


# 11. segment dedup: same (source, start_ms, end_ms) inserted once
def test_segment_dedup():
    c, root = fresh()
    o = c.ingest_file(_file(root, "src.mp4"))
    c.add_source("SRC1", "u", "youtube", content_hash=o["sha256"])
    c.add_asset("S1", "video", source_id="SRC1", start_ms=1000, end_ms=6000, review_status="approved")
    c.add_asset("S2", "video", source_id="SRC1", start_ms=1000, end_ms=6000, review_status="approved")
    assert c.stats()["assets"] == 1


# 12. era gate: unknown era rejected when the beat forbids it; known era must overlap
def test_era_gate():
    c, root = fresh()
    _img(c, root, "OLD", era_from=1980, era_to=1989)
    _img(c, root, "NEW", era_from=2010, era_to=2019)
    _img(c, root, "UNK")                                  # no era
    assert [r["asset_id"] for r in c.search(type="image", era=(2005, 2025))] == ["NEW"]
    got = {r["asset_id"] for r in c.search(type="image", era=(2005, 2025), allow_unknown_era=True)}
    assert got == {"NEW", "UNK"}                          # unknown allowed only when asked


# 13. scope collection prevents cross-niche leakage
def test_scope_isolation():
    c, root = fresh()
    c.ensure_collection("COL_PROJECT_NIKE", "PROJECT")
    c.ensure_collection("COL_PROJECT_WATCH", "PROJECT")
    _img(c, root, "NIKE", collections=["COL_PROJECT_NIKE"])
    _img(c, root, "WATCH", collections=["COL_PROJECT_WATCH"])
    got = [r["asset_id"] for r in c.search(type="image", scope_collections=["COL_PROJECT_NIKE"])]
    assert got == ["NIKE"]


# 14. cooldown: over-used clip excluded; last-N exclusion works
def test_cooldown():
    c, root = fresh()
    _img(c, root, "A")
    assert len(c.search(type="image", cooldown_channel="ch", max_channel_uses=2)) == 1
    c.mark_used("A", channel="ch"); c.mark_used("A", channel="ch")
    assert c.search(type="image", cooldown_channel="ch", max_channel_uses=2) == []


# 15. FTS relevance: query_text returns only matching assets, ranked
def test_fts_relevance():
    c, root = fresh()
    _img(c, root, "PEN", description="fountain pen nib writing macro close-up")
    _img(c, root, "CAR", description="classic american car driving on a highway")
    got = [r["asset_id"] for r in c.search(query_text="fountain pen nib", type="image")]
    assert got == ["PEN"]
    assert c.search(query_text="submarine periscope", type="image") == []


# 16. auto-approve guard: high-conf clean + file -> approved; low-conf -> quarantined
def test_auto_approve():
    c, root = fresh()
    src = _file(root, "x.jpg"); o = c.ingest_file(src)
    c.add_asset("HI", "image", object_sha=o["sha256"], clean_status="clean", match_conf=0.9)
    c.add_asset("LO", "image", object_sha=o["sha256"], clean_status="clean", match_conf=0.2)
    assert c.auto_approve("HI") == "approved"
    assert c.auto_approve("LO") == "quarantined"


# 17. transaction rollback: a CHECK violation leaves NO partial rows (asset or FTS)
def test_transaction_rollback():
    c, root = fresh()
    o = c.ingest_file(_file(root, "src.mp4"))
    c.add_source("SRC1", "u", "youtube", content_hash=o["sha256"])
    with pytest.raises(sqlite3.IntegrityError):
        c.add_asset("BAD", "video", source_id="SRC1", start_ms=6000, end_ms=1000)  # start>end
    assert c.stats()["assets"] == 0
    fts = c.cx.execute("SELECT COUNT(*) FROM assets_fts WHERE asset_id='BAD'").fetchone()[0]
    assert fts == 0


# 18. consistent backup snapshot is usable
def test_backup():
    c, root = fresh()
    _img(c, root, "A")
    dest = os.path.join(root, "backup.sqlite")
    c.backup(dest)
    b = sqlite3.connect(dest)
    assert b.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
    b.close()


# 19. persistence: reopening the same db keeps data
def test_persistence():
    c, root = fresh()
    _img(c, root, "A")
    c.close()
    import catalog_db
    c2 = catalog_db.Catalog(os.path.join(root, "catalog.sqlite"))
    assert c2.stats()["assets"] == 1


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))


# 60. roster: a project declares who may appear; anyone else excludes the asset (fail-closed)
def test_roster_excludes_off_roster_person():
    c, root = fresh()
    c.upsert_entity("ENT_TYSON", "person", "Mike Tyson")
    c.upsert_entity("ENT_GOLOTA", "person", "Andrew Golota")
    _img(c, root, "TYSON_ONLY", entities=["ENT_TYSON"])
    _img(c, root, "GOLOTA", entities=["ENT_GOLOTA"])
    _img(c, root, "CROWD")                                  # no person at all
    got = sorted(r["asset_id"] for r in c.search(type="image", roster=["ENT_TYSON"]))
    # the stranger is gone; the crowd shot survives because a roster judges PEOPLE, not everything
    assert got == ["CROWD", "TYSON_ONLY"]


# 61. roster judges people only — a place label must not disqualify an asset
def test_roster_ignores_non_person_entities():
    c, root = fresh()
    c.upsert_entity("ENT_TYSON", "person", "Mike Tyson")
    c.upsert_entity("PLACE_AC", "place", "Atlantic City")
    _img(c, root, "TYSON_IN_AC", entities=["ENT_TYSON", "PLACE_AC"])
    assert [r["asset_id"] for r in c.search(type="image", roster=["ENT_TYSON"])] == ["TYSON_IN_AC"]


# 62. an UNLABELLED stranger is the case a blacklist cannot catch — roster must still allow it only
#     when it carries no person label at all, and reject the moment one is added
def test_roster_is_failclosed_for_new_entities():
    c, root = fresh()
    c.upsert_entity("ENT_TYSON", "person", "Mike Tyson")
    c.upsert_entity("ENT_NEWCOMER", "person", "Someone Added Later")
    _img(c, root, "NEW", entities=["ENT_NEWCOMER"])
    assert c.search(type="image", roster=["ENT_TYSON"]) == []
    assert [r["asset_id"] for r in c.search(type="image")] == ["NEW"]   # unrestricted still finds it


# 63. a card must fit the frame it is composited into, at ANY build resolution
def test_cards_fit_target_resolution():
    """The build moved to 1280x720 while typography still drew 1920x1080 and the overlay was
    applied at 0:0 with no scale, so only the top-left of each card survived: centred text landed
    in the bottom-right and ran off the edge ("Quadrastee", "37 ft" half gone). This pins the
    contract — a card is the size it is asked for, and its ink stays inside the frame."""
    import numpy as np
    from PIL import Image
    import typography as T
    for w, h in ((1280, 720), (1920, 1080)):
        p = os.path.join(tempfile.mkdtemp(), "c.png")
        T.stat_card("37 ft", "turning circle", p, style="clean", size_px=(w, h))
        im = Image.open(p)
        assert im.size == (w, h), f"card is {im.size}, asked for {(w, h)}"
        a = np.asarray(im.convert("RGBA"))[:, :, 3]          # alpha = where ink is
        ys, xs = np.nonzero(a > 8)
        assert xs.size, "card rendered nothing"
        m = 4
        assert xs.min() >= m and xs.max() <= w - m, "ink runs off the horizontal edge"
        assert ys.min() >= m and ys.max() <= h - m, "ink runs off the vertical edge"


# 64. no ACTIVE render path may use zoompan — it shakes, measured
def test_no_zoompan_in_active_render_paths():
    """zoompan truncates its crop origin to whole pixels (and in a zoom, the crop height too), so a
    smooth Ken Burns arrives as uneven steps. Measured on our own stills:

        zoompan       dx sd 0.352 px    <- visible shake
        perspective   dx sd 0.001 px

    The fix landed in three niche builds and was then found still present in a fourth build and in
    three unused modules — the same "fixed here, not there" pattern that let a rival channel's
    watermark ship. A comment cannot stop that from coming back; this test can."""
    import re, pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    active = [root / "CODE" / "build_core.py",
              root / "_quadrasteer" / "build.py",
              root / "_ajax" / "build.py",
              root / "_alzado" / "build.py",
              root / "_spinks" / "sample_audio.py",
              root / "_spinks" / "build.py"]
    offenders = []
    for f in active:
        if not f.exists():
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"zoompan\s*=", code):
                offenders.append(f"{f.name}:{i}")
    assert not offenders, f"zoompan in an active render path: {offenders}"
