# CDev — FOUNDATION (open-world documentary system)

> **Scope lock:** CDev is ONLY for open-world documentary titles (Nike, watches, yachts,
> animals, cars, businesses…). The movie/TV essay system (ProStudio) stays SEPARATE — do not
> merge or reuse its closed-world architecture here. You may *reference* the royal-news kit's
> tested render tricks later, but never couple the two libraries.

This file is the source of truth for HOW the system works and WHY. Read before touching code.
It exists because the earlier build had a strong architecture but the runtime path was broken
(see §6) and the library design could not scale to many niches at once (see §3–4).

---

## 1. The one idea that changes everything

**A source video is NOT a retrieval unit. A shot/segment is.**

The old `TECH-SCRAPE-BRAIN` mistake was `1 YouTube video = 1 ID = 1 description`. A 30-minute
video holds 200+ visually distinct moments; a single description cannot retrieve any of them.

```
SourceVideo (kept once, for dedup + provenance)
  ├── Segment 001  Phil Knight on stage        [81.2s–87.4s]
  ├── Segment 002  Nike factory line           [120.0s–126.0s]
  └── Segment 003  Air Jordan close-up         [200.0s–205.0s]
```

Everything downstream — search, gates, timeline — operates on **segments**, never on the raw
source. The source row exists only so we never re-download or re-catalog the same file twice.

---

## 2. The pipeline — the real stages

```
1.  TITLE (+ light premise note)          — is the story roughly real? one-line note, not a blocker
2.  CLEAN NARRATION                        — the exact text fed to TTS = single source of truth
3.  VOICEOVER + word timestamps (SRT)      — the sync spine
4.  VISUAL/CLUE SCRIPT (beats)             — per beat: role, entities, era, strictness, must-not-show, query
5.  LIBRARY COVERAGE CHECK                 — what we already have (this is where cost is saved)
6.  DEMAND TICKETS                          — one per genuine gap, merged across all queued scripts
7.  ACQUISITION (free-source ladder)        — library → YouTube → archive.org → Wikimedia → stock
8.  SEGMENT EXTRACTION                       — cut source into candidate shots (scene-aware, not blind)
9.  GEMINI CATALOG (2-pass)                 — source pass → candidate windows; segment pass → verify
10. RETRIEVAL + hard gates + final verify   — right shot for right beat; fail-closed on miss
11. TIMELINE (word-synced) + RENDER         — ffmpeg; one valid graph, one [vout]
12. QC → repair → feedback into library     — human deletes/swaps written back
```

`right clip at the right time` lives in **stage 4 + stage 10**. Everything else serves those two.

---

## 3. The library is five layers, not one flat file

A single `library_root.json` mixes every niche and does not scale. Split by REUSE scope:

| Layer | Examples | Reused by |
|---|---|---|
| **COMMON** | money, city skyline, crowd, factory line, ocean | every niche |
| **DOMAIN** | motorhomes-market, footwear, watchmaking, yacht-building | same industry |
| **ENTITY** | nike/, wildax/, swift-carrera/, rolex/, phil-knight/ | same brand/person |
| **PROJECT** | nike-bankruptcy/, motorhomes-10-to-shift/ | one specific story (evidence) |
| **GENERATED** | charts, timelines, maps, diagrams | claim-specific graphics |

**Why exactly five is structurally enough (not just "enough for now").** The layers are not
topics — they are *reuse scope*, a complete spectrum of "how widely can this clip be reused":

```
COMMON     usable by EVERY niche            (money, crowd, factory, skyline)
DOMAIN     usable by one industry           (footwear, motorhomes, defence, cycling)
ENTITY     usable for one named thing        (Wildax, GMC Sierra, AM General JLTV, a pen model)
PROJECT    usable only for THIS one video    (this story's specific evidence)
GENERATED  we made it ourselves              (charts, title cards, maps)
```

