#!/usr/bin/env python3
"""Tests for Stage 0 script intake + narration lock."""
import os
import tempfile
import pytest
import intake


def test_strip_cues_and_arrows():
    raw = "The vans sat there [music] month after month >> and the dealer blinked."
    cleaned, log = intake.clean_script(raw)
    assert "[music]" not in cleaned and ">>" not in cleaned
    assert "month after month" in cleaned
    kinds = {c["kind"] for c in log}
    assert "strip_cue" in kinds and "strip_arrows" in kinds


def test_explicit_fixes_logged():
    raw = "A zero mile Millio is the raw bargain. Another Millio nearby."
    cleaned, log = intake.clean_script(raw, fixes={"Millio": "Mileo"})
    assert "Millio" not in cleaned and cleaned.count("Mileo") == 2
    fix = [c for c in log if c["kind"] == "fix"][0]
    assert fix["from"] == "Millio" and fix["to"] == "Mileo" and fix["count"] == 2


def test_hash_stable_to_whitespace_only():
    a = intake.narration_hash("hello   world\n\nfoo")
    b = intake.narration_hash("hello world foo")
    assert a == b                       # trivial whitespace must not break the lock


def test_hash_changes_on_content():
    assert intake.narration_hash("hello world") != intake.narration_hash("hello worlds")


def test_approve_and_load_roundtrip():
    d = tempfile.mkdtemp()
    r = intake.stage0(d, "en", "The dealer [music] blinked.")
    loaded = intake.load_approved(d, "en")
    assert loaded["hash"] == r["hash"]
    assert "blinked" in loaded["text"]


def test_load_detects_tampering():
    d = tempfile.mkdtemp()
    intake.stage0(d, "en", "Original approved text.")
    # someone edits the approved file after locking
    p = os.path.join(d, "scripts", "en", "approved.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("Sneakily changed text.")
    with pytest.raises(ValueError):
        intake.load_approved(d, "en")


def test_assert_narration_guard():
    txt = "the locked narration"
    h = intake.narration_hash(txt)
    intake.assert_narration(txt, h)                 # ok
    with pytest.raises(ValueError):
        intake.assert_narration("a different narration", h)


def test_per_language_isolation():
    d = tempfile.mkdtemp()
    en = intake.stage0(d, "en", "The dealer blinked.")
    es = intake.stage0(d, "es", "El concesionario parpadeó.")
    assert en["hash"] != es["hash"]
    assert intake.load_approved(d, "en")["text"] != intake.load_approved(d, "es")["text"]


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
