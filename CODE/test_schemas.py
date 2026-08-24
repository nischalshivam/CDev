#!/usr/bin/env python3
"""Tests for the plan/coverage schemas + format packs."""
import os
import tempfile
import pytest
import schemas as S
import format_packs as FP


def _shot(**kw):
    return S.ShotRequirement(**kw)


def test_shot_validation():
    _shot(role="literal", media="video").validate()          # ok
    with pytest.raises(S.ValidationError):
        _shot(role="nope").validate()
    with pytest.raises(S.ValidationError):
        _shot(media="hologram").validate()
    with pytest.raises(S.ValidationError):
        _shot(era=[2000, 1990]).validate()                   # from>to
    with pytest.raises(S.ValidationError):
        _shot(min_seconds=9, max_seconds=7).validate()


def test_beat_requires_shots_and_narration():
    with pytest.raises(S.ValidationError):
        S.Beat("B1", "text", shots=[]).validate()            # no shots
    with pytest.raises(S.ValidationError):
        S.Beat("B1", "   ", shots=[_shot()]).validate()      # empty narration
    S.Beat("B1", "The dealer blinked.", shots=[_shot()]).validate()


def test_plan_roundtrip_and_hash_lock():
    plan = S.VisualPlan(
        project_id="P1", narration_hash="abc123", format_pack="PRODUCT_LISTICLE",
        beats=[S.Beat("B1", "line one", 0, 5000,
                      shots=[_shot(role="literal", query_text="wildax campervan forecourt")])])
    plan.validate()
    p = os.path.join(tempfile.mkdtemp(), "plan.json")
    plan.save(p)
    back = S.VisualPlan.load(p)
    assert back.narration_hash == "abc123"
    assert back.beats[0].shots[0].query_text == "wildax campervan forecourt"
    assert isinstance(back.beats[0].shots[0], S.ShotRequirement)


def test_plan_needs_hash():
    with pytest.raises(S.ValidationError):
        S.VisualPlan(project_id="P1", narration_hash="",
                     beats=[S.Beat("B1", "x", shots=[_shot()])]).validate()


def test_plan_rejects_duplicate_beat_ids():
    with pytest.raises(S.ValidationError):
        S.VisualPlan(project_id="P1", narration_hash="h",
                     beats=[S.Beat("B1", "a", shots=[_shot()]),
                            S.Beat("B1", "b", shots=[_shot()])]).validate()


def test_demand_ticket_merge():
    t1 = S.DemandTicket("T1", "dealer forecourt", needed_variants=3, needed_seconds=15,
                        from_beats=["B1"])
    t2 = S.DemandTicket("T1", "dealer forecourt", needed_variants=5, needed_seconds=10,
                        from_beats=["B7"])
    t1.merge(t2)
    assert t1.needed_variants == 5 and t1.needed_seconds == 15
    assert t1.from_beats == ["B1", "B7"]


def test_manifest_roundtrip():
    m = S.ProjectManifest(project_id="uk-motorhomes/10-vans", niche="motorhomes",
                          format_pack="PRODUCT_LISTICLE", languages=["en", "es"])
    m.validate()
    p = os.path.join(tempfile.mkdtemp(), "project.json")
    m.save(p)
    assert S.ProjectManifest.load(p).languages == ["en", "es"]
    with pytest.raises(S.ValidationError):
        S.ProjectManifest(project_id="").validate()


def test_format_packs():
    assert set(["HISTORY_ARCHIVAL", "COMPARISON_EVIDENCE", "PROCUREMENT_TIMELINE",
                "PRODUCT_LISTICLE"]).issubset(set(FP.names()))
    assert FP.get("comparison_evidence")["display"] == "Comparison / evidence"
    assert FP.get("nonexistent")["display"]           # falls back to default, no crash


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
