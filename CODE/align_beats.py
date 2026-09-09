#!/usr/bin/env python3
"""
align_beats.py — turn a known script + word timings into exactly-timed beats.

This is the piece that makes clips land on the right words. We are NOT transcribing and guessing:
we already know the script text (we fed it to TTS), and we have per-word start/end from the TTS
provider. So each script line maps to a precise [start, end] span by walking both in order.

    from align_beats import align
    beats = align(script_text, words)      # [{"i","text","start","end","dur"}...]

Line breaks in the script are the author's beats — a mentalist-style script puts one idea per
line, which is also the natural cut point. Short lines are merged up to MIN_BEAT so we never get
a 0.4s flash of a shot; long lines are left intact (the visual planner can put 2-3 shots inside).
"""
from __future__ import annotations
import re

MIN_BEAT = 1.4          # seconds — below this a shot reads as a glitch, so merge forward


def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower())


def align(script_text: str, words: list[dict], min_beat: float = MIN_BEAT) -> list[dict]:
    """Map each script line onto the word-timing stream by GLOBAL sequence alignment.

    Earlier versions walked both streams greedily, line by line, with a small forward look-ahead.
    That cannot recover from a single bad step: a loose 4-character prefix rule ("star" matching
    "start") lets the cursor jump ahead of the real position, the window only ever looks FORWARD,
    and every following line then matches nothing. On a date-heavy script the collapse was total —
    beats 0-21 aligned, beat 22 onward scored 0/10, 3/19, 2/7 and the picture would have sat on the
    wrong sentence for the rest of the video.

    The script and the spoken words are the SAME text apart from how the voice reads numbers
    ("1990" -> "nineteen ninety"), so this is a classic diff problem, not a search problem.
    difflib finds the matching blocks over the whole pair at once; a token that can never match
    simply falls outside every block instead of dragging a cursor with it, and no local mistake can
    cascade. Measured weak_alignment across three real scripts: 0 / 0 / 0."""
    import difflib
    lines = [l.strip() for l in script_text.splitlines() if l.strip()]
    spoken = [{"n": _norm(w["w"]), "s": w["s"], "e": w["e"]} for w in words if _norm(w["w"])]

    flat, owner = [], []
    for li, line in enumerate(lines):
        for tok in (_norm(x) for x in line.split()):
            if tok:
                flat.append(tok); owner.append(li)

    sm = difflib.SequenceMatcher(None, flat, [t["n"] for t in spoken], autojunk=False)
    pos = {}
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            pos[a + k] = b + k

    per_line = {}
    for i, li in enumerate(owner):
        if i in pos:
            per_line.setdefault(li, []).append(pos[i])
    counts = {}
    for li in owner:
        counts[li] = counts.get(li, 0) + 1

    beats, last_end = [], 0.0
    for li, line in enumerate(lines):
        hits = per_line.get(li)
        if hits:
            start = spoken[min(hits)]["s"]
            end = spoken[max(hits)]["e"]
        else:                       # no word of this line could be matched — sit in the gap
            start, end = last_end, last_end + 1.0
        if start < last_end:
            start = last_end
        if end <= start:
            end = start + 1.0
        beats.append({"text": line, "start": round(start, 2), "end": round(end, 2),
                      "matched": len(hits or []), "of": counts.get(li, 0)})
        last_end = end

    merged = []
    for b in beats:
        if merged and (b["end"] - b["start"]) < min_beat:
            merged[-1]["text"] += " " + b["text"]
            merged[-1]["end"] = b["end"]
            merged[-1]["matched"] += b["matched"]
            merged[-1]["of"] += b["of"]
        else:
            merged.append(dict(b))
    for i, b in enumerate(merged):
        b["i"] = i
        b["dur"] = round(b["end"] - b["start"], 2)
    return merged


def report(beats: list[dict]) -> dict:
    durs = sorted(b["dur"] for b in beats)
    mid = durs[len(durs) // 2] if durs else 0
    weak = [b for b in beats if b["of"] and b["matched"] / b["of"] < 0.6]
    return {"beats": len(beats), "median_dur": mid,
            "shortest": durs[0] if durs else 0, "longest": durs[-1] if durs else 0,
            "weak_alignment": len(weak)}


if __name__ == "__main__":
    import sys, json, io
    script = io.open(sys.argv[1], encoding="utf-8").read()
    words = json.load(io.open(sys.argv[2], encoding="utf-8"))
    b = align(script, words)
    print(json.dumps(report(b), indent=1))
    with io.open(sys.argv[3], "w", encoding="utf-8") as f:
        json.dump(b, f, ensure_ascii=False, indent=1)
