#!/usr/bin/env python3
"""
intake.py — Stage 0: raw -> cleaned -> approved narration, with a SHA-256 lock.

WHY (FOUNDATION.md): the sample motorhomes script was full of transcription artifacts
("[music]", ">>", "Millio" for "Mileo", "mahavishnu"...). If a raw file like that is locked
as truth, every downstream artifact (entities, TTS, beats, subtitles) inherits the garbage.

So Stage 0 makes the "one text" explicit and immutable:
    script.raw.txt      what came in (never used directly downstream)
    script.cleaned.txt  structural cleanup (markers/whitespace) + any explicit fixes applied
    script.approved.txt  the locked narration = single source of truth
    script.approved.<lang>.sha256   its hash

Every downstream file records this hash. `assert_narration()` fails the pipeline on a mismatch,
so a voiceover/beat set can never silently drift from the approved text.

Spelling/entity fixes that need judgement (Millio->Mileo) are passed in as an explicit `fixes`
dict — the tool does NOT guess them, it records exactly what was changed.
"""
from __future__ import annotations
import re
import json
import hashlib
from pathlib import Path

# bracketed stage cues and stray transcript tokens that are never spoken content
_CUE = re.compile(r"\[(music|applause|laughter|inaudible|crosstalk|noise)\]", re.I)
_ARROWS = re.compile(r">{2,}")
_MULTISPACE = re.compile(r"[ \t]{2,}")


def clean_script(raw: str, fixes: dict[str, str] | None = None) -> tuple[str, list[dict]]:
    """Structural cleanup + explicit fixes. Returns (cleaned_text, change_log).

    Structural (safe, automatic): remove [music]/[applause]/... cues, ">>" arrows, collapse
    whitespace, normalize quotes/dashes lightly. Judgement fixes come ONLY from `fixes`
    (e.g. {"Millio": "Mileo"}); each application is logged so nothing changes silently.
    """
    log: list[dict] = []
    text = raw

    n_cues = len(_CUE.findall(text))
    if n_cues:
        text = _CUE.sub(" ", text)
        log.append({"kind": "strip_cue", "count": n_cues})

    n_arrows = len(_ARROWS.findall(text))
    if n_arrows:
        text = _ARROWS.sub(" ", text)
        log.append({"kind": "strip_arrows", "count": n_arrows})

    for wrong, right in (fixes or {}).items():
        pat = re.compile(r"\b" + re.escape(wrong) + r"\b")
        n = len(pat.findall(text))
        if n:
            text = pat.sub(right, text)
            log.append({"kind": "fix", "from": wrong, "to": right, "count": n})

    text = _MULTISPACE.sub(" ", text)
    text = re.sub(r"\s+\n", "\n", text).strip()
    return text, log


def narration_hash(text: str) -> str:
    """Hash the EXACT bytes fed to TTS — after a single normalization so trivial whitespace
    differences don't break the lock, but real content changes do."""
    norm = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def approve(project_dir: str | Path, lang: str, cleaned_text: str) -> dict:
    """Lock `cleaned_text` as the approved narration for `lang`. Writes approved.<lang>.txt +
    its .sha256, returns {lang, hash, path}. Downstream artifacts must carry this hash."""
    d = Path(project_dir) / "scripts" / lang
    d.mkdir(parents=True, exist_ok=True)
    txt = d / "approved.txt"
    txt.write_text(cleaned_text, encoding="utf-8")
    h = narration_hash(cleaned_text)
    (d / "approved.sha256").write_text(h, encoding="utf-8")
    return {"lang": lang, "hash": h, "path": str(txt)}


def load_approved(project_dir: str | Path, lang: str) -> dict:
    """Load the approved narration and verify it still matches its recorded hash."""
    d = Path(project_dir) / "scripts" / lang
    text = (d / "approved.txt").read_text(encoding="utf-8")
    recorded = (d / "approved.sha256").read_text(encoding="utf-8").strip()
    actual = narration_hash(text)
    if actual != recorded:
        raise ValueError(f"approved narration for {lang} was edited after locking "
                         f"(hash {actual[:12]} != {recorded[:12]}). Re-approve it in Stage 0.")
    return {"lang": lang, "hash": recorded, "text": text}


def assert_narration(text: str, expected_hash: str):
    """Downstream guard: raise if `text` is not the approved narration."""
    if narration_hash(text) != expected_hash:
        raise ValueError("narration does not match the approved hash — the locked trio is broken "
                         "(clean narration = TTS text = beat narration must be ONE text).")


def stage0(project_dir: str | Path, lang: str, raw_text: str, fixes: dict = None) -> dict:
    """Full Stage 0 in one call: clean -> write raw+cleaned -> approve+lock. Returns the lock info
    plus the change log, so a human can see exactly what was altered before it became truth."""
    d = Path(project_dir) / "scripts" / lang
    d.mkdir(parents=True, exist_ok=True)
    (d / "raw.txt").write_text(raw_text, encoding="utf-8")
    cleaned, log = clean_script(raw_text, fixes)
    (d / "cleaned.txt").write_text(cleaned, encoding="utf-8")
    (d / "changes.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    lock = approve(project_dir, lang, cleaned)
    return {**lock, "changes": log}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Stage 0: clean + lock a narration script.")
    ap.add_argument("project_dir")
    ap.add_argument("raw_txt")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--fixes", help="JSON dict of explicit spelling fixes, e.g. '{\"Millio\":\"Mileo\"}'")
    a = ap.parse_args()
    fixes = json.loads(a.fixes) if a.fixes else None
    raw = Path(a.raw_txt).read_text(encoding="utf-8")
    r = stage0(a.project_dir, a.lang, raw, fixes)
    print(f"[intake] approved {a.lang}  hash={r['hash'][:16]}  changes={r['changes']}")
