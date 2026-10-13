"""sfx_cc0.py — the CC0 sound-effects kit (from the Barty-Bart `sound-effects` skill) + its measured mix check.

What we took from the skill and what we did not (tested 2026-10-13 on the map v2 scene):
  TAKEN  : the bundled CC0 library (hf_assets/sfx_cc0, 103 sounds, licence + source per file in manifest.json),
           cue type -> category map, "vary takes within a category", whooshes 2 frames early, risers END on
           the hit, measure the EXPORTED mp4 (integrated LUFS + true peak, stereo AND mono downmix).
  NOT    : beat-grid alignment (built for music-led promos; on a narrated doc with an orchestral bed librosa
           found no usable grid — reported a 58 s "cut-to-beat error"); Mixkit runtime sounds (no
           redistribution, so never in this repo); its -16 LUFS target (YouTube = -14, as fx_audio uses).
Use: events -> sfx_stem() -> mix it with voice/music in your own mix (fx_audio.mix takes an sfx stem) ->
     measure(final_mp4) -> assert ok.
"""
from __future__ import annotations
import json, random, re, subprocess
from pathlib import Path

KIT = Path(__file__).resolve().parent / "hf_assets" / "sfx_cc0"
SR = 48000
CUE_MAP = {"movement": "whoosh", "scene_cut": "whoosh", "appear": "pop", "click": "click", "build_up": "riser",
           "reveal": "impact", "success": "pop", "error_or_tech": "glitch", "hover_or_small_ui": "tick",
           "decode": "ui-blip", "bed": "ambience", "transition": "transition", "ding": "ding"}
GAIN = {"whoosh": -4, "pop": -6, "click": -6, "riser": -6, "impact": 0, "glitch": -8, "tick": -12,
        "ui-blip": -10, "ambience": -18, "transition": -5, "ding": -8}      # the skill's tested relative levels
EARLY = {"whoosh": 2 / 30, "transition": 2 / 30}                              # land the peak on the cut


def library():
    m = json.load(open(KIT / "manifest.json", encoding="utf-8"))
    lib = {}
    for e in m["bundled"]:
        lib.setdefault(e["category"], []).append({**e, "path": str(KIT / e["file"])})
    kit = {e["category"]: str(KIT / e["file"]) for e in m["default_kit"] if e.get("file")}
    for e in m["default_kit"]:                                   # the kit files are not in "bundled"
        if e.get("file"):
            lib.setdefault(e["category"], []).append({**e, "path": str(KIT / e["file"]),
                                                      "attribution": e.get("credit", "")})
    return lib, kit


def _dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
                       capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def plan(events, seed=7):
    """events: [{'t': s, 'type': cue type, 'gain': dB?}] -> [{'at', 'file', 'gain', 'cat', 'credit'}].
    Default-kit sound first; repeats of a category rotate through its alternatives (no robotic repeats)."""
    lib, kit = library()
    rnd, used, out = random.Random(seed), {}, []
    for e in events:
        cat = CUE_MAP.get(e["type"], e["type"])
        pool = lib.get(cat, [])
        if not pool:
            continue
        n = used.get(cat, 0); used[cat] = n + 1
        f = kit.get(cat) if n == 0 and cat in kit else rnd.choice(pool)["path"]
        at = e["t"] - EARLY.get(cat, 0.0)
        if cat == "riser":                                   # a riser ENDS on the hit it builds to
            at = e.get("hit", e["t"]) - _dur(f)
        out.append({"at": max(0.0, at), "file": f, "gain": e.get("gain", GAIN.get(cat, -8)), "cat": cat})
    return out


def sfx_stem(events, duration, out, seed=7):
    """Render one stereo WAV stem with every placed sound (adelay per use)."""
    pl = plan(events, seed)
    if not pl:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", f"{duration:.3f}", "-i",
                        f"anullsrc=r={SR}:cl=stereo", str(out)], check=True)
        return str(out), pl
    inputs, parts = [], []
    for k, p in enumerate(pl):
        inputs += ["-i", p["file"]]
        ms = int(p["at"] * 1000)
        parts.append(f"[{k}:a]aformat=sample_rates={SR}:channel_layouts=stereo,volume={p['gain']}dB,"
                     f"adelay={ms}|{ms}[e{k}]")
    g = ";".join(parts) + ";" + "".join(f"[e{k}]" for k in range(len(pl))) + \
        f"amix=inputs={len(pl)}:normalize=0:dropout_transition=0,apad[o]"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", g, "-map", "[o]",
                    "-t", f"{duration:.3f}", "-ar", str(SR), "-c:a", "pcm_s16le", str(out)], check=True)
    return str(out), pl


def measure(media, target_lufs=-14.0, tol=1.0, max_tp=-1.0):
    """Measure the EXPORTED file (stereo + mono downmix). Returns dict with ok flag."""
    res = {}
    for name, extra in (("stereo", []), ("mono", ["-ac", "1"])):
        r = subprocess.run(["ffmpeg", "-nostats", "-i", str(media), *extra, "-af", "ebur128=peak=true", "-f", "null", "-"],
                           capture_output=True, text=True)
        s = r.stderr[r.stderr.rfind("Summary"):]
        i = re.search(r"I:\s+(-?[\d.]+) LUFS", s); tp = re.search(r"Peak:\s+(-?[\d.]+) dBFS", s)
        res[name] = (float(i.group(1)) if i else None, float(tp.group(1)) if tp else None)
    lufs, tp = res["stereo"]
    res["ok"] = lufs is not None and abs(lufs - target_lufs) <= tol and tp is not None and tp <= max_tp
    return res


def credits(pl):
    """Paste-ready credit lines for the sounds actually used (CC0 needs none; this is proof of source)."""
    lib, _ = library()
    by = {e["path"]: e for es in lib.values() for e in es}
    seen, lines = set(), []
    for p in pl:
        e = by.get(p["file"])
        if e and e["path"] not in seen:
            seen.add(e["path"]); lines.append(f'{e.get("attribution", "")} - {e.get("source_url", "")}')
    return "\n".join(lines)