There is no reuse-scope outside that spectrum, so any documentary of any of the 1000s of topics
still slots into one of these. The TOPIC is unlimited (that is a **tag**, added freely); the ROLE
is always one of five. And even if a sixth layer were ever wanted, in SQLite that is just allowing
a new value in the `layer` column — **no media re-copied, no clip re-cataloged, zero cost.** The
"re-do the whole library" fear cannot happen with the tag/collection design.

On-disk shape:

```
library/
  COMMON/            index.json + media/
  DOMAIN/<domain>/   index.json + media/
  ENTITY/<entity>/   index.json + media/
  PROJECT/<slug>/    index.json + media/
  GENERATED/<slug>/  index.json + media/
```

Why this solves the "everything mixes" fear:
- Wrong-brand footage can't leak in — retrieval scopes to `[PROJECT, its ENTITIES, its DOMAIN,
  COMMON]` only, and the exact-entity hard gate rejects the rest.
- After the Nike project, Adidas/Puma videos reuse `DOMAIN/footwear` → progressively cheaper.
- The motorhomes 10-video batch shares one DOMAIN library while each brand stays isolated at
  ENTITY level.

---

## 4. Multi-niche isolation + the "10 → 10 → 10" model

**Rule: one chat/session = one PROJECT (one niche/channel). Never mix niches in a chat.**
Claude does not need the whole corpus — only that project's TopicPack + the scoped library slices
above. This is what keeps 10–20 parallel niches from colliding.

**Incremental library growth (Coverage Planner + Demand Tickets):**

```
Batch 1 (scripts 1–10)   library empty → ~100% gaps → scrape+catalog → library fills
Batch 2 (scripts 11–20)  check batch-1 library → say 60% hits → scrape only the 40% gap
Batch 3 (scripts 21–30)  check last-20 library → say 80% hits → scrape only 20%
```

A **DemandTicket** = "this shot is needed, by these beats/scripts". Tickets that describe the same
shot are **merged** across all queued scripts, so a shot 3 scripts want is scraped + Gemini-cataloged
**once**. This is the mechanism that saves Gemini cost and scrape time — it is not automatic today
and must be built (Phase 2).

---

## 5. Schemas (the contracts everything agrees on)

Two record kinds. Keep them versioned.

**SourceAsset** (one per downloaded file — dedup + provenance, never retrieved directly):
```json
{ "source_id": "SRC_YT_abc123", "url": "...", "channel": "...", "channel_trust": "official|news|unknown",
  "downloaded_at": "...", "content_hash": "...", "duration": 1830.0, "rights_status": "review_required" }
```

**SegmentAsset** (the retrievable unit; this is what LibraryDB stores/searches):
```json
{ "asset_id": "AST_001", "source_id": "SRC_YT_abc123", "layer": "ENTITY/nike",
  "type": "video|image", "file": "library/ENTITY/nike/media/AST_001.mp4",
  "segment": {"start_ms": 81200, "end_ms": 87400},
  "entities": ["Nike","Phil Knight"], "actions": ["speaking"], "environment": ["stage","1980s"],
  "era": {"from": 1980, "to": 1989}, "description": "...", "ocr_text": [], "clean": true,
  "quality": "high", "identity_confidence": 0.9, "match_confidence": 0.86,
  "rights_status": "review_required", "review_status": "approved|needs_review|rejected|quarantined",
  "catalog": {"schema_version": "seg-v1", "model": "gemini-2.5-flash", "prompt_version": "cat-v1"},
  "times_used": 0 }
