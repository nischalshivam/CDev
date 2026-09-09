#!/usr/bin/env python3
"""entity_bind.py — bind people to clips, and narration lines to the face they need.

The defect this fixes is the one a viewer notices before any other: a name is spoken and a
different man is on screen. Three separate causes, all present at once:

  1. Only 59% of video assets carried any entity label. A clip whose own description read
     "Michael Spinks lies unconscious on the boxing canvas" had no ENT_SPINKS row against it, so
     asking retrieval for Spinks could not find it.
  2. A shared library holds several films. 48 Andrew Golota clips, plus Klitschko and Holyfield
     footage, sat unlabelled next to the Tyson material and won beats on text relevance alone.
  3. Only six of a hundred beats named an entity at all. The other ninety-four took whatever the
     words happened to match.

(1) and (2) are fixed by labelling every asset from its description and then declaring a ROSTER of
who may appear in this film — fail-closed, so an unlabelled stranger is excluded rather than
allowed. (3) is fixed by resolving every beat to a subject, pronouns included, once, up front.

Entity ids follow the convention already in the database: ENT_ plus the surname, upper-cased.
"""
from __future__ import annotations
import io
import json
import re
import unicodedata

# Everyone who may appear in a Tyson-Spinks film: the two men, Tyson's opponents from his rise, and
# the corner and officials who were actually there. Derived from what the in-era sources contain,
# not guessed.
SPINKS_ROSTER = ["ENT_TYSON", "ENT_SPINKS", "ENT_HOLMES", "ENT_BERBICK", "ENT_TILLMAN",
                 "ENT_RIBALTA", "ENT_KING", "ENT_BIGGS", "ENT_FRAZIER", "ENT_BRUNO",
                 "ENT_WILLIAMS", "ENT_RUDDOCK", "ENT_ROONEY", "ENT_JOHNSON", "ENT_LANE",
                 "ENT_GROSS", "ENT_RICHARDSON"]

# Deliberately NOT on the roster, and the reason each is excluded:
#   ENT_ALI        a different era entirely; two Ali clips were sitting in the Spinks source and
#                  one of them reached the last cut under narration about Tyson
#   ENT_GOLOTA     Tyson did fight Golota, but in October 2000
#   ENT_HOLYFIELD  1990s Tyson
# Era is enforced separately and at SOURCE level, via the PROJ_ collection: the stored per-asset
# era is too coarse to help (the 2000 Golota fight is recorded as era 1980-2009, a range wide
# enough to pass a 1988 gate), whereas a source's own title states its date.
SPINKS_SCOPE = ["PROJ_SPINKS_1988"]


def norm(s: str) -> str:
    """Alias normalisation: casefold and strip accents, so 'Andrzej Gołota' and 'golota' meet.

    This is the multi-language bridge the whole library depends on — one English label reachable
    from any spelling — so it must stay lossless in the ways that matter and lossy only in the ways
    that do not."""
    s = unicodedata.normalize("NFKD", (s or "").strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s'-]", " ", s)).strip()


def entity_id(name: str) -> str:
    parts = [p for p in norm(name).split() if p not in ("jr", "sr", "ii", "iii")]
    return "ENT_" + re.sub(r"[^A-Z]", "", (parts[-1] if parts else "unknown").upper())


def apply_labels(cat, assignments: list, min_conf: float = 0.0) -> dict:
    """Write the workflow's per-asset people onto the catalog. Returns a summary.

    asset_entities is REPLACED for every asset covered, not merged. The existing labels are the
    thing being corrected — merging would preserve exactly the errors this pass exists to remove.
    Assets no chunk covered are left untouched rather than silently cleared."""
    stats = {"assets": 0, "links": 0, "entities": 0, "foreign": 0, "cleared": 0}
    seen_ent = set()
    for a in assignments:
        aid = a.get("id")
        if not aid or (a.get("confidence") is not None and a["confidence"] < min_conf):
            continue
        if not cat.cx.execute("SELECT 1 FROM assets WHERE asset_id=?", (aid,)).fetchone():
            continue
        old = cat.cx.execute("SELECT COUNT(*) c FROM asset_entities WHERE asset_id=?",
                             (aid,)).fetchone()["c"]
        cat.cx.execute("DELETE FROM asset_entities WHERE asset_id=?", (aid,))
        stats["cleared"] += old
        for person in a.get("people") or []:
            eid = entity_id(person)
            if eid == "ENT_":
                continue
            cat.cx.execute(
                "INSERT INTO entities(entity_id, kind, display_name) VALUES(?,'person',?) "
                "ON CONFLICT(entity_id) DO UPDATE SET kind='person'", (eid, person.strip()))
            for al in {norm(person), norm(person.split()[-1])}:
                if al:
                    cat.cx.execute("INSERT OR IGNORE INTO entity_aliases(alias_norm, entity_id) "
                                   "VALUES(?,?)", (al, eid))
            cat.cx.execute("INSERT OR IGNORE INTO asset_entities(asset_id, entity_id, confidence) "
                           "VALUES(?,?,?)", (aid, eid, float(a.get("confidence") or 1.0)))
            seen_ent.add(eid)
            stats["links"] += 1
        if a.get("foreign"):
            stats["foreign"] += 1
        stats["assets"] += 1
    cat.cx.commit()
    stats["entities"] = len(seen_ent)
    return stats


def beat_entities(beats: list, roster: list) -> dict:
    """{beat_index: entity_id} for beats resolved to a person who is ON the roster.

    A beat resolved to someone off the roster is dropped rather than forced: the roster gate would
    reject every candidate and the beat would fall through to the fill pool, which is worse than
    simply not constraining it."""
    out = {}
    rs = set(roster)
    for b in beats:
        subj = (b.get("subject") or "").strip()
        if not subj:
            continue
        eid = entity_id(subj)
        if eid in rs:
            out[int(b["i"])] = eid
    return out


def save(path, obj):
    json.dump(obj, io.open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


def load(path):
    return json.load(io.open(path, encoding="utf-8"))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "CODE")
    import catalog_db
    data = load(sys.argv[1])
    cat = catalog_db.Catalog()
    print(apply_labels(cat, data.get("assets", [])))
    bm = beat_entities(data.get("beats", []), SPINKS_ROSTER)
    save(sys.argv[2] if len(sys.argv) > 2 else "beat_entities.json", bm)
    print(f"{len(bm)} beats bound to a roster entity")
