# CDev — The System Manual

> Read this. It tells you how the entire system works, why it works this way, and how to use it. Every decision is documented here. Every file in the project exists for a reason.

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [The Philosophy](#2-the-philosophy)
3. [Architecture Overview](#3-architecture-overview)
4. [The 3-Pack System](#4-the-3-pack-system)
5. [Pipeline — Step by Step](#5-pipeline--step-by-step)
6. [File Structure Explained](#6-file-structure-explained)
7. [Hard Identity Gates](#7-hard-identity-gates)
8. [Timeline System](#8-timeline-system)
9. [Rendering Strategy](#9-rendering-strategy)
10. [Cost Model](#10-cost-model)
11. [Decision Log](#11-decision-log)
12. [Common Workflows](#12-common-workflows)

---

## 1. The Problem

Traditional narration-driven video automation (thumbnail + AI voiceover + free B-roll) creates thousands of channels that all look identical. The problem isn't the tools — it's the **workflow**:

- **B-roll-first workflow**: Find footage, write script around what's available. Scripts become generic. Viewers become numb.
- **Script-first workflow**: Write narration, THEN find media. Better content, but finding matching footage at scale is the bottleneck.
- **LLM timestamp workflow**: Ask AI "what timestamp in this 10-minute video matches this 3-second narration?" — AI guesses wrong 4/5 times. Wrong clip = wrong variant = bad video.

**CDev solves this with: Script-first, Clue Script (search keys not timestamps), cumulative library, and hard identity gates.**

---

## 2. The Philosophy

### Fail-Closed

If a clip can't be verified, it renders as **still or text card** — never as forced moving footage of the wrong thing. Wrong variant of a vehicle? Still image of the right one, or just text. This is better than "close enough."

### Need-Driven Library

Don't scrape 100 random defence videos. Analyze 50 scripts, extract keywords, check library for gaps, scrape **only what's missing**. Cost drops over time because the library grows.

### Search Keys, Not Timestamps

The Clue Script describes **WHAT to show** (entities, actions, context). The tool searches the library/internet. Timestamps don't work because:
- LLMs can't watch 10-minute videos and find 3-second clips accurately
- Scene detection cuts don't align with narration beats
- Manual timestamping takes longer than the time it saves

### 3-Pack Consistency

Every video is controlled by 3 packs:
1. **Niche Pack** — What entities/actions are valid
2. **Format Pack** — What each video structure looks like
3. **Style Pack** — Color grading, typography, motion, audio

This ensures 50 videos look like they come from the same editor.

### Cumulative Advantage

Video 1: Scrape 20 clips, cost $5
Video 20: Library has 400 clips, reuse 80%, cost $2
Video 50: Library has 1000+ clips, reuse 95%, cost $0.50

---

## 3. Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                    ProClip Engine                         │
├────────────────────┬─────────────────────────────────────┤
│   INPUT LAYER      │  Scripts (.txt) + Audio (.mp3)      │
│                    │  + Niche Pack + Style Pack           │
├────────────────────┼─────────────────────────────────────┤
│   AI LAYER         │  Claude writes Clue Scripts         │
│                    │  (search keys, not timestamps)       │
├────────────────────┼─────────────────────────────────────┤
│   PIPELINE         │  Load → Generate → Retrieve         │
│   (Python)         │  → Build Timeline → Render           │
├────────────────────┼─────────────────────────────────────┤
│   DATA LAYER       │  Library DB (JSON)                  │
│                    │  Queue (JSON)                       │
│                    │  Clue Scripts (JSON)                │
│                    │  Timelines (JSON)                   │
├────────────────────┼─────────────────────────────────────┤
│   OUTPUT           │  MP4 video                          │
│                    │  Timeline JSON (for review)         │
└────────────────────┴─────────────────────────────────────┘
```

### Modules

| Module | File | Job |
|--------|------|-----|
| CLI | `CODE/demandscout.py` | Argument parsing, queue management, status |
| Core | `CODE/demandscout_core.py` | Pipeline orchestration |
| Data Models | Same files | ClipEntry, Job, Beat, Segment |
| Library | `LibraryDB` class | JSON-based media vault with hard gates |
| Queue | `QueueManager` class | Batch job management |
| Scraper | Phase 2 | yt-dlp + scene detection |
| Cataloger | Phase 2 | AI-powered tagging |
| Renderer | Phase 2+ | FFmpeg output |

---

## 4. The 3-Pack System

### Niche Pack (`PACKS/niche/`)

Defines what's valid content for this niche.

```yaml
# PACKS/niche/defence.yaml
name: defence
entities:
  vehicles: [Boxer CRV, ASLAV, Bradley, T-90]
  aircraft: [F-35A, F-35B, Apache, Chinook]
  naval: [destroyer, submarine, aircraft carrier]
actions:
  - military exercise
  - live fire
  - amphibious assault
strictness_rules:
  vehicles: "exact make + model + variant"
  events: "exact event + year"
trusted_channels:
  - "Defence Australia"
  - "US Army"
  - "NATO"
```

### Format Pack (in Clue Script)

Defines what each beat's visual should look like. Built into the Clue Script prompt — output varies by niche.

### Style Pack (`PACKS/style/`)

Defines visual treatment. Separate from niche so you can use the same defence pack with cinematic or clean_doc style.

```yaml
# PACKS/style/cinematic.yaml
color_grade: dramatic
motion: slow_push_in
transitions: fade
typography: Bebas Neue
```

---

## 5. Pipeline — Step by Step

### Step 1: Load Inputs

Read:
- Script (.txt) → narration text
- Audio (.mp3) → duration alignment
- Niche Pack (.yaml) → valid entities/actions
- Style Pack (.yaml) → visual treatment

### Step 2: Generate Clue Script

**Input:** Narration script + niche + style + title

**Output:** Structured JSON with beat-by-beat plans

**How it works:**
1. Read `PROMPTS/CLUE_SCRIPT_PROMPT.md`
2. Fill the input template (niche, title, style, script)
3. Send to Claude
4. Claude returns valid JSON with:
   - `beats[]` — each beat has primary_visual, fallback_visual, last_resort
   - `asset_summary` — total assets needed

**Key principle:** Clue Script contains search keys, NOT timestamps.

### Step 3: Retrieve Assets

**For each beat:**

1. Parse `primary_visual` → entities, actions, context, strictness, media_type
2. Search library with hard gates
3. If match found → use it, increment times_used
4. If partial match → downgrade to image/text card
5. If no match → flag `needs_asset: true` (for scraping queue)

**Hard Gates (order matters):**
1. Entity match (exact match or downgrade based on strictness)
2. Action match (exact or reject)
3. Context match (exact or reject)
4. Quality gate (minimum quality level)
5. THEN rank by relevance score

### Step 4: Build Timeline

**Input:** Beats + matched assets + style config

**Output:** Timeline JSON with segments

For each beat:
- Video match → video clip with motion
- Image match → image with Ken Burns
- Map match → animated map
- No match → text card / generated graphic
- Text overlay specified → additional overlay element

### Step 5: Render

Phase 1: Basic FFmpeg render
- Concatenate clips
- Add narration audio
- Basic text overlays

Phase 2+: Complex filter graphs
- Multi-track audio (narration + music + SFX)
- Smooth transitions
- Color grading
- Motion graphics
- Map animations

---

## 6. File Structure Explained

```
CDev/
├── README.md              # Quick start
├── PROCESS.md             # This file — the complete manual
├── CHANGELOG.md           # Every decision documented
├── TODO.md                # Task tracking
│
├── CODE/                  # Python modules
│   ├── demandscout.py     # Main CLI + data models (Beat, Job, ClipEntry, LibraryDB)
│   └── demandscout_core.py # Core pipeline (process_job function)
│
├── PROMPTS/
│   └── CLUE_SCRIPT_PROMPT.md  # Universal prompt — works for ANY niche
│
├── PACKS/
│   ├── niche/
│   │   └── defence.yaml    # Niche definitions, entities, trusted channels
│   └── style/
│       ├── clean_doc.yaml  # Style definitions, color grade, motion
│       └── cinematic.yaml
│
├── SCRIPTS/
│   └── sample_script.txt   # Example narration script
│
├── QUEUE/                  # Batch jobs
│   └── jobs.json          # Queue data
│
├── CLUES/                  # Generated Clue Scripts (JSON)
├── TIMELINES/              # Generated Timelines (JSON)
├── OUTPUT/                 # Final rendered videos
├── AUDIO/                  # Narration + music
├── RAW/                    # Downloaded raw videos
├── CLIPS/                  # Extracted video clips
├── LIBRARY/                # Curated media vault
│   └── library_root.json   # Library database
├── LOGS/                   # Processing logs
├── STATE/                  # Runtime state files
```

---

## 7. Hard Identity Gates

This is the most important concept in the system. The library search uses **hard gates, not soft ranking**.

### The Problem with Soft Ranking

```
User asks: "Show me Boxer CRV video"
Library has:
  - Boxer CRV video (score: 10)
  - Boxer APC video (score: 9) ← WRONG VARIANT
  - ASLAV video (score: 7)

Soft ranking might pick Boxer APC (score 9) because it's close.
HARD GATES reject it because APC ≠ CRV.
```

### How Hard Gates Work

```
INPUT: "Boxer CRV" + strictness="exact"

GATE 1 — Entity:
  ┌─ Entry has "Boxer CRV"? → PASS (exact)
  ├─ Entry has "Boxer" only? → CHECK strictness
  │  ├─ exact → REJECT
  │  ├─ specific → REJECT
  │  ├─ general → DOWNGRADE score
  │  └─ loose → ACCEPT (downgraded)
  └─ Entry has something else? → REJECT

GATE 2 — Action:
  ┌─ Entry action matches requested? → PASS
  └─ No match? → REJECT

GATE 3 — Context:
  Same logic as action

GATE 4 — Quality:
  ┌─ Entry quality >= requested? → PASS
  └─ No? → REJECT

ALL GATES PASS → Calculate relevance score → Sort by score → Return top N
```

### Strictness Levels

| Level | Use For | Behavior |
|-------|---------|----------|
| `exact` | Specific variant (Boxer CRV, F-35A) | Only exact entity match passes. Everything else rejected. |
| `specific` | Category (Boxer variant, F-35 variant) | Exact or closely related passes. Wrong variant rejected. |
| `general` | Type (military vehicle, fighter jet) | Related entities pass with score penalty |
| `loose` | Ambient B-roll | Anything vaguely related passes, heavily penalized |

### The Library Never Lies

Library entries have:
- `entities[]` — exact entity names
- `actions[]` — what's happening
- `environment[]` — where/when
- `quality` — low/medium/high
- `strictness` — the strictness that was used when cataloging
- `times_used` — reuse counter (penalizes overused clips)

This data is set by the AI cataloger (Gemini Flash/Pro) during cataloging. It doesn't guess — it identifies what's actually in the clip.

---

## 8. Timeline System

### The Timeline JSON

```json
{
  "timeline_id": "TL0001",
  "title": "The Boxer CRV",
  "duration_seconds": 180,
  "audio_file": "audio/S001.mp3",
  "fps": 30,
  "resolution": [1920, 1080],
  "segments": [
    {
      "segment_id": "SEG001",
      "beat_id": "B01",
      "start": 0.0,
      "end": 8.5,
      "narration": "The Boxer CRV is Australia's primary armored vehicle.",
      "items": [
        {
          "type": "video",
          "file": "library/CLP_abc123_Boxer_demo.mp4",
          "motion": "slow_push_in",
          "transition_in": "fade_in"
        }
      ]
    }
  ]
}
```

### Segment Types

| Media Type | Motion | Transition | Use Case |
|------------|--------|------------|----------|
| `video` | push_in/pan/tracking/static | cut/dissolve/fade | Moving footage |
| `image` | ken_burns_zoom_in/static | dissolve | Still photos |
| `map` | zoom_in/pan/globe_rotate | fade_in/dissolve | Maps, locations |
| `text_card` | static | fade_in | Titles, stats, dates |
| `graphic` | various | fade_in | Diagrams, comparisons |
| `text_overlay` | static | — | Lower thirds, labels |

### Beat → Segment Mapping

```
BEAT (from Clue Script):
  narration: "The Boxer CRV was developed by Germany and Netherlands."
  start: 8.5, end: 15.0
  primary_visual: {media_type: "video", entities: ["Boxer CRV"], strictness: "exact"}
  fallback_visual: {media_type: "image"}
  last_resort: {type: "text_card"}

SEGMENT (in Timeline):
  If library has matching video:
    → Use video clip, cut to beat duration
  Else if library has matching image:
    → Use image with Ken Burns
  Else:
    → Use text card (from last_resort or narration)
```

---

## 9. Rendering Strategy

### Phase 1: Basic

- Simple video + audio concat
- Text overlay with drawtext filter
- Output: MP4 (H.264 + AAC)

### Phase 2: Multi-track

- Separate tracks: main video, B-roll, maps, text cards, graphics
- FFmpeg filter_complex with overlay chains
- Audio: narration + ambient music + SFX
- Transitions: dissolve, fade, cut between segments

### Phase 3: Advanced

- Color grading per segment (LUTs or filters)
- Animated maps with API (globe rotation, zoom)
- Dynamic text animations (typewriter, fade-in)
- Motion graphics generation
- Multiple camera angles for same topic

### Render Command Structure (Phase 2+)

```bash
ffmpeg \
  -i narration.wav \
  -i music_ambient.mp3 \
  -i segment_001.mp4 \
  -i segment_002.jpg \
  -filter_complex "
    [1:v]scale=1920:1080[bg];
    [2:v]format=yuva420p,fade=t=in:st=0:d=0.5,trim=duration=8.5[clip1];
    [3:v]fade=t=in:st=0:d=0.5,zoompan=z='1+0.001*on':d=255:s=1920x1080,trim=duration=6.5[img1];
    [bg][clip1]overlay[tmp];
    [tmp][img1]overlay
  " \
  -map "[tmp]" \
  -map 0:a \
  -c:v libx264 \
  -c:a aac \
  output.mp4
```

---

## 10. Cost Model

### Per-Video Costs

| Phase | Components | Cost | Notes |
|-------|-----------|------|-------|
| Clue Script | Claude Sonnet | $0.05-0.15 | One-time per video |
| Asset matching | Library search | $0.00 | Free (local JSON) |
| Scraping | yt-dlp + Gemini catalog | $1-5 | Only for NEW content |
| Rendering | FFmpeg | $0.00 | CPU only |

### Library Growth Cost

| Batch | Videos | Library Growth | Scraping Cost | Total |
|-------|--------|----------------|---------------|-------|
| 1-5 | 5 | 0→200 clips | $3-5 each | $15-25 |
| 6-20 | 15 | 200→800 | $2-3 each | $30-45 |
| 21-50 | 30 | 800→2000 | $0.50-1 each | $15-30 |
| 51+ | 50+ | Minimal | $0.10-0.20 each | $5-10 |

**After library reaches 1000+ clips, marginal cost per video drops to $0.10-0.20.**

### Gemini Usage Optimization

| Approach | Cost per 100 clips |
|----------|-------------------|
| Naive (scan everything) | $5-10 |
| Smart (metadata filter → frame check → Flash scan) | $2 |
| Library reuse (5% new clips) | $0.10-0.50 |

---

## 11. Decision Log

Every major decision is documented here with WHY.

### Decision 1: Clue Script uses search keys, not timestamps

**Date:** 2026-08-22

**Problem:** LLMs can't accurately find timestamps in 10-minute videos for 3-second narration beats. 4/5 timestamp guesses are wrong.

**Decision:** Clue Script describes WHAT to show (entities, actions, context). The tool searches the library.

**Impact:** Eliminates timestamp error class. Enables library matching.

### Decision 2: Hard identity gates before ranking

**Date:** 2026-08-22

**Problem:** Soft ranking allows wrong variants to win (Boxer APC scored higher than Boxer CRV because more related words matched).

**Decision:** Entity/action/context are hard gates. Wrong entity = reject, no matter the score.

**Impact:** Zero wrong-variant errors. Slightly more clips needed for rare variants.

### Decision 3: 3-Pack system (Niche + Format + Style)

**Date:** 2026-08-22

**Problem:** Mixing niche, format, and style in one config creates combinatorial explosion.

**Decision:** Separate packs. Niche defines what's valid. Format defines structure. Style defines look.

**Impact:** Easy to add new style (cyberpunk) or new niche (animals) independently.

### Decision 4: JSON-based library (Phase 1)

**Date:** 2026-08-22

**Problem:** SQLite requires setup. JSON is simpler for Phase 1.

**Decision:** JSON for Phase 1. SQLite migration at Phase 2 when library exceeds 5000 entries.

**Impact:** Simpler code, faster iteration. Migration path exists.

### Decision 5: Need-driven library growth

**Date:** 2026-08-22

**Problem:** Scraping 100 random videos to build initial library is expensive and wasteful.

**Decision:** Analyze scripts first. Scrape only for gaps.

**Impact:** 70% cost reduction on initial library build.

### Decision 6: Fail-closed rendering

**Date:** 2026-08-22

**Problem:** Forcing wrong content (video of wrong vehicle, wrong angle) produces unwatchable videos.

**Decision:** If no match, render still image or text card. Never force moving footage.

**Impact:** Some videos have more text cards early on. Quality perception: HIGH. Viewers prefer still + clear text over wrong B-roll.

---

## 12. Common Workflows

### Create Your First Video

```bash
# 1. Write a narration script
# Save to SCRIPTS/my_first_video.txt

# 2. Generate narration audio
# Use ElevenLabs or your TTS tool
# Save to AUDIO/my_first_video.mp3

# 3. Process single video
python CODE/demandscout.py \
  --script SCRIPTS/my_first_video.txt \
  --audio AUDIO/my_first_video.mp3 \
  --niche PACKS/niche/defence.yaml \
  --title "The Boxer CRV"
```

### Batch Process Multiple Videos

```bash
# 1. Put scripts in SCRIPTS/ folder (.txt files)
# 2. Put matching audio files in AUDIO/ folder (.mp3 files, same filename)

# 3. Create queue
python CODE/demandscout.py \
  --queue-from SCRIPTS AUDIO \
  --niche PACKS/niche/defence.yaml

# 4. Process all
python CODE/demandscout.py \
  --queue QUEUE/jobs.json
```

### Add a New Niche

```bash
# 1. Create PACKS/niche/my_niche.yaml
# Use PACKS/niche/defence.yaml as template
# Define entities, actions, strictness rules

# 2. Create a style (optional)
# Use PACKS/style/clean_doc.yaml as template

# 3. Process
python CODE/demandscout.py \
  --script SCRIPTS/my_video.txt \
  --audio AUDIO/my_video.mp3 \
  --niche PACKS/niche/my_niche.yaml
```

### Check Library Health

```bash
python CODE/demandscout.py --library
```

### Review Queue

```bash
python CODE/demandscout.py --status
```

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for all decisions, changes, and reasoning.

## Todo

See [TODO.md](TODO.md) for current task tracking.