```

Hard gates read: `review_status ∈ approved` · exact identity where required · required era ·
no forbidden OCR/watermark · rights not `blocked`. (`needs_review`/`rejected`/`quarantined` are
now gated out of retrieval — see §6.)

> **Storage decision (day-one, not deferred):** the operational catalog is **SQLite**
> (`CODE/catalog_db.py`), not a flat JSON. Reason: with a queue + many niches, concurrent
> JSON writes corrupt, there are no transactions/indexes, and a crash mid-write can lose the
> whole library. SQLite is server-less, built-in, WAL-concurrent, atomic and indexed — one
> `.sqlite` file, easy to back up and reuse years later. JSON/JSONL stay ONLY as import/export
> + the Gemini request/response interface, never as the query engine.
>
> **One object, many collections (no duplicate copies).** A media file is stored ONCE by content
> hash under `library/objects/`. The five layers are **collections (tags)**, many-to-many — an
> asset can be in COMMON + DOMAIN + ENTITY + PROJECT at once without being copied. This is what
> makes delete / rights-update / `times_used` unambiguous and keeps storage small.

---

## 5b. Language — one English library serves every language

The user publishes in multiple languages (EN/ES/FR/DE…), but sources + the library stay English.
The **canonical entity ID is the bridge** (and it also solves the "exact model identity" gate):

```
Spanish script "Nike en quiebra"
  → Stage 0 clean + lock  (Spanish narration + Spanish TTS + Spanish SRT)   [per language]
  → entity resolve        "Nike" / "耐克" / alias  →  ORG_NIKE  (canonical, language-neutral)
  → library search + scrape + Gemini catalog:  ALL ENGLISH, keyed by ORG_NIKE
  → beats: narration in Spanish, entities as canonical IDs
  → render: Spanish audio + Spanish text overlays + the SAME English-cataloged clips
