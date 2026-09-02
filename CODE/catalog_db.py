#!/usr/bin/env python3
"""
catalog_db.py — CDev's operational catalog (SQLite, hardened).

See FOUNDATION.md. This is storage + retrieval only; scraping/cataloging/rendering write THROUGH it.

P0A-hardening in this version:
  * Real content-addressed object store: `ingest_file()` hashes (SHA-256) and stores each media
    file ONCE under objects/<hh>/<hash>.<ext>; unique hash enforced; duplicates are detected.
  * Relative paths only (drive-letter safe): the DB stores `objects/ab/hash.mp4`, resolved against
    config.library_root() at runtime. Change the SSD letter -> edit config, never the DB.
  * FTS5 relevance search over description + entities + actions + environment (the "right clip").
  * Fail-closed retrieval: review_status='approved' AND clean_status in (clean|fixable) AND the
    object file actually EXISTS AND (era known if era required) AND type/entity/era gates.
    (Per operator decision, rights is NOT a gate — copyright posture is the <=7s clip cap instead.)
  * Entity aliases NORMALIZED (accents/punct stripped); ambiguous alias returns None + candidates,
    never an arbitrary first match.
  * Schema CHECK constraints (type/quality/status enums, start<end, confidence 0..1) + unique hash.
  * Multi-table writes are transactional. Consistent backup via the SQLite backup API.
"""
from __future__ import annotations
import os
import re
import json
import time
import shutil
import hashlib
import sqlite3
import unicodedata
import mimetypes
from pathlib import Path
from typing import Optional

import config

SCHEMA_VERSION = 3
VALID_LAYERS = {"COMMON", "DOMAIN", "ENTITY", "PROJECT", "GENERATED"}


# ======================================================================
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

-- one physical media file, stored ONCE by content hash. rel_path is relative to library_root.
CREATE TABLE IF NOT EXISTS objects (
  sha256     TEXT PRIMARY KEY,
  rel_path   TEXT UNIQUE NOT NULL,
  size_bytes INTEGER,
  mime       TEXT,
  created_at REAL
);

-- a downloaded source master (dedup + provenance). Its media is an object (content_hash).
CREATE TABLE IF NOT EXISTS sources (
  source_id     TEXT PRIMARY KEY,
  url           TEXT,
  kind          TEXT,
  channel       TEXT,
  channel_trust TEXT,
  content_hash  TEXT REFERENCES objects(sha256),
  duration      REAL DEFAULT 0,
  downloaded_at REAL,
  meta_json     TEXT DEFAULT '{}'
);

