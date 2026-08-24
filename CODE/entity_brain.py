#!/usr/bin/env python3
"""
entity_brain.py — Auto "Topic Pack" generator for ANY documentary video.

WHY THIS FILE EXISTS
--------------------
The hand-written niche packs (PACKS/niche/defence.yaml) only work when you already
know every entity in the niche. Documentaries are open-ended: "How Nike Went Bankrupt",
"Why a $1M Watch Makes No Sense", "The Truth About Superyachts". You cannot pre-write a
pack for every topic on earth.

The Entity Brain fixes that. Given only a VIDEO TITLE (and optionally the narration
script), it asks Claude to produce a `topic_pack.json` — a per-video, auto-generated
niche pack. That pack drives two things at once:
  1. SCRAPING  — concrete search queries per entity/era (source_hunter.py reads these)
  2. IDENTITY  — the entities + strictness the hard gates enforce (library search)

So the flow becomes:
    title (+ script)  ->  entity_brain  ->  topic_pack.json  ->  scraper + gates

This is the missing piece that makes CDev niche-agnostic.

USAGE
-----
    python CODE/entity_brain.py --title "How Nike Went Bankrupt"
    python CODE/entity_brain.py --title "The Rise of Rolex" --script scripts/rolex.txt \
                                --out PACKS/niche/rolex.json
    # then use it exactly like a normal niche pack:
    python CODE/demandscout.py --script scripts/rolex.txt --niche PACKS/niche/rolex.json

No API key / anthropic not installed? It falls back to a heuristic pack so the pipeline
never hard-crashes — but the LLM pack is far richer, use it in production.
"""
from __future__ import annotations
import os
import re
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
NICHE_DIR = BASE_DIR / "PACKS" / "niche"
NICHE_DIR.mkdir(parents=True, exist_ok=True)

# The model that builds the pack. Cheap + smart is the right trade here.
BRAIN_MODEL = os.getenv("ENTITY_BRAIN_MODEL", "claude-sonnet-5")


# ======================================================================
# THE PROMPT — this is the actual "brain". Edit here to tune quality.
# ======================================================================
BRAIN_PROMPT = """You are a documentary RESEARCH PRODUCER. Given a video title (and possibly
its narration script), you produce a machine-readable "Topic Pack" that a video-automation
engine uses to (a) scrape the RIGHT footage and images, and (b) reject wrong-subject footage
via hard identity gates.

Think like a researcher building a shot list for a 15-25 minute documentary. Cover the WHOLE
arc the title implies — origin, key people, key products/objects, rivals, turning points,
places, and eras — not just the literal words in the title.

RULES
- entities: the specific, nameable things the footage must actually show. Group them.
  Every entity needs a "strictness":
    exact    = a specific named variant/model/person/event that MUST match (e.g. "Air Jordan 1", "Phil Knight")
    specific = a category where the right class is enough (e.g. "Nike running shoe 1970s")
    general  = type-level, related is fine (e.g. "shoe factory")
    loose    = pure ambience (e.g. "1980s city street")
- eras: the time periods the video spans (years or decades). Footage look changes by era.
- search_queries: 15-30 CONCRETE queries a scraper can run on YouTube / archive.org / Wikimedia
  / Google Images. Each must name a real entity + a visual context. Good: "Phil Knight interview
  1980s". Bad: "Nike history" (too vague, returns recap channels).
- archive_terms: 4-8 terms specifically for archive.org (old ads, historical footage, public domain).
- wikimedia_articles: 5-12 exact Wikipedia article titles whose images are the right subject
  (people, HQs, products, places). These give clean, license-clear stills.
- avoid: things that pollute results for this topic (e.g. name collisions, unrelated brands,
  competitor recap channels). The gates and scraper use this as a blocklist.
- common_broll: 5-10 generic, reusable shots this video needs (money, stock ticker, factory line,
  city skyline). These go in the shared _common library, reused across videos.
- mood_arc: 3-6 words describing the emotional arc (e.g. "hopeful -> hubris -> collapse -> lesson").

Return ONLY valid JSON (no markdown fence), exactly this shape:
{
  "name": "<kebab-slug>",
  "display_name": "<Human Title Of Niche>",
  "title": "<the exact video title given>",
  "summary": "<one line: what this video is about>",
  "entities": {
    "people":   [{"name": "...", "strictness": "exact", "note": "who they are"}],
    "products": [{"name": "...", "strictness": "exact"}],
    "orgs":     [{"name": "...", "strictness": "exact"}],
    "places":   [{"name": "...", "strictness": "specific"}],
    "events":   [{"name": "...", "strictness": "exact", "year": "1985"}]
  },
  "eras": ["1964", "1970s", "1980s", "2000s"],
  "search_queries": ["...", "..."],
  "archive_terms": ["..."],
  "wikimedia_articles": ["..."],
  "common_broll": ["..."],
  "avoid": ["..."],
  "mood_arc": "hopeful -> collapse -> lesson"
}
"""