```

Rules:
- **English / canonical only:** library, catalog metadata, search queries, entity IDs.
- **Per-language only:** narration text, TTS voice, on-screen text, SRT — each locked+hashed
  separately in Stage 0.
- One story in 4 languages = **1 shared library**, 4 narrations/TTS/timelines. Big saving.
- `entities.aliases_json` holds surface forms in any language → `resolve_alias()` maps them to the
  canonical id. Implemented + tested in `catalog_db.py`.

---

## 5c. Locked operator decisions (2026-08-24)

1. **Library lives on an external 2TB SSD** (expandable) + periodic manual Drive backup. The tool
   gets full library access from the SSD. → `LIBRARY_ROOT` is a config/env value pointing at the
   SSD, NOT hard-coded in the repo.
2. **⚠️ Drive-letter safety (foundation-critical).** A USB/external SSD's Windows drive letter
   changes on reconnect (E:→F:→G:). SQLite must therefore store **relative paths only**
   (`objects/ab/ab3f.mp4`), resolved against `LIBRARY_ROOT` at runtime. A letter change = edit one
   config value; the database is never rewritten. (The movie system was bitten by absolute paths —
   106 catalog files had to be find/replaced. Do not repeat that here.)
3. **Approval = full-auto**, with the clean/confidence gate as the guard: an asset auto-approves
   only if `clean == true` AND `match_conf >= AUTO_APPROVE_CONF` AND its object file exists;
   otherwise it is `quarantined` (never silently rendered). "Full auto" means the thresholds ARE
   the quality control — set them sensibly and keep a reject/quarantine path.
4. Media stored once on the SSD by content hash under `LIBRARY_ROOT/objects/<hh>/<hash>.<ext>`.

## 5d. Adopted from the final foundation guide + operator overrides (2026-08-24)

**Operator overrides (these WIN over the guide's caution):**
- **Rights is NOT a hard gate.** The operator's posture: commentary/fair-use, and every used clip
  is capped at **≤ 5–7 seconds** — that length cap is the copyright-safety mechanism, not a rights
  database. We still record `source_url` per asset (for attribution + dedup), but `rights_status`
  is metadata, never a retrieval blocker. Do not build a rights-review workflow.
- **Approval = full-auto** (already locked in §5c): clean/confidence/file-exists thresholds are the
  only gate. No manual rights sign-off.

**Shape-level improvements adopted (build lean, but in this shape so it extends without rework):**
1. **Collections are fully generic** — `collections(id, type, name, parent_id, meta)` +
   `asset_collections`. The five layers (COMMON/DOMAIN/ENTITY/PROJECT/GENERATED) are `type` values,
   not columns/folders. A 6th type later = one new row, zero recatalog.
2. **Orthogonal metadata are fields, not tags:** entity, visual_role, shot_type, action, setting,
   era, source, quality, language, on-screen-text. Kept separate from collections.
3. **Format Pack is a third dimension** beside Niche and Style. The 5 samples proved distinct
   grammars: `HISTORY_ARCHIVAL` (cars), `COMPARISON_EVIDENCE` (bikes), `PROCUREMENT_TIMELINE`
   (defence), `PRODUCT_LISTICLE` (motorhomes/pens). Niche = WHAT, Format = HOW the story is told,
   Style = LOOK.
4. **One beat → 1..N shots / composites.** Shot requirements support single clip, ordered montage,
   comparison/split-screen, price/stat card, document overlay, map, timeline, generated graphic.
5. **Ideal plan first, coverage second.** Claude writes the ideal visual plan WITHOUT looking at the
   library; a separate coverage-mapper then labels each requirement EXACT_REUSE / ACCEPTABLE_REUSE /
   COMPOSITE / GENERATE / ACQUIRE. Don't let the current library shrink the creative plan.
6. **Virtual segments:** store `(source, start_ms, end_ms)` in the DB; materialize (cut) the clip
   only when it is actually assigned. Saves disk + encoding.
7. **Gemini result caching:** key on `input_hash + model + prompt_version + schema_version`; never
   re-charge unchanged content. Use Batch API for non-urgent bulk (≈50% cost).
8. **Benchmark gate before bulk spend:** a 5-niche gold set (Recall@5, wrong-entity rate) must pass
   before cataloging thousands of clips. This is the money-safety valve.

**Deliberately deferred (NOT building now — avoids paralysis):** full 30-table schema, PostgreSQL
adapter, embeddings/vector index, perceptual-hash near-dup, full rights model, complete benchmark
harness. Build the lean, correctly-shaped version first; these slot in later without reshaping.

## 6. Phase 0 — what was fixed (with execution evidence) vs still open

**FIXED and verified by running the code:**
1. `LibraryDB.search()` caller mismatch — `demandscout_core.retrieve_assets_for_beat()` passed
   `entities=`/`top_k=` which the signature never had → `TypeError`. Now passes `entity_filter=`,
   `strictness=`, and `search()` accepts `top_k`. ✔ retrieve returns a library hit.
2. Hard-gate scoring `float += "exact"` — gate methods return verdict strings; search now maps
   them via `verdict_score = {"exact":3.0,"downgrade":1.0}` before adding. ✔ no more TypeError.
3. **Retrieval fail-closed gate** — entries with `needs_review` or `review_status ∈
   {rejected,quarantined}` are now skipped in `search()`, so unverified assets can never reach a
   render. ✔ verified (a `needs_review` entry is excluded).
4. `entity_brain.py` heuristic date bug — `(19|20)` capture returned `"19"`; now non-capturing,
   and eras render as decades (`1998 → 1990s`). ✔ verified.

**STILL OPEN (documented honestly, NOT blind-patched):**
- `render_video()` in `demandscout_core.py`: (a) `from CODE.renderer import ...` path is wrong when
  run from inside `CODE/`; (b) the renderer maps `[v0][v1]…` without a concat/xfade chain to a
  single `[vout]`. This can only be fixed and tested against real clips → do it in the Phase-1
  vertical slice, reusing the royal-news `render_test.py` xfade chain as reference (copy the
  technique, not the coupling).
- `source_hunter.py`: only YouTube + Wikimedia hunters exist; archive.org and a proper Pexels
  ambience hunter are NOT built yet. Segment cutting is blind (12/38/62/85% samples), which will
  miss the wanted moment — replace with the 2-pass Gemini candidate-window approach (§2 stage 9).
  It is also not wired into the pipeline and has no persistent seen-state/dedup.
- `entity_brain.py`: LLM pack currently needs `ANTHROPIC_API_KEY`. A Gemini-backed brain path
  should be added so it works with the key already present.
- No SQLite, no vector search, no claim ledger yet — deliberately deferred until the vertical
  slice proves the core loop.

---

## 6b. Clean handling — blur/crop/credit, don't blanket-reject (operator decision)

Observed in the 5 sample videos: real channels keep otherwise-good footage and either (a) show a
small **source credit** overlay ("JAY LENO'S GARAGE", "AM General", "NZ Defence Force"), or the
graphic sits in a corner. Rejecting every clip with a corner logo would starve the library. So:

- **Gemini DETECTS, FFmpeg FIXES.** Gemini can't blur; it returns *where* a logo/subscribe/watermark
  is (corner + rough box) and a `clean` verdict. The pipeline then:
  - **corner logo / subscribe button** → `ffmpeg delogo`/blur/crop that region → usable clip;
  - **mid-frame caption/subtitle block across the subject** → can't blur without hiding the subject
    → **crop** if it's an edge band, else avoid that segment;
  - either way, keep a **source credit** option (matches how the samples handle rights).
- `clean` therefore has three outcomes, not two: `clean` · `fixable` (logo boxed → auto-clean) ·
  `unusable` (caption over subject). Only `unusable` is dropped. This keeps relevant clips instead
  of throwing them away.

## 7. Rights posture (manage, don't ignore, don't freeze)

Free sources are fine for commentary/transformative use, but:
- Prefer **Wikimedia / archive.org / official channels / brand press kits** for anything used
  heavily; use YouTube for discovery + short illustrative clips.
- Record `source_url` + `rights_status` for every asset. Default new YouTube pulls to
  `review_required`; a human moves them to `approved` before they render.
- Never state fabricated criminal/financial wrongdoing as fact in narration (legal exposure).

---

## 8. First real test = ONE vertical slice, not a scrape storm

Take a single script (e.g. `scripts/motorhomes_script.txt`), run the whole loop end-to-end:
pack → beats → coverage → acquire ~5–10 real shots → catalog → retrieval → 60–120s render.
Where it breaks is the real gap list. Only scale to 10-script batches / multi-niche after the
slice passes.

## 9. Phase 0a — SQLite catalog foundation (DONE, tested)

`CODE/catalog_db.py` + `CODE/test_catalog.py` (13 pytest cases, all green). Enforces, with tests:
- default-deny retrieval (approved + rights in {owned,licensed,public_domain,approved_fair_use});
- media-type honored (video request never returns an image);
- entity gates: `required_all` / `required_any` / `forbidden` (not first-match-wins);
- alias → canonical entity id (language bridge);
- segment dedup on (source, start_ms, end_ms);
- era gate; scope-collection isolation (no cross-niche leak); usage cooldown/reuse cap;
- crash-safe persistence (reopen keeps data).

The old `LibraryDB` (flat JSON) in `demandscout.py` is now legacy — `demandscout_core` will be
rewired onto `Catalog` next.

## 10. Still to do before the motorhomes slice (Phase 0b)
- Rewire `demandscout_core.retrieve_assets_for_beat()` onto `Catalog` (media-type + explicit
  fallback chain: video → image+kenburns → graphic → text).
- Stage 0 raw→cleaned→approved narration + SHA-256 lock (per language).
- Beat vs ShotRequirement split (1 beat → 1–3 shots).
- Diversity-aware DemandTicket (variants / seconds / distinct sources / cooldown).
- Synthetic-fixture renderer test (testsrc/color/sine) — concat/xfade/duration/audio-map.
- Project manifest (`workspace/channel/niche/batch/project/script/run` IDs).
- Corrected + source-verified motorhomes Topic Pack.
- (Deferred by user until after the slice: factual claim register.)

*Phase 0a completed + tested: 2026-08-24. Next: Phase 0b, then the motorhomes vertical slice.*