-- the retrievable unit: an image (object_sha set) OR a virtual video segment (source_id + ms range).
CREATE TABLE IF NOT EXISTS assets (
  asset_id      TEXT PRIMARY KEY,
  source_id     TEXT REFERENCES sources(source_id),
  object_sha    TEXT REFERENCES objects(sha256),
  type          TEXT NOT NULL CHECK (type IN ('video','image','graphic','map')),
  start_ms      INTEGER,
  end_ms        INTEGER,
  description   TEXT DEFAULT '',
  era_from      INTEGER,
  era_to        INTEGER,
  quality       TEXT DEFAULT 'medium' CHECK (quality IN ('low','medium','high')),
  clean_status  TEXT DEFAULT 'clean'  CHECK (clean_status IN ('clean','fixable','unusable')),
  ocr_text      TEXT DEFAULT '[]',
  identity_conf REAL DEFAULT 0 CHECK (identity_conf BETWEEN 0 AND 1),
  match_conf    REAL DEFAULT 0 CHECK (match_conf BETWEEN 0 AND 1),
  review_status TEXT DEFAULT 'needs_review'
                CHECK (review_status IN ('needs_review','approved','rejected','quarantined')),
  rights_status TEXT DEFAULT 'unknown',   -- metadata only; NOT a retrieval gate (operator decision)
  lang          TEXT DEFAULT 'en',
  times_used    INTEGER DEFAULT 0,
  catalog_json  TEXT DEFAULT '{}',
  created_at    REAL,
  CHECK (start_ms IS NULL OR end_ms IS NULL OR start_ms < end_ms),
  CHECK (object_sha IS NOT NULL OR source_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_assets_type   ON assets(type);
CREATE INDEX IF NOT EXISTS ix_assets_review ON assets(review_status);
CREATE UNIQUE INDEX IF NOT EXISTS ux_assets_seg ON assets(source_id, start_ms, end_ms);

CREATE TABLE IF NOT EXISTS entities (
  entity_id    TEXT PRIMARY KEY,
  kind         TEXT,
  display_name TEXT
);
-- normalized aliases (accents/punct stripped). Ambiguity is resolved by the caller, never guessed.
CREATE TABLE IF NOT EXISTS entity_aliases (
  alias_norm TEXT NOT NULL,
  entity_id  TEXT NOT NULL REFERENCES entities(entity_id),
  language   TEXT DEFAULT 'und',
  PRIMARY KEY (alias_norm, entity_id)
);
CREATE INDEX IF NOT EXISTS ix_alias ON entity_aliases(alias_norm);

CREATE TABLE IF NOT EXISTS asset_entities (
  asset_id   TEXT REFERENCES assets(asset_id),
  entity_id  TEXT REFERENCES entities(entity_id),
  confidence REAL DEFAULT 1.0,
  PRIMARY KEY (asset_id, entity_id)
);
CREATE INDEX IF NOT EXISTS ix_ae_entity ON asset_entities(entity_id);

CREATE TABLE IF NOT EXISTS collections (
  collection_id TEXT PRIMARY KEY,
  layer         TEXT,
  name          TEXT,
  parent_id     TEXT
);
CREATE TABLE IF NOT EXISTS collection_assets (
  collection_id TEXT REFERENCES collections(collection_id),
  asset_id      TEXT REFERENCES assets(asset_id),
  PRIMARY KEY (collection_id, asset_id)
);
CREATE INDEX IF NOT EXISTS ix_ca_asset ON collection_assets(asset_id);

CREATE TABLE IF NOT EXISTS usage_events (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id TEXT REFERENCES assets(asset_id),
  channel  TEXT,
  video_id TEXT,
  used_at  REAL
);
CREATE INDEX IF NOT EXISTS ix_usage_asset ON usage_events(asset_id);

CREATE VIRTUAL TABLE IF NOT EXISTS assets_fts USING fts5(asset_id UNINDEXED, body);

-- Gemini result cache: same source+model+prompt+schema => never re-charged.
CREATE TABLE IF NOT EXISTS catalog_cache (
  cache_key   TEXT PRIMARY KEY,
  result_json TEXT,
  created_at  REAL
);
"""


def _norm_alias(s: str) -> str:
    # strip accents, lowercase, keep unicode letters/digits (so CJK/Cyrillic aliases survive)
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", " ", s.lower(), flags=re.UNICODE).strip()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Catalog:
    def __init__(self, db_path: str | os.PathLike = None):
        self.db_path = str(db_path or config.db_path())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        config.objects_dir().mkdir(parents=True, exist_ok=True)
        self.cx = sqlite3.connect(self.db_path)
        self.cx.row_factory = sqlite3.Row
        self.cx.execute("PRAGMA journal_mode=WAL;")
        self.cx.execute("PRAGMA foreign_keys=ON;")
        self.cx.executescript(_SCHEMA)
        self._migrate()

    def close(self):
        self.cx.close()

    def _migrate(self):
        cur = self.cx.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        have = int(cur["value"]) if cur else 0
        if have < SCHEMA_VERSION:
            with self.cx:
                self.cx.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                                (str(SCHEMA_VERSION),))

    # ------------------------------------------------------------------ object store
    def ingest_file(self, src_path: str | os.PathLike) -> dict:
        """Content-address a media file: store ONCE under objects/<hh>/<hash>.<ext>.
        Returns {sha256, rel_path, existing}. Same bytes -> same object, no duplicate copy."""
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(src)
        sha = _sha256(src)
        row = self.cx.execute("SELECT rel_path FROM objects WHERE sha256=?", (sha,)).fetchone()
        if row:
            return {"sha256": sha, "rel_path": row["rel_path"], "existing": True}
        ext = src.suffix.lower()
        rel = f"objects/{sha[:2]}/{sha}{ext}"
        dest = config.library_root() / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        mime = mimetypes.guess_type(str(dest))[0] or ""
        with self.cx:
            self.cx.execute(
                "INSERT INTO objects(sha256,rel_path,size_bytes,mime,created_at) VALUES(?,?,?,?,?)",
                (sha, rel, dest.stat().st_size, mime, time.time()))
        return {"sha256": sha, "rel_path": rel, "existing": False}

    def object_path(self, sha: str) -> Optional[Path]:
        row = self.cx.execute("SELECT rel_path FROM objects WHERE sha256=?", (sha,)).fetchone()
        return (config.library_root() / row["rel_path"]) if row else None

    def _asset_object_sha(self, r: sqlite3.Row) -> Optional[str]:
        if r["object_sha"]:
            return r["object_sha"]
        if r["source_id"]:
            s = self.cx.execute("SELECT content_hash FROM sources WHERE source_id=?",
                                (r["source_id"],)).fetchone()
            return s["content_hash"] if s else None
        return None

    def _file_exists(self, r: sqlite3.Row) -> bool:
        sha = self._asset_object_sha(r)
        if not sha:
            return False
        p = self.object_path(sha)
        return bool(p and p.exists())

    # ------------------------------------------------------------------ entities + aliases
    def upsert_entity(self, entity_id: str, kind: str, display_name: str, aliases=()):
        with self.cx:
            self.cx.execute(
                "INSERT INTO entities(entity_id,kind,display_name) VALUES(?,?,?) "
                "ON CONFLICT(entity_id) DO UPDATE SET kind=excluded.kind,"
                "display_name=excluded.display_name", (entity_id, kind, display_name))
            for a in [display_name, *aliases]:
                n = _norm_alias(a)
                if n:
                    self.cx.execute(
                        "INSERT OR IGNORE INTO entity_aliases(alias_norm,entity_id) VALUES(?,?)",
                        (n, entity_id))

    def resolve_alias(self, text: str):
        """Return canonical entity_id if the alias maps to exactly one entity, else None.
        Ambiguous or unknown -> None (never an arbitrary pick). Use resolve_alias_candidates for detail."""
        cands = self.resolve_alias_candidates(text)
        return cands[0] if len(cands) == 1 else None

    def resolve_alias_candidates(self, text: str) -> list[str]:
        n = _norm_alias(text)
        rows = self.cx.execute(
            "SELECT DISTINCT entity_id FROM entity_aliases WHERE alias_norm=?", (n,)).fetchall()
        return [r["entity_id"] for r in rows]

    # ------------------------------------------------------------------ collections
    def ensure_collection(self, collection_id: str, layer: str, name: str = "", parent_id: str = None):
        if layer not in VALID_LAYERS:
            raise ValueError(f"layer must be one of {VALID_LAYERS}, got {layer}")
        with self.cx:
            self.cx.execute(
                "INSERT OR IGNORE INTO collections(collection_id,layer,name,parent_id) VALUES(?,?,?,?)",
                (collection_id, layer, name or collection_id, parent_id))

    def tag(self, asset_id: str, collection_id: str):
        with self.cx:
            self.cx.execute("INSERT OR IGNORE INTO collection_assets VALUES(?,?)",
                            (collection_id, asset_id))

    # ------------------------------------------------------------------ sources
    def add_source(self, source_id: str, url: str, kind: str, content_hash: str = None,
                   channel: str = "", channel_trust: str = "unknown", duration: float = 0,
                   meta: dict = None):
        with self.cx:
            self.cx.execute(
                "INSERT OR IGNORE INTO sources(source_id,url,kind,channel,channel_trust,"
                "content_hash,duration,downloaded_at,meta_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (source_id, url, kind, channel, channel_trust, content_hash, duration,
                 time.time(), json.dumps(meta or {})))

    # ------------------------------------------------------------------ assets
    def add_asset(self, asset_id: str, type: str, *, source_id: str = None, object_sha: str = None,
                  start_ms: int = None, end_ms: int = None, description: str = "",
                  era_from: int = None, era_to: int = None, quality: str = "medium",
                  clean_status: str = "clean", ocr_text: list = None, identity_conf: float = 0,
                  match_conf: float = 0, review_status: str = "needs_review",
                  rights_status: str = "unknown", lang: str = "en", entities: list = None,
                  collections: list = None, catalog: dict = None):
        """Insert an image (object_sha) or a virtual video segment (source_id + ms range).
        Idempotent on (source_id,start_ms,end_ms). Writes the FTS body + entity/collection links
        in ONE transaction so a partial failure commits nothing."""
        _cat = catalog or {}
        body = " ".join(filter(None, [description, " ".join(entities or []),
                                       " ".join(_cat.get("actions", [])),
                                       " ".join(_cat.get("environment", [])),
                                       " ".join(_cat.get("serves", [])),      # narrator-intent search
                                       " ".join(_cat.get("keywords", [])),     # the real search engine
                                       " ".join(_cat.get("objects", [])),
                                       " ".join(_cat.get("places", []))]))
        # idempotency PRE-CHECK (so a plain INSERT can still raise on CHECK violations —
        # INSERT OR IGNORE would silently swallow bad data like start_ms > end_ms).
        dup = self.cx.execute("SELECT 1 FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        if not dup and source_id is not None and start_ms is not None:
            dup = self.cx.execute(
                "SELECT 1 FROM assets WHERE source_id=? AND start_ms=? AND end_ms=?",
                (source_id, start_ms, end_ms)).fetchone()
        if dup:
            return False
        with self.cx:
            self.cx.execute(
                "INSERT INTO assets(asset_id,source_id,object_sha,type,start_ms,end_ms,"
                "description,era_from,era_to,quality,clean_status,ocr_text,identity_conf,match_conf,"
                "review_status,rights_status,lang,times_used,catalog_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
                (asset_id, source_id, object_sha, type, start_ms, end_ms, description, era_from,
                 era_to, quality, clean_status, json.dumps(ocr_text or []), identity_conf, match_conf,
                 review_status, rights_status, lang, json.dumps(catalog or {}), time.time()))
            self.cx.execute("INSERT INTO assets_fts(asset_id,body) VALUES(?,?)", (asset_id, body))
            for eid in (entities or []):
                self.cx.execute("INSERT OR IGNORE INTO asset_entities(asset_id,entity_id) VALUES(?,?)",
                                (asset_id, eid))
            for cid in (collections or []):
                self.cx.execute("INSERT OR IGNORE INTO collection_assets VALUES(?,?)", (cid, asset_id))
        return True

    def auto_approve(self, asset_id: str):
        """Full-auto approval guard: approve only if clean/fixable AND match_conf>=threshold AND the
        object file exists; otherwise quarantine. Returns the resulting status."""
        r = self.cx.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        if r is None:
            return None
        ok = (r["clean_status"] in ("clean", "fixable")
              and (r["match_conf"] or 0) >= config.AUTO_APPROVE_CONF
              and self._file_exists(r))
        status = "approved" if ok else "quarantined"
        with self.cx:
            self.cx.execute("UPDATE assets SET review_status=? WHERE asset_id=?", (status, asset_id))
        return status

    def set_review(self, asset_id: str, review_status: str):
        with self.cx:
            self.cx.execute("UPDATE assets SET review_status=? WHERE asset_id=?",
                            (review_status, asset_id))

    def mark_used(self, asset_id: str, channel: str = "", video_id: str = ""):
        with self.cx:
            self.cx.execute("UPDATE assets SET times_used=times_used+1 WHERE asset_id=?", (asset_id,))
            self.cx.execute("INSERT INTO usage_events(asset_id,channel,video_id,used_at) "
                            "VALUES(?,?,?,?)", (asset_id, channel, video_id, time.time()))

    # ------------------------------------------------------------------ RETRIEVAL
    def search(self, *, query_text: str = None, type: str = None, required_all: list = None,
               required_any: list = None, forbidden: list = None, min_quality: str = "low",
               era: tuple = None, allow_unknown_era: bool = False, min_match_conf: float = 0.0,
               scope_collections: list = None, cooldown_channel: str = None,
               exclude_last_n: int = None, max_channel_uses: int = None, top_k: int = 10) -> list[dict]:
        """Fail-closed retrieval. An asset surfaces only if it is approved, clean/fixable, its file
        exists, and it passes type/entity/era/quality gates. query_text adds FTS relevance ranking."""
        qrank = {"low": 0, "medium": 1, "high": 2}
        min_q = qrank.get(min_quality, 0)
        required_all, required_any = required_all or [], required_any or []
        forbidden = set(forbidden or [])

        fts_rank = {}
        if query_text:
            # FTS5 MATCH defaults to AND across terms, which returns nothing for a natural-language
            # query ("Tyson punching aggressive"). Relevance search needs OR + bm25 ranking, so more
            # matched terms simply rank higher. Terms are sanitised (FTS5 syntax chars would throw).
            terms = [t for t in re.findall(r"\w+", (query_text or "").lower()) if len(t) > 2]
            if terms:
                expr = " OR ".join(f'"{t}"' for t in terms)
                try:
                    for r in self.cx.execute(
                            "SELECT asset_id, bm25(assets_fts) AS r FROM assets_fts "
                            "WHERE assets_fts MATCH ? ORDER BY r", (expr,)):
                        fts_rank[r["asset_id"]] = r["r"]     # lower bm25 = better
                except sqlite3.OperationalError:
                    fts_rank = {}
            if not fts_rank:
                return []                                     # query given but nothing matched

        rows = self.cx.execute("SELECT * FROM assets WHERE review_status='approved'").fetchall()
        out = []
        for r in rows:
            if query_text and r["asset_id"] not in fts_rank:
                continue
            if r["clean_status"] == "unusable":               # fail-closed on unusable footage
                continue
            if not self._file_exists(r):                      # object must actually exist on disk
                continue
            if type and r["type"] != type:
                continue
            if qrank.get(r["quality"], 1) < min_q:
                continue
            if (r["match_conf"] or 0) < min_match_conf:
                continue
            if era:
                known = r["era_from"] is not None or r["era_to"] is not None
                if not known:
                    if not allow_unknown_era:
                        continue
                else:
                    lo, hi = era
                    if (r["era_to"] is not None and r["era_to"] < lo) or \
                       (r["era_from"] is not None and r["era_from"] > hi):
                        continue
            ents = {x["entity_id"] for x in self.cx.execute(
                "SELECT entity_id FROM asset_entities WHERE asset_id=?", (r["asset_id"],))}
            if ents & forbidden:
                continue
            if required_all and not set(required_all).issubset(ents):
                continue
            if required_any and not (set(required_any) & ents):
                continue
            if scope_collections:
                cols = {x["collection_id"] for x in self.cx.execute(
                    "SELECT collection_id FROM collection_assets WHERE asset_id=?", (r["asset_id"],))}
                if not (set(scope_collections) & cols):
                    continue
            # diversity / cooldown
            if cooldown_channel is not None and (max_channel_uses is not None or exclude_last_n):
                used = self.cx.execute(
                    "SELECT COUNT(*) c FROM usage_events WHERE asset_id=? AND channel=?",
                    (r["asset_id"], cooldown_channel)).fetchone()["c"]
                if max_channel_uses is not None and used >= max_channel_uses:
                    continue
                if exclude_last_n:
                    recent = [x["asset_id"] for x in self.cx.execute(
                        "SELECT asset_id FROM usage_events WHERE channel=? ORDER BY id DESC LIMIT ?",
                        (cooldown_channel, exclude_last_n))]
                    if r["asset_id"] in recent:
                        continue

            score = qrank.get(r["quality"], 1) * 1.0
            score += len(ents & set(required_all + required_any)) * 2.0
            score += (r["match_conf"] or 0)
            if r["asset_id"] in fts_rank:
                # SQLite bm25() returns a NEGATIVE score where MORE negative = BETTER match, so
                # relevance is -bm25. (The old `5.0 + bm25` inverted this: the best matches clamped
                # to 0 and the weakest scored highest — every query returned near-misses.)
                score += min(8.0, -fts_rank[r["asset_id"]])
            score -= min((r["times_used"] or 0) * 0.2, 1.5)
            out.append({**dict(r), "entities": sorted(ents), "score": round(score, 3)})

        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:top_k]

    # ------------------------------------------------------------------ gemini result cache
    def get_cache(self, cache_key: str):
        r = self.cx.execute("SELECT result_json FROM catalog_cache WHERE cache_key=?",
                            (cache_key,)).fetchone()
        return json.loads(r["result_json"]) if r else None

    def put_cache(self, cache_key: str, result):
        with self.cx:
            self.cx.execute("INSERT OR REPLACE INTO catalog_cache(cache_key,result_json,created_at) "
                            "VALUES(?,?,?)", (cache_key, json.dumps(result), time.time()))

    # ------------------------------------------------------------------ backup / export / stats
    def backup(self, dest: str | os.PathLike):
        """Consistent snapshot via the SQLite backup API (safe even in WAL mode)."""
        b = sqlite3.connect(str(dest))
        with b:
            self.cx.backup(b)
        b.close()

    def export_jsonl(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            for r in self.cx.execute("SELECT * FROM assets"):
                f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")

    def stats(self) -> dict:
        g = lambda q: self.cx.execute(q).fetchone()[0]
        return {"objects": g("SELECT COUNT(*) FROM objects"),
                "sources": g("SELECT COUNT(*) FROM sources"),
                "assets": g("SELECT COUNT(*) FROM assets"),
                "approved": g("SELECT COUNT(*) FROM assets WHERE review_status='approved'"),
                "entities": g("SELECT COUNT(*) FROM entities"),
                "collections": g("SELECT COUNT(*) FROM collections")}


if __name__ == "__main__":
    c = Catalog()
    print("[catalog] db:", c.db_path)
    print("[catalog] library_root:", config.library_root())
    print("[catalog] stats:", c.stats())
