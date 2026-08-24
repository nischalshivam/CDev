#!/usr/bin/env python3
"""Tests for the project workspace + orchestrator (Stage0 -> plan lock -> coverage)."""
import os
import tempfile
import pytest
import schemas as S
import project as P


def fresh_catalog():
    root = tempfile.mkdtemp()
    os.environ["CDEV_LIBRARY_ROOT"] = root
    import importlib, config, catalog_db
    importlib.reload(config)
    importlib.reload(catalog_db)
    return catalog_db.Catalog(), root


def _proj():
    base = tempfile.mkdtemp()
    m = S.ProjectManifest(project_id="10-vans", channel_id="uk-motorhomes",
                          niche="motorhomes", format_pack="PRODUCT_LISTICLE")
    return P.Project(base, m)


def test_stage0_then_plan_lock():
    proj = _proj()
    lock = proj.add_script("en", "The dealer [music] blinked.")
    plan = S.VisualPlan(project_id="10-vans", narration_hash=lock["hash"], language="en",
                        beats=[S.Beat("B1", "The dealer blinked.",
                                      shots=[S.ShotRequirement(media="image",
                                                               query_text="dealer forecourt")])])
    proj.save_plan(plan)                       # ok — hash matches
    assert proj.load_plan("en").beats[0].shots[0].query_text == "dealer forecourt"


def test_plan_rejected_on_hash_mismatch():
    proj = _proj()
    proj.add_script("en", "Approved text.")
    bad = S.VisualPlan(project_id="10-vans", narration_hash="deadbeef", language="en",
                       beats=[S.Beat("B1", "x", shots=[S.ShotRequirement()])])
    with pytest.raises(ValueError):
        proj.save_plan(bad)                    # plan written from a different text -> blocked


def test_coverage_writes_run_artifacts():
    c, root = fresh_catalog()
    proj = _proj()
    lock = proj.add_script("en", "Wildax forecourt stock.")
    plan = S.VisualPlan(project_id="10-vans", narration_hash=lock["hash"], language="en",
                        beats=[S.Beat("B1", "Wildax forecourt stock.",
                                      shots=[S.ShotRequirement(media="image",
                                                               query_text="wildax campervan forecourt")])])
    proj.save_plan(plan)
    cov = proj.coverage(c, "en", run_id="RUN1")
    assert cov["requirements"][0]["status"] == "ACQUIRE"
    assert (proj.dir / "runs" / "RUN1" / "coverage.json").exists()
    assert (proj.dir / "runs" / "RUN1" / "tickets.json").exists()


def test_scope_ids():
    m = S.ProjectManifest(project_id="10-vans", channel_id="uk", niche="motorhomes")
    ids = P.collection_ids_for(m)
    assert "COL_COMMON" in ids
    assert any("DOMAIN_MOTORHOMES" in x for x in ids)
    assert any("PROJECT_10-VANS" in x for x in ids)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
