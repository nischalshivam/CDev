#!/usr/bin/env python3
"""Tests for the coverage planner + demand tickets (against a real in-memory Catalog)."""
import os
import tempfile
import pytest
import schemas as S
import coverage as CV


def fresh_catalog():
    root = tempfile.mkdtemp()
    os.environ["CDEV_LIBRARY_ROOT"] = root
    import importlib, config, catalog_db
    importlib.reload(config)
    importlib.reload(catalog_db)
    return catalog_db.Catalog(), root


def _approved_img(c, root, aid, desc, entities=None):
    p = os.path.join(root, f"{aid}.jpg")
    open(p, "wb").write(aid.encode() + b"-bytes")
    o = c.ingest_file(p)
    c.add_asset(aid, "image", object_sha=o["sha256"], description=desc, quality="high",
                match_conf=0.9, review_status="approved", entities=entities or [])


def _shot(**kw):
    return S.ShotRequirement(**kw)


def _plan(pid, beats):
    return S.VisualPlan(project_id=pid, narration_hash="h", beats=beats)


def test_generate_needs_no_acquisition():
    c, root = fresh_catalog()
    plan = _plan("P1", [S.Beat("B1", "$5,700 vs $1,900",
                               shots=[_shot(media="graphic", composition="price_card")])])
    cov = CV.plan_coverage(c, plan)
    assert cov["requirements"][0]["status"] == "GENERATE"
    assert len(cov["tickets"]) == 0


def test_acquire_when_empty():
    c, root = fresh_catalog()
    plan = _plan("P1", [S.Beat("B1", "wildax forecourt",
                               shots=[_shot(media="image", query_text="wildax campervan forecourt")])])
    cov = CV.plan_coverage(c, plan)
    assert cov["requirements"][0]["status"] == "ACQUIRE"
    assert len(cov["tickets"]) == 1


def test_exact_reuse_when_covered():
    c, root = fresh_catalog()
    _approved_img(c, root, "A", "wildax campervan forecourt rows")
    plan = _plan("P1", [S.Beat("B1", "wildax forecourt",
                               shots=[_shot(media="image", query_text="wildax campervan forecourt")])])
    cov = CV.plan_coverage(c, plan)
    assert cov["requirements"][0]["status"] in ("EXACT_REUSE", "ACCEPTABLE_REUSE")
    assert len(cov["tickets"]) == 0


def test_partial_when_short_on_variants():
    c, root = fresh_catalog()
    _approved_img(c, root, "A", "dealer forecourt rows of motorhomes")
    # three beats want the same forecourt shot, but only one clip exists -> repetition risk
    beats = [S.Beat(f"B{i}", "forecourt line",
                    shots=[_shot(media="image", query_text="dealer forecourt motorhomes")])
             for i in range(3)]
    cov = CV.plan_coverage(c, _plan("P1", beats))
    statuses = {r["status"] for r in cov["requirements"]}
    assert "PARTIAL" in statuses
    t = list(cov["tickets"].values())[0]
    assert t.needed_variants >= 2          # short by ~2 distinct clips
    assert set(t.from_beats) == {"B0", "B1", "B2"}


def test_batch_merges_duplicate_tickets():
    c, root = fresh_catalog()
    q = "dealer forecourt motorhomes"
    p1 = _plan("P1", [S.Beat("B1", "x", shots=[_shot(media="image", query_text=q)])])
    p2 = _plan("P2", [S.Beat("B1", "y", shots=[_shot(media="image", query_text=q)])])
    out = CV.plan_coverage_batch(c, [p1, p2])
    assert len(out["tickets"]) == 1                         # merged, not two
    assert set(out["tickets"][0].from_beats) == {"B1"}      # same beat id across projects


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
