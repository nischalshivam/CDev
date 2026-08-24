#!/usr/bin/env python3
"""
Regression tests for the CDev catalog (foundation contracts).
Run:  cd CODE && python -m pytest test_catalog.py -q     (or: python test_catalog.py)

Each test locks one foundation rule that, if broken, silently poisons the library.
"""
import os
import tempfile
import pytest
from catalog_db import Catalog, ALLOWED_RIGHTS


def fresh() -> Catalog:
    p = os.path.join(tempfile.mkdtemp(), "t.sqlite")
    return Catalog(p)


def _approved(c, aid, **kw):
    """Helper: add an asset already approved + rights-clear so it CAN surface."""
    kw.setdefault("review_status", "approved")
    kw.setdefault("rights_status", "public_domain")
    kw.setdefault("quality", "high")
    c.add_asset(aid, kw.pop("type", "video"), **kw)


# 1. default-deny: unreviewed asset never surfaces
def test_needs_review_rejected():
    c = fresh()
    c.add_asset("A", "video", description="x", review_status="needs_review",
                rights_status="public_domain", quality="high")
    assert c.search(type="video") == []


# 2. default-deny: rights not allowed -> rejected (GPT finding #5)
def test_blocked_rights_rejected():
    c = fresh()
    c.add_asset("A", "video", review_status="approved", rights_status="blocked", quality="high")
    c.add_asset("B", "video", review_status="approved", rights_status=None, quality="high")
    assert c.search(type="video") == []


# 3. approved + allowed rights -> surfaces
def test_approved_allowed_surfaces():
    c = fresh()
    _approved(c, "A", description="nike shoe")
    assert [r["asset_id"] for r in c.search(type="video")] == ["A"]


# 4. video request must not return an image (GPT finding #6)
def test_media_type_honored():
    c = fresh()
    _approved(c, "VID", type="video")
    _approved(c, "IMG", type="image")
    assert [r["asset_id"] for r in c.search(type="video")] == ["VID"]
    assert [r["asset_id"] for r in c.search(type="image")] == ["IMG"]


# 5. required_all: EVERY entity must be present (GPT finding #7)
def test_required_all_enforced():
    c = fresh()
    c.upsert_entity("ORG_NIKE", "org", "Nike")
    c.upsert_entity("PERSON_PHIL", "person", "Phil Knight")
    _approved(c, "ONLY_NIKE", entities=["ORG_NIKE"])
    _approved(c, "BOTH", entities=["ORG_NIKE", "PERSON_PHIL"])
    got = [r["asset_id"] for r in c.search(type="video", required_all=["ORG_NIKE", "PERSON_PHIL"])]
    assert got == ["BOTH"]  # ONLY_NIKE must be excluded


# 6. required_any: at least one is enough
def test_required_any():
    c = fresh()
    c.upsert_entity("PERSON_PHIL", "person", "Phil Knight")
    c.upsert_entity("PERSON_MJ", "person", "Michael Jordan")
    _approved(c, "A", entities=["PERSON_PHIL"])
    got = [r["asset_id"] for r in c.search(type="video", required_any=["PERSON_PHIL", "PERSON_MJ"])]
    assert got == ["A"]


# 7. forbidden entity excludes the asset
def test_forbidden_entity():
    c = fresh()
    c.upsert_entity("ORG_NIKE", "org", "Nike")
    c.upsert_entity("ORG_ADIDAS", "org", "Adidas")
    _approved(c, "MIX", entities=["ORG_NIKE", "ORG_ADIDAS"])
    assert c.search(type="video", required_any=["ORG_NIKE"], forbidden=["ORG_ADIDAS"]) == []


# 8. alias resolves to canonical id (language bridge)
def test_alias_bridge():
    c = fresh()
    c.upsert_entity("ORG_NIKE", "org", "Nike", aliases=["Nike Inc", "耐克", "Nike, Inc."])
    assert c.resolve_alias("耐克") == "ORG_NIKE"
    assert c.resolve_alias("nike inc") == "ORG_NIKE"
    assert c.resolve_alias("Adidas") is None


# 9. duplicate segment (same source+timestamps) never inserted twice
def test_segment_dedup():
    c = fresh()
    c.add_source("SRC1", "u", "youtube", content_hash="h1")
    _approved(c, "S1", source_id="SRC1", start_ms=1000, end_ms=6000)
    _approved(c, "S2", source_id="SRC1", start_ms=1000, end_ms=6000)  # same window
    assert c.stats()["assets"] == 1


# 10. era mismatch rejected
def test_era_gate():
    c = fresh()
    _approved(c, "OLD", era_from=1980, era_to=1989)
    _approved(c, "NEW", era_from=2010, era_to=2019)
    got = [r["asset_id"] for r in c.search(type="video", era=(2005, 2025))]
    assert got == ["NEW"]


# 11. scope collection prevents cross-niche leakage
def test_scope_isolation():
    c = fresh()
    c.ensure_collection("COL_PROJECT_NIKE", "PROJECT")
    c.ensure_collection("COL_PROJECT_WATCH", "PROJECT")
    _approved(c, "NIKE", collections=["COL_PROJECT_NIKE"])
    _approved(c, "WATCH", collections=["COL_PROJECT_WATCH"])
    got = [r["asset_id"] for r in c.search(type="video", scope_collections=["COL_PROJECT_NIKE"])]
    assert got == ["NIKE"]


# 12. usage cooldown blocks an over-used clip
def test_cooldown_cap():
    c = fresh()
    _approved(c, "A")
    assert len(c.search(type="video", cooldown_channel="ch1", max_uses=2)) == 1
    c.mark_used("A", channel="ch1", video_id="v1")
    c.mark_used("A", channel="ch1", video_id="v2")
    assert c.search(type="video", cooldown_channel="ch1", max_uses=2) == []  # hit the cap


# 13. atomic/resume: reopening the same db keeps data (crash-safe persistence)
def test_persistence_reopen():
    p = os.path.join(tempfile.mkdtemp(), "t.sqlite")
    c = Catalog(p)
    _approved(c, "A")
    c.close()
    c2 = Catalog(p)
    assert c2.stats()["assets"] == 1


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
