#!/usr/bin/env python3
"""
catalog_db.py — CDev's operational catalog (SQLite, day-one).

WHY SQLITE (see FOUNDATION.md §5)
  A single big JSON file corrupts under concurrent writes (queue + many niches), has no
  transactions/indexes, and a crash mid-write can lose the whole library. SQLite is a
  server-less, built-in, single-file database with WAL concurrency, atomic transactions,
  foreign keys and fast indexed search. One `.sqlite` file = easy backup + reusable years later.

CORE DESIGN
  * One media object stored ONCE, keyed by content hash. No duplicate copies across layers.
  * Conceptual layers (COMMON / DOMAIN / ENTITY / PROJECT / GENERATED) are COLLECTIONS (tags),
    many-to-many — an asset can belong to several at once without being copied.
  * Entities are CANONICAL IDs (ORG_NIKE, MFR_SWIFT__RANGE_CARRERA, PERSON_PHIL_KNIGHT) with
    aliases. This is also the LANGUAGE BRIDGE: a Spanish/French beat resolves to the same
    canonical ID, so ONE English library serves every language.
  * Retrieval is DEFAULT-DENY: an asset surfaces only if review_status == 'approved' AND
    rights_status is in an allowed set. Missing/unknown status = rejected (fail-closed).
  * Entity gates support required_all / required_any / forbidden — not "first match wins".
  * Media type is honored; fallbacks must be requested explicitly by the caller.

This module is storage + retrieval only. Scraping, cataloging and rendering live elsewhere and
write THROUGH this API. JSON/JSONL stay as import/export + Gemini interface, never the DB.
"""
from __future__ import annotations
import os
import json
import time
import sqlite3
from pathlib import Path
from typing import Optional, Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
LIBRARY_DIR = BASE_DIR / "library"
OBJECTS_DIR = LIBRARY_DIR / "objects"
DB_PATH = LIBRARY_DIR / "catalog.sqlite"

SCHEMA_VERSION = 1

# Rights a renderable asset may have. Default-deny: anything else (incl. NULL) is rejected.
ALLOWED_RIGHTS = {"owned", "licensed", "public_domain", "approved_fair_use"}
VALID_LAYERS = {"COMMON", "DOMAIN", "ENTITY", "PROJECT", "GENERATED"}


# ======================================================================
# SCHEMA
# ======================================================================
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

-- a downloaded source file (dedup + provenance). NEVER retrieved directly.
CREATE TABLE IF NOT EXISTS sources (
  source_id     TEXT PRIMARY KEY,
  url           TEXT,
  kind          TEXT,                 -- youtube | archive | wikimedia | stock | upload
  channel       TEXT,
  channel_trust TEXT,                 -- official | news | unknown
  content_hash  TEXT UNIQUE,          -- sha256 of the raw file
  duration      REAL DEFAULT 0,
  rights_status TEXT DEFAULT 'review_required',
  downloaded_at REAL,
  meta_json     TEXT DEFAULT '{}'
);

-- the retrievable unit: a segment (video clip) or an image.
CREATE TABLE IF NOT EXISTS assets (
  asset_id       TEXT PRIMARY KEY,
  source_id      TEXT REFERENCES sources(source_id),
  type           TEXT NOT NULL,        -- video | image | graphic | map
  file           TEXT,                 -- path under library/objects/ (materialized on approval)
  sha256         TEXT,                 -- content hash of the segment/image file (dedup)
  start_ms       INTEGER,              -- for video segments; NULL for images
  end_ms         INTEGER,
  description    TEXT DEFAULT '',
  era_from       INTEGER,
  era_to         INTEGER,
  quality        TEXT DEFAULT 'medium',-- low | medium | high
  clean          INTEGER DEFAULT 1,    -- 0 if big burned-in caption/logo mid-frame
  ocr_text       TEXT DEFAULT '[]',
  identity_conf  REAL DEFAULT 0,
  match_conf     REAL DEFAULT 0,
  review_status  TEXT DEFAULT 'needs_review',  -- needs_review | approved | rejected | quarantined
  rights_status  TEXT DEFAULT 'review_required',
  lang           TEXT DEFAULT 'en',    -- catalog language (always en for the shared library)
  times_used     INTEGER DEFAULT 0,
  catalog_json   TEXT DEFAULT '{}',    -- {schema_version, model, prompt_version}
  created_at     REAL
);
CREATE INDEX IF NOT EXISTS ix_assets_type    ON assets(type);
CREATE INDEX IF NOT EXISTS ix_assets_review  ON assets(review_status);
CREATE UNIQUE INDEX IF NOT EXISTS ux_assets_seg ON assets(source_id, start_ms, end_ms);

