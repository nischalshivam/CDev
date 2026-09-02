# CHANNELS — the master index

> **This file is the real "main chat".** Sidebar chats are disposable; this index is not. Any chat
> reads it to know what exists, what is done, and what is next. Update it (via `python CODE/sync.py`)
> whenever a channel or video moves forward.

**Shared library:** ONE catalog for every channel below (`<SSD>/catalog.sqlite` + `objects/`).
Channels are separated by *collections*, never by separate libraries. See `FOUNDATION.md`.

---

## Channels

| channel_id | niche | format pack | style pack | videos done | status |
|---|---|---|---|---|---|
| *(test)* `tyson-boxing` | boxing / archival | HISTORY_ARCHIVAL | *(not written yet)* | 1 (test cut) | retrieval fixed; needs typography + SFX pass |
| *(test)* `r107-cars` | classic cars | HISTORY_ARCHIVAL | *(not written yet)* | 1 (test cut) | plumbing test only |

> Add a row per channel. Keep it short — details live in each project folder.

---

## Library snapshot

`library_index.jsonl` in this repo is a text export of every APPROVED asset (id, source, time range,
description, entities, collections, serves, keywords, quality, times_used). It is refreshed by
`python CODE/sync.py`, so you can see what the library holds from any machine — even one without the
SSD attached.

| library | assets | note |
|---|---|---|
| tyson (test) | 198 approved | 5 YouTube sources; 137 shots still unused |

---

## Naming convention (chats + projects)

- **Chat title:** `CDev · <channel_id>` — e.g. `CDev · cycles-uk`. File them all under one sidebar
  group (e.g. "CDev Channels") and pin the master chat.
- **Project folder:** `projects/<channel_id>/<video_slug>/`
- **Style pack:** `PACKS/style/<niche>.yaml`
- **Topic pack:** `PACKS/niche/<slug>.json`

---

## Per-video status legend

`scripted` → `vo` → `clue` → `coverage` → `acquired` → `cataloged` → `rendered` → `published`
