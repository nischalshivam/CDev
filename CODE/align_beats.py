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
    """Map each non-empty script line onto the word-timing stream, in order."""
    lines = [l.strip() for l in script_text.splitlines() if l.strip()]
    toks = [{"n": _norm(w["w"]), "s": w["s"], "e": w["e"]} for w in words if _norm(w["w"])]

    beats, wi = [], 0
    for line in lines:
        want = [_norm(x) for x in line.split() if _norm(x)]
        if not want:
            continue
        start = toks[wi]["s"] if wi < len(toks) else (beats[-1]["end"] if beats else 0.0)
        matched = 0
        j = wi
        # walk forward, tolerating small mismatches (numbers spoken differently, punctuation)
        for target in want:
            k, hop = j, 0
            while k < len(toks) and hop < 4:
                if toks[k]["n"] == target or toks[k]["n"].startswith(target[:4]) or \
                   target.startswith(toks[k]["n"][:4]):
                    j = k + 1
                    matched += 1
                    break
                k += 1; hop += 1
            else:
                j = min(j + 1, len(toks))
        end = toks[j - 1]["e"] if 0 < j <= len(toks) else start + 2.0
        if end <= start:
            end = start + 1.0
        beats.append({"text": line, "start": round(start, 2), "end": round(end, 2),
                      "matched": matched, "of": len(want)})
        wi = j

    # merge beats that are too short to hold a shot
    merged = []
    for b in beats:
        if merged and (b["end"] - b["start"]) < min_beat:
            merged[-1]["text"] += " " + b["text"]
            merged[-1]["end"] = b["end"]
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