-- canonical entities + aliases (the language bridge)
CREATE TABLE IF NOT EXISTS entities (
  entity_id    TEXT PRIMARY KEY,       -- ORG_NIKE, PERSON_PHIL_KNIGHT, MFR_SWIFT__RANGE_CARRERA
  kind         TEXT,                   -- org | person | product | place | event
  display_name TEXT,
  aliases_json TEXT DEFAULT '[]'       -- ["Nike Inc", "Nike, Inc.", "耐克"] — any language
);
CREATE TABLE IF NOT EXISTS asset_entities (
  asset_id   TEXT REFERENCES assets(asset_id),
  entity_id  TEXT REFERENCES entities(entity_id),
  confidence REAL DEFAULT 1.0,
  PRIMARY KEY (asset_id, entity_id)
);
CREATE INDEX IF NOT EXISTS ix_ae_entity ON asset_entities(entity_id);

-- collections = the conceptual layers, as many-to-many tags
CREATE TABLE IF NOT EXISTS collections (
  collection_id TEXT PRIMARY KEY,      -- COL_DOMAIN_MOTORHOMES, COL_ENTITY_NIKE, ...
  layer         TEXT,                  -- COMMON | DOMAIN | ENTITY | PROJECT | GENERATED
  name          TEXT
);
CREATE TABLE IF NOT EXISTS collection_assets (
  collection_id TEXT REFERENCES collections(collection_id),
  asset_id      TEXT REFERENCES assets(asset_id),
  PRIMARY KEY (collection_id, asset_id)
);
CREATE INDEX IF NOT EXISTS ix_ca_asset ON collection_assets(asset_id);

