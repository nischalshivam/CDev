#!/usr/bin/env python3
"""
format_packs.py — the third dimension: niche = WHAT, format = HOW the story is told, style = LOOK.

The 5 sample videos proved distinct visual grammars. A format pack gives the clue-script stage
default shot cadence, preferred compositions and an opening treatment, so a bikes comparison video
doesn't get planned like a cars history video. These are GUIDANCE the planner reads, not hard rules.
"""

FORMAT_PACKS = {
    "HISTORY_ARCHIVAL": {
        "display": "History / archival",
        "example": "A Short History of the Longest American Cars",
        "avg_shot_seconds": 4.8,
        "hero_shot_seconds": 10.0,
        "compositions": ["single", "document", "map", "timeline"],
        "roles_emphasis": ["evidence", "literal", "atmospheric"],
        "opening": "archival hook + era establish",
        "notes": "real dated footage/photos, maps for places, people/events, cinematic B-roll",
    },
    "COMPARISON_EVIDENCE": {
        "display": "Comparison / evidence",
        "example": "American vs Chinese Carbon Bikes",
        "avg_shot_seconds": 4.6,
        "hero_shot_seconds": 8.0,
        "compositions": ["comparison", "split_screen", "price_card", "single"],
        "roles_emphasis": ["evidence", "literal"],
        "opening": "state the two things being compared",
        "notes": "two exact products side by side, price/stat cards, macro proof shots",
    },
    "PROCUREMENT_TIMELINE": {
        "display": "Procurement / timeline",
        "example": "Canadian Special Forces JLTV",
        "avg_shot_seconds": 5.5,
        "hero_shot_seconds": 12.0,
        "compositions": ["timeline", "document", "map", "single"],
        "roles_emphasis": ["evidence", "literal"],
        "opening": "name the program + the exact entity",
        "notes": "official footage, dated timeline beats, RFI/gov documents, exact vehicle identity",
    },
    "PRODUCT_LISTICLE": {
        "display": "Product listicle",
        "example": "10 Motorhomes... / 7 Amazon Fountain Pens...",
        "avg_shot_seconds": 4.5,
        "hero_shot_seconds": 9.0,
        "compositions": ["single", "price_card", "comparison"],
        "roles_emphasis": ["literal", "context", "evidence"],
        "opening": "numbered promise + market framing",
        "notes": "per-item walkthrough, numbered chapter cards, prices/discount typography",
    },
}

DEFAULT_FORMAT = "PRODUCT_LISTICLE"


def get(name: str) -> dict:
    return FORMAT_PACKS.get((name or "").upper(), FORMAT_PACKS[DEFAULT_FORMAT])


def names() -> list[str]:
    return list(FORMAT_PACKS)