# ======================================================================
def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (fence-tolerant)."""
    text = text.strip()
    # strip ```json ... ``` fences if present
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    # else grab from first { to last }
    if not text.startswith("{"):
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1:
            text = text[s:e + 1]
    return json.loads(text)


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:40] or "topic"


def build_pack_llm(title: str, script_text: str = "") -> dict | None:
    """Ask Claude to build the topic pack. Returns None if the API path is unavailable."""
    try:
        import anthropic
    except ImportError:
        return None
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None

    user = f"VIDEO TITLE: {title}\n"
    if script_text.strip():
        # keep it bounded — first ~1200 words is plenty of signal
        words = script_text.split()
        user += "\nNARRATION SCRIPT (excerpt):\n" + " ".join(words[:1200])
    else:
        user += "\n(No script yet — infer the full arc from the title.)"

    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=BRAIN_MODEL,
            max_tokens=3000,
            temperature=0.4,
            messages=[{"role": "user", "content": f"{BRAIN_PROMPT}\n\n{user}"}],
        )
        pack = _extract_json(msg.content[0].text)
    except Exception as e:  # noqa: BLE001 — never crash the pipeline on a research call
        print(f"[entity_brain] LLM pack failed ({e}); falling back to heuristic")
        return None

    pack.setdefault("name", _slug(title))
    pack["title"] = title
    pack["generated_by"] = BRAIN_MODEL
    pack["generated_at"] = datetime.now().isoformat()
    return pack


def build_pack_heuristic(title: str, script_text: str = "") -> dict:
    """No-API fallback: crude but keeps the pipeline runnable offline.

    Pulls Proper-Noun phrases from the title/script as 'exact' entities and turns the
    title into a couple of generic search queries. Good enough to smoke-test wiring;
    NOT good enough for a real video — get the LLM path working for production.
    """
    text = f"{title}. {script_text}"
    caps = re.findall(r"\b[A-Z][a-zA-Z0-9'\-]+(?:\s+[A-Z][a-zA-Z0-9'\-]+)*\b", text)
    # de-dupe, drop 1-letter noise, keep order
    seen, ents = set(), []
    for c in caps:
        c = c.strip()
        if len(c) > 2 and c.lower() not in seen:
            seen.add(c.lower())
            ents.append(c)
    ents = ents[:15]
    years = sorted(set(re.findall(r"\b(?:19|20)\d{2}\b", text)))  # non-capturing: full year, not "19"/"20"
    return {
        "name": _slug(title),
        "display_name": title,
        "title": title,
        "summary": title,
        "entities": {
            "people": [], "products": [], "orgs": [],
            "places": [],
            "misc": [{"name": e, "strictness": "specific"} for e in ents],
        },
        "eras": sorted({y[:3] + "0s" for y in years}) or ["modern"],  # 1998 -> "1990s"
        "search_queries": [f"{e} documentary footage" for e in ents[:12]] or [title],
        "archive_terms": [f"{ents[0]}"] if ents else [],
        "wikimedia_articles": ents[:8],
        "common_broll": ["city skyline", "money counting", "stock market ticker",
                         "factory production line", "crowd walking"],
        "avoid": [],
        "mood_arc": "neutral",
        "generated_by": "heuristic",
        "generated_at": datetime.now().isoformat(),
    }


def build_pack(title: str, script_text: str = "") -> dict:
    """Main entry: LLM pack if possible, heuristic otherwise."""
    return build_pack_llm(title, script_text) or build_pack_heuristic(title, script_text)


def flatten_entities(pack: dict) -> list[str]:
    """All entity names as a flat list — handy for gate filters / library indexing."""
    out = []
    for group in (pack.get("entities") or {}).values():
        for e in group:
            if isinstance(e, dict) and e.get("name"):
                out.append(e["name"])
            elif isinstance(e, str):
                out.append(e)
    return out


def all_queries(pack: dict) -> list[str]:
    """Every scrape query the source hunter should try, de-duplicated, in priority order."""
    qs = list(pack.get("search_queries") or [])
    qs += [f"{t} archive" for t in (pack.get("archive_terms") or [])]
    qs += list(pack.get("common_broll") or [])
    seen, out = set(), []
    for q in qs:
        k = q.lower().strip()
        if k and k not in seen:
            seen.add(k)
            out.append(q)
    return out


# ======================================================================
def main():
    ap = argparse.ArgumentParser(description="Auto-generate a Topic Pack from a video title.")
    ap.add_argument("--title", required=True, help="The video title, e.g. 'How Nike Went Bankrupt'")
    ap.add_argument("--script", help="Optional narration script .txt for richer packs")
    ap.add_argument("--out", help="Output path (default PACKS/niche/<slug>.json)")
    a = ap.parse_args()

    script_text = ""
    if a.script and Path(a.script).exists():
        script_text = Path(a.script).read_text(encoding="utf-8", errors="ignore")

    pack = build_pack(a.title, script_text)
    out = Path(a.out) if a.out else NICHE_DIR / f"{pack['name']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")

    ents = flatten_entities(pack)
    qs = all_queries(pack)
    print(f"[entity_brain] pack: {out}")
    print(f"  via        : {pack.get('generated_by')}")
    print(f"  entities   : {len(ents)}  -> {', '.join(ents[:8])}{' ...' if len(ents) > 8 else ''}")
    print(f"  queries    : {len(qs)}")
    print(f"  eras       : {', '.join(pack.get('eras', []))}")
    print(f"  mood_arc   : {pack.get('mood_arc')}")


if __name__ == "__main__":
    main()