-- usage events power diversity/cooldown (not just binary coverage)
CREATE TABLE IF NOT EXISTS usage_events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id   TEXT REFERENCES assets(asset_id),
  channel    TEXT,
  video_id   TEXT,
  used_at    REAL
);
CREATE INDEX IF NOT EXISTS ix_usage_asset ON usage_events(asset_id);
"""


# ======================================================================
class Catalog:
    def __init__(self, db_path: str | os.PathLike = DB_PATH):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        OBJECTS_DIR.mkdir(parents=True, exist_ok=True)
        self.cx = sqlite3.connect(self.db_path)
        self.cx.row_factory = sqlite3.Row
        self.cx.execute("PRAGMA journal_mode=WAL;")     # concurrent-safe writes
        self.cx.execute("PRAGMA foreign_keys=ON;")
        self.cx.executescript(_SCHEMA)
        self._migrate()

    def close(self):
        self.cx.close()

    # -- migrations (bump SCHEMA_VERSION + add an if-block when the schema changes) --
    def _migrate(self):
        cur = self.cx.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        have = int(cur["value"]) if cur else 0
        if have < SCHEMA_VERSION:
            # future ALTER TABLEs go here, guarded by `if have < N`
            self.cx.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                            (str(SCHEMA_VERSION),))
            self.cx.commit()

    # ------------------------------------------------------------------ entities
    def upsert_entity(self, entity_id: str, kind: str, display_name: str,
                      aliases: Iterable[str] = ()):
        self.cx.execute(
            "INSERT INTO entities(entity_id,kind,display_name,aliases_json) VALUES(?,?,?,?) "
            "ON CONFLICT(entity_id) DO UPDATE SET kind=excluded.kind,"
            "display_name=excluded.display_name,aliases_json=excluded.aliases_json",
            (entity_id, kind, display_name, json.dumps(list(aliases))))
        self.cx.commit()

    def resolve_alias(self, text: str) -> Optional[str]:
        """Map any-language surface form -> canonical entity_id (the language bridge)."""
        t = text.strip().lower()
        for r in self.cx.execute("SELECT entity_id,display_name,aliases_json FROM entities"):
            if t == (r["display_name"] or "").lower():
                return r["entity_id"]
            if t in [a.lower() for a in json.loads(r["aliases_json"] or "[]")]:
                return r["entity_id"]
        return None

    # ------------------------------------------------------------------ collections
    def ensure_collection(self, collection_id: str, layer: str, name: str = ""):
        if layer not in VALID_LAYERS:
            raise ValueError(f"layer must be one of {VALID_LAYERS}, got {layer}")
        self.cx.execute(
            "INSERT OR IGNORE INTO collections(collection_id,layer,name) VALUES(?,?,?)",
            (collection_id, layer, name or collection_id))
        self.cx.commit()

    def tag(self, asset_id: str, collection_id: str):
        self.cx.execute("INSERT OR IGNORE INTO collection_assets VALUES(?,?)",
                        (collection_id, asset_id))
        self.cx.commit()

    # ------------------------------------------------------------------ sources / assets
    def add_source(self, source_id: str, url: str, kind: str, content_hash: str,
                   channel: str = "", channel_trust: str = "unknown",
                   duration: float = 0, rights_status: str = "review_required",
                   meta: dict = None):
        self.cx.execute(
            "INSERT OR IGNORE INTO sources(source_id,url,kind,channel,channel_trust,"
            "content_hash,duration,rights_status,downloaded_at,meta_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (source_id, url, kind, channel, channel_trust, content_hash, duration,
             rights_status, time.time(), json.dumps(meta or {})))
        self.cx.commit()

    def add_asset(self, asset_id: str, type: str, source_id: str = None, *,
                  file: str = "", sha256: str = "", start_ms: int = None, end_ms: int = None,
                  description: str = "", era_from: int = None, era_to: int = None,
                  quality: str = "medium", clean: bool = True, ocr_text: list = None,
                  identity_conf: float = 0, match_conf: float = 0,
                  review_status: str = "needs_review", rights_status: str = "review_required",
                  lang: str = "en", entities: list = None, collections: list = None,
                  catalog: dict = None):
        """Insert a segment/image. Idempotent on (source_id,start_ms,end_ms). Never duplicates."""
        self.cx.execute(
            "INSERT OR IGNORE INTO assets(asset_id,source_id,type,file,sha256,start_ms,end_ms,"
            "description,era_from,era_to,quality,clean,ocr_text,identity_conf,match_conf,"
            "review_status,rights_status,lang,times_used,catalog_json,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
            (asset_id, source_id, type, file, sha256, start_ms, end_ms, description,
             era_from, era_to, quality, int(clean), json.dumps(ocr_text or []),
             identity_conf, match_conf, review_status, rights_status, lang,
             json.dumps(catalog or {"schema_version": f"seg-v{SCHEMA_VERSION}"}), time.time()))
        for eid in (entities or []):
            self.cx.execute("INSERT OR IGNORE INTO asset_entities(asset_id,entity_id) VALUES(?,?)",
                            (asset_id, eid))
        for cid in (collections or []):
            self.cx.execute("INSERT OR IGNORE INTO collection_assets VALUES(?,?)", (cid, asset_id))
        self.cx.commit()

    def set_review(self, asset_id: str, review_status: str, rights_status: str = None):
        if rights_status is not None:
            self.cx.execute("UPDATE assets SET review_status=?,rights_status=? WHERE asset_id=?",
                            (review_status, rights_status, asset_id))
        else:
            self.cx.execute("UPDATE assets SET review_status=? WHERE asset_id=?",
                            (review_status, asset_id))
        self.cx.commit()

    def mark_used(self, asset_id: str, channel: str = "", video_id: str = ""):
        self.cx.execute("UPDATE assets SET times_used=times_used+1 WHERE asset_id=?", (asset_id,))
        self.cx.execute("INSERT INTO usage_events(asset_id,channel,video_id,used_at) VALUES(?,?,?,?)",
                        (asset_id, channel, video_id, time.time()))
        self.cx.commit()

    # ------------------------------------------------------------------ RETRIEVAL (default-deny)
    def search(self, *, type: str = None, required_all: list = None, required_any: list = None,
               forbidden: list = None, min_quality: str = "medium", era: tuple = None,
               scope_collections: list = None, cooldown_channel: str = None,
               max_uses: int = None, top_k: int = 10) -> list[dict]:
        """
        Return renderable assets, most-relevant first. FAIL-CLOSED:
          * review_status must be 'approved'
          * rights_status must be in ALLOWED_RIGHTS
        Entity logic: required_all (every id present) AND required_any (>=1) AND no forbidden id.
        Media type is honored. scope_collections limits leakage across niches/projects.
        """
        qrank = {"low": 0, "medium": 1, "high": 2}
        min_q = qrank.get(min_quality, 1)
        required_all = required_all or []
        required_any = required_any or []
        forbidden = set(forbidden or [])

        rows = self.cx.execute(
            "SELECT * FROM assets WHERE review_status='approved'").fetchall()
        out = []
        for r in rows:
            # GATE: rights (default-deny — NULL/unknown rejected)
            if r["rights_status"] not in ALLOWED_RIGHTS:
                continue
            # GATE: media type
            if type and r["type"] != type:
                continue
            # GATE: quality
            if qrank.get(r["quality"], 1) < min_q:
                continue
            # GATE: era overlap
            if era and (r["era_from"] or r["era_to"]):
                lo, hi = era
                if r["era_to"] and r["era_to"] < lo:  # asset entirely before window
                    continue
                if r["era_from"] and r["era_from"] > hi:
                    continue
            # entity set for this asset
            ents = {x["entity_id"] for x in self.cx.execute(
                "SELECT entity_id FROM asset_entities WHERE asset_id=?", (r["asset_id"],))}
            # GATE: forbidden
            if ents & forbidden:
                continue
            # GATE: required_all
            if required_all and not set(required_all).issubset(ents):
                continue
            # GATE: required_any
            if required_any and not (set(required_any) & ents):
                continue
            # GATE: scope (limit to the project's collections)
            if scope_collections:
                cols = {x["collection_id"] for x in self.cx.execute(
                    "SELECT collection_id FROM collection_assets WHERE asset_id=?", (r["asset_id"],))}
                if not (set(scope_collections) & cols):
                    continue
            # GATE: cooldown / reuse cap
            if max_uses is not None:
                used = self.cx.execute(
                    "SELECT COUNT(*) c FROM usage_events WHERE asset_id=? AND channel=?",
                    (r["asset_id"], cooldown_channel or "")).fetchone()["c"]
                if used >= max_uses:
                    continue

            # --- score (gates passed) ---
            score = qrank.get(r["quality"], 1) * 1.0
            score += len(ents & set(required_all + required_any)) * 2.0
            score += r["match_conf"] or 0
            score -= min((r["times_used"] or 0) * 0.2, 1.5)   # spread usage
            out.append({**dict(r), "entities": sorted(ents), "score": round(score, 3)})

        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:top_k]

    # ------------------------------------------------------------------ export / stats
    def export_jsonl(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            for r in self.cx.execute("SELECT * FROM assets"):
                f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")

    def stats(self) -> dict:
        g = lambda q: self.cx.execute(q).fetchone()[0]
        return {
            "sources": g("SELECT COUNT(*) FROM sources"),
            "assets": g("SELECT COUNT(*) FROM assets"),
            "approved": g("SELECT COUNT(*) FROM assets WHERE review_status='approved'"),
            "entities": g("SELECT COUNT(*) FROM entities"),
            "collections": g("SELECT COUNT(*) FROM collections"),
        }


if __name__ == "__main__":
    c = Catalog(DB_PATH)
    print("[catalog] db:", c.db_path)
    print("[catalog] stats:", c.stats())
