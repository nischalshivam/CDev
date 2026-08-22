# CDev — Complete System Overview

> **Purpose:** This document is the single source of truth for the CDev system. Any Claude (or developer) reading this should understand what the system does, how it works, why it works this way, and how every piece fits together.

---

## Table of Contents

1. [What Problem Does This Solve?](#1-what-problem-does-this-solve)
2. [What Is the Big Idea?](#2-what-is-the-big-idea)
3. [System Architecture](#3-system-architecture)
4. [Pipeline — Step by Step](#4-pipeline--step-by-step)
5. [Every File Explained](#5-every-file-explained)
6. [The 3-Pack System](#6-the-3-pack-system)
7. [How Assets Work](#7-how-assets-work)
8. [Hard Identity Gates](#8-hard-identity-gates)
9. [Cost Model](#9-cost-model)
10. [Phase Roadmap](#10-phase-roadmap)
11. [How to Extend This System](#11-how-to-extend-this-system)

---

## 1. What Problem Does This Solve?

**Short answer:** Making documentary-style YouTube videos (narration + visuals) is slow and expensive. This system automates 80-90% of it.

**Long answer:** Think of channels like "The Armoured Patrol", "Defence Simplified", "WarBirds", etc. They make videos like "The Boxer CRV — Australia's Armored Future". Each video needs:
- A narration script (written)
- A voiceover (recorded or TTS)
- Visuals (video clips + images)
- Text overlays (titles, stats, names)
- Music/sound effects
- Final assembly in video editor

Doing this manually takes 4-8 hours per video. This system brings it down to 30-60 minutes.

**The real bottleneck isn't writing scripts — it's finding the right visuals for every sentence.**

---

## 2. What Is the Big Idea?

The system works on **6 core principles**:

### Principle 1: Script First, Not B-Roll First
Most automation tools start with "find some footage, then write a script around it." This produces generic, soulless content. CDev does the opposite:
1. You write the narration script (or Claude writes it for you)
2. THEN the system finds the perfect visuals for each sentence

### Principle 2: Search Keys, Not Timestamps
Traditional AI video tools ask: "What's at timestamp 3:24 in this 10-minute video?" The AI guesses wrong 4 out of 5 times.

CDev's "Clue Script" describes **WHAT to show** (entities, actions, mood). The tool searches the library/internet for matching content. No timestamps. No guessing.

### Principle 3: Cumulative Library
Every video the system produces adds clips/images to a library database. The more videos you make, the less you need to scrape new content:
- Video 1: 100% new scraping, cost ~$5
- Video 20: 80% reuse from library, cost ~$2
- Video 50: 95% reuse, cost ~$0.50

### Principle 4: Fail-Closed
If the system can't find a verified match for a narration sentence, it shows a **text card or still image** — never forced wrong footage. Better to show nothing than show the wrong tank.

### Principle 5: 3-Pack Consistency
Every video is controlled by 3 config files:
- **Niche Pack** — What entities/actions are valid (e.g., defence, cars, animals)
- **Style Pack** — How it looks (colors, fonts, motion, transitions)
- **Format Pack** — Video structure (intro, body, outro pattern)

This ensures 50 videos look like they come from the same editor.

### Principle 6: Need-Driven Scraping
Don't scrape 100 random videos. Analyze 50 scripts, extract keywords, check library for gaps, scrape **only what's missing**. This is how cost stays low.

---

## 3. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        ProClip Engine                            │
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐  │
│  │   INPUT      │    │   AI BRAIN   │    │   PYTHON ENGINE     │  │
│  │             │    │             │    │                     │  │
│  │  Scripts     │───▶│  Claude     │───▶│  Scraper            │  │
│  │  (.txt)      │    │  (Clue      │    │  (yt-dlp + APIs)    │  │
│  │             │    │   Script)   │    │                     │  │
│  ├─────────────┤    ├─────────────┤    ├─────────────────────┤  │
│  │  Audio       │    │             │    │  Cataloger          │  │
│  │  (.mp3 or    │    │             │    │  (Gemini Flash)     │  │
│  │   TTS)       │    │             │    │                     │  │
│  ├─────────────┤    ├─────────────┤    ├─────────────────────┤  │
│  │  Niche Pack  │    │             │    │  Renderer           │  │
│  │  (.yaml)     │    │             │    │  (FFmpeg)            │  │
│  ├─────────────┤    ├─────────────┤    ├─────────────────────┤  │
│  │  Style Pack  │    │             │    │  Library DB         │  │
│  │  (.yaml)     │    │             │    │  (JSON database)    │  │
│  └─────────────┘    └─────────────┘    └─────────────────────┘  │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    DATA STORAGE                            │  │
│  │  Library DB  │  Queue  │  Clue Scripts  │  Timelines      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                       OUTPUT                               │  │
│  │                    Final MP4 Video                         │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User writes script (or Claude generates it)
         │
         ▼
┌─────────────────────────────────────┐
│  STEP 1: Clue Script Generation     │
│  Claude reads script, breaks it into │
│  "beats" (narration segments with   │
│  visual requirements)               │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  STEP 2: Asset Retrieval            │
│  For each beat:                     │
│  1. Search library DB               │
│  2. If not found → scrape (Pexels,  │
│     Wikimedia, YouTube)             │
│  3. Catalog with AI (Gemini)        │
│  4. Add to library for next time    │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  STEP 3: Timeline Building          │
│  Match each beat to:                │
│  - Video clip (with motion effect)  │
│  - Image (with Ken Burns)           │
│  - Text card (fallback)             │
│  Add transitions, text overlays     │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  STEP 4: Rendering                  │
│  FFmpeg assembles:                  │
│  - Video clips (cropped/motion)     │
│  - Images (Ken Burns zoom/pan)      │
│  - Text overlays (title cards)      │
│  - Narration audio                  │
│  - Music                            │
│  → Final MP4                        │
└─────────────────────────────────────┘
```

---

## 4. Pipeline — Step by Step

### Input Required
```
1. Narration Script (.txt)   — REQUIRED
2. Audio File (.mp3)         — AUTO (TTS if missing)
3. Niche Pack (.yaml)        — REQUIRED (defence.yaml provided)
4. Style Pack (.yaml)        — Optional (clean_doc is default)
5. Video Title               — Optional (derived from script filename)
```

### Processing Pipeline

```
┌────────────────────────────────────────────────────────────────────┐
│  MAIN PIPELINE (demandscout_core.py → process_job)                │
├────┬───────────────────────────────────────────────────────────────┤
│ #  │ Step                                                        │
├────┼───────────────────────────────────────────────────────────────┤
│ 1  │ LOAD INPUTS                                                 │
│    │   - Read script text                                        │
│    │   - Load niche config (YAML)                                │
│    │   - Load style config (YAML)                                │
├────┼───────────────────────────────────────────────────────────────┤
│ 2  │ AUDIO CHECK                                                  │
│    │   - If audio exists → use it                                 │
│    │   - If not → generate TTS (edge-tts)                         │
│    │   - Cost: $0 (edge-tts is free)                              │
├────┼───────────────────────────────────────────────────────────────┤
│ 3  │ CLUE SCRIPT GENERATION                                       │
│    │   - Call Claude API with CLUE_SCRIPT_PROMPT.md               │
│    │   - Claude breaks script into timed "beats"                  │
│    │   - Each beat has: text, entities, visual needs, mood        │
│    │   - Cost: ~$0.10-0.30 per script (Claude Sonnet)             │
├────┼───────────────────────────────────────────────────────────────┤
│ 4  │ ASSET RETRIEVAL (per beat)                                   │
│    │   For each beat in Clue Script:                              │
│    │   a) Search Library DB (local JSON)                          │
│    │   b) If found → use it (free, instant)                       │
│    │   c) If not found → scrape (Pexels API, Wikimedia, etc.)     │
│    │   d) Catalog new assets with Gemini Flash                     │
│    │   e) Add to Library DB for future use                        │
│    │   Cost: $0 for library hits, ~$0.50 for new scraping         │
├────┼───────────────────────────────────────────────────────────────┤
│ 5  │ TIMELINE BUILDING                                            │
│    │   - Each beat → timeline segment                             │
│    │   - Assign: video clip OR image OR text card                 │
│    │   - Assign: motion effect (Ken Burns, push-in, static)       │
│    │   - Assign: transition (cut, dissolve, fade)                 │
│    │   - Add text overlays (entity names, stats)                  │
│    │   - Calculate timing from audio duration                     │
│    │   Cost: $0                                                     │
├────┼───────────────────────────────────────────────────────────────┤
│ 6  │ RENDERING                                                    │
│    │   - FFmpeg assembles final MP4                               │
│    │   - Composite video + images + text + audio                  │
│    │   - Apply style pack effects (color grade, etc.)             │
│    │   - Output: output/{JOB_ID}_{script_name}.mp4                │
│    │   Cost: $0 (FFmpeg is free, runs locally)                    │
└────┴───────────────────────────────────────────────────────────────┘
```

### Output Files (per job)

```
output/
  JOB_001_boxer_crv.mp4          ← Final video
  JOB_001_boxer_crv_timeline.json ← Timeline for review

clues/
  JOB_001_clue.json              ← Clue Script (beats + visual needs)

audio/
  boxer_crv.mp3                   ← Narration audio (TTS or provided)

logs/
  JOB_001.log                     ← Processing log
```

---

## 5. Every File Explained

### CODE/ (Python Modules)

#### `demandscout.py` — Main Entry Point
**What it does:** CLI interface, data models, queue management
**Key classes:**
- `Job` — Represents one video job (script, audio, niche, status)
- `Beat` — A single narration segment with visual requirements
- `LibraryDB` — JSON-based media library with search
- `QueueManager` — Batch job management (add, process, resume)

**CLI Commands:**
```bash
python CODE/demandscout.py --script scripts/X.txt --audio audio/X.mp3 --niche PACKS/defence.yaml
python CODE/demandscout.py --queue-from scripts/ audio/ --niche PACKS/defence.yaml
python CODE/demandscout.py --queue QUEUE/jobs.json
python CODE/demandscout.py --status
python CODE/demandscout.py --library
```

#### `demandscout_core.py` — Pipeline Orchestrator
**What it does:** The main processing pipeline that ties everything together
**Key function:** `process_job(job)` — runs all 6 steps

Flow:
1. Load inputs (script, niche config)
2. Check/generate audio (TTS if missing)
3. Generate Clue Script (Claude API)
4. Search library + scrape missing assets
5. Build timeline
6. Render video

#### `scraper.py` — Asset Scraper
**What it does:** Downloads/clones visual assets from the internet
**Sources:**
- Pexels API (free stock photos/videos) — PRIMARY
- Wikimedia Commons (free images) — SECONDARY
- YouTube thumbnails (free high-res images) — TERTIARY

**Key classes:**
- `ScraperEngine` — Main scraper coordinator
- `PexelsHarvester` — Pexels API integration
- `WikimediaHarvester` — Wikimedia Commons API
- `YouTubeHarvester` — YouTube thumbnail extraction

**Output:** Downloads to `DOWNLOADS/` (gitignored), adds entries to Library DB

#### `tts.py` — Text-to-Speech
**What it does:** Generates narration audio from script text
**Engine:** Microsoft Edge TTS (`edge-tts`) — FREE, high quality

**Key class:** `TTSEngine`
- `generate_from_script(text)` — Generate full narration audio
- `generate_from_beats(beats)` — Generate per-beat audio for precise timing
- `list_available_voices()` — Show all available voices

**Default voice:** `en-US-GuyNeural` (deep male, documentary quality)
**Cost:** $0

#### `renderer.py` — Video Renderer
**What it does:** Assembles final MP4 using FFmpeg
**Key classes:**
- `RendererEngine` — Main renderer
- `RenderJob` — Render configuration
- `TimelineItem` — Individual item in timeline

**Capabilities:**
- Video clips with Ken Burns (zoom/pan on stills)
- Text cards with typography
- Motion effects (push-in, pan, static)
- Transitions (cut, dissolve, fade)
- Audio mixing (narration + music)

**Output:** `output/{JOB_ID}_{name}.mp4`

### PACKS/ (Configuration)

#### `defence.yaml` — Defence Niche Pack
Defines what's valid for defence/military content:
- Entities: vehicles, aircraft, weapons, organizations
- Actions: military exercise, live fire, etc.
- Trusted channels for scraping
- Entity strictness rules (exact match required)

#### `style_clean_doc.yaml` — Clean Documentary Style
- Typography: Inter font
- Colors: Dark text on light background
- Motion: Subtle push-in
- Transitions: Cut or dissolve

#### `style_cinematic.yaml` — Cinematic Style
- Typography: Bebas Neue (bold, impactful)
- Colors: Desaturated, dramatic
- Motion: Slow push-in
- Transitions: Fade

### QUEUE/ (Batch Processing)

#### `jobs.json` — Active Job Queue
Contains all jobs waiting to be processed. Each job has:
- `id` — Unique identifier
- `script` — Path to narration script
- `audio` — Path to audio file
- `niche` — Niche pack path
- `status` — queued/running/done/error
- `progress` — 0-100 percentage
- `output` — Output path (when done)

### SCRIPTS/ (Narration Scripts)

Contains `.txt` files with narration scripts. Each script should be:
- Plain text
- 100-500 words (for 60s-180s videos)
- Written in full sentences
- No markdown formatting

### PROMPTS/ (AI Prompts)

#### `CLUE_SCRIPT_PROMPT.md`
The prompt sent to Claude API to generate Clue Scripts. Defines:
- Beat structure (narration, entities, visual needs, mood)
- Output format (JSON)
- Rules for visual role assignment

---

## 6. The 3-Pack System

### Why 3 Packs?

If you change niche (defence → cars), you change what entities are valid.
If you change style (clean → cinematic), you change how it looks.
If you change format (short → long), you change video structure.

Separating these lets you mix and match without rewriting rules.

### Niche Pack (WHAT is valid)

```yaml
# PACKS/niche/defence.yaml
name: defence
display_name: "Defence & Military"
entities:
  vehicles:
    - name: "Boxer CRV"
      type: "armored_vehicle"
      manufacturer: "Rheinmetall"
      variants: ["CRV", "Command", "Ambulance", "Jeep"]
    - name: "ASLAV"
      type: "armored_vehicle"
      manufacturer: "General Dynamics"
  aircraft:
    - name: "AH-64 Apache"
      type: "attack_helicopter"
    - name: "MH-60R Seahawk"
      type: "naval_helicopter"
actions:
  - military_exercise
  - live_fire
  - amphibious_assault
  - parachute_jump
strictness_rules:
  vehicles: "exact make + model + variant"
  events: "exact event + year"
  locations: "country + region"
trusted_channels:
  - "Defence Australia"
  - "US Army"
  - "British Army"
  - "NATO"
```

### Style Pack (HOW it looks)

```yaml
# PACKS/style/cinematic.yaml
name: cinematic
display_name: "Cinematic"
typography:
  font: "Bebas Neue"
  size_title: 72
  size_subtitle: 36
  color: "#FFFFFF"
  shadow: true
color_grade:
  type: "desaturated"
  contrast: 1.1
  saturation: 0.85
motion:
  default: "slow_push_in"
  speed: 1.2
transitions:
  default: "fade"
  duration: 0.5
audio:
  narration_eq: "warm"
  music_ducking: -20
```

---

## 7. How Assets Work

### Asset Types

| Type | Extension | Use | Source |
|------|-----------|-----|--------|
| video_clip | .mp4 | Main footage | Pexels, YouTube scrape |
| image | .jpg/png | Maps, diagrams, portraits | Wikimedia, Pexels |
| text_card | N/A | Titles, stats, names | Generated by renderer |
| lower_third | N/A | Name labels | Generated by renderer |
| audio_music | .mp3 | Background music | Royalty-free libraries |

### Library DB Structure

```json
{
  "version": "2.0",
  "total_entries": 147,
  "entities_index": {
    "Boxer CRV": ["CLP_a1b2c3", "CLP_d4e5f6"],
    "AH-64 Apache": ["CLP_g7h8i9"]
  },
  "actions_index": {
    "military_exercise": ["CLP_j0k1l2"],
    "driving": ["CLP_m3n4o5"]
  },
  "entries": {
    "CLP_a1b2c3": {
      "id": "CLP_a1b2c3",
      "type": "video_clip",
      "file": "DOWNLOADS/pexels_12345.mp4",
      "source_type": "pexels",
      "topic": "Boxer armored vehicle driving",
      "entities": ["Boxer CRV", "Australian Army"],
      "actions": ["driving", "military exercise"],
      "environment": ["forest", "daylight"],
      "quality": "high",
      "duration": 8.5,
      "description": "Boxer CRV armored vehicle driving through forest..."
    }
  }
}
```

### Asset Lifecycle

```
1. SCRIPT NEEDS ASSET
   Beat says: "The Boxer CRV drives through rugged terrain"
   Needs: video of Boxer CRV driving

2. LIBRARY SEARCH
   Search: "Boxer CRV driving"
   Result: CLP_a1b2c3 (score: 8.5) ✓

3. IF FOUND → USE IT
   Add to timeline with motion effect

4. IF NOT FOUND → SCRAPE
   a) Build search query: "Boxer CRV driving"
   b) Search Pexels API
   c) Download best match
   d) Cut into clips (FFmpeg)
   e) Catalog with Gemini Flash
   f) Add to Library DB

5. NEXT TIME → REUSE
   When another script needs "Boxer CRV",
   find CLP_a1b2c3 in library (free, instant)
```

---

## 8. Hard Identity Gates

This is the most important quality control mechanism.

### What Is a Gate?

A gate is a rule that **rejects** content if it doesn't match exactly. No exceptions.

### Example: Vehicle Identity Gate

```
Script says: "Boxer CRV"
Library clip says: "Boxer armored vehicle" (generic, no variant)

GATE CHECK:
  ✓ Has "Boxer"? YES
  ✓ Has "CRV" variant? NO (clip is generic)
  ✗ REJECTED

Result: Text card or generic Boxer image instead.
```

### Example: Event Identity Gate

```
Script says: "Exercise Talisman Sabre 2023"
Library clip says: "Australian military exercise 2023"

GATE CHECK:
  ✓ Has "military exercise"? YES
  ✓ Has "Talisman Sabre"? NO
  ✓ Has "2023"? YES
  ✗ REJECTED

Result: Text card or generic exercise image.
```

### Why Hard Gates?

Without gates, you get "close enough" clips that show the wrong thing. A viewer who knows about military vehicles will immediately notice if you show a generic Boxer when talking about the CRV variant. That destroys credibility.

### Gate Implementation

```python
def hard_identity_gate(clip: ClipEntry, beat: Beat) -> bool:
    """
    Return True if clip passes ALL identity gates.
    False = reject this clip, use text card instead.
    """
    # Vehicle gate: must match exact make + model + variant
    if "vehicles" in beat.entities:
        for vehicle in beat.entities["vehicles"]:
            required_variant = vehicle.get("variant")
            if required_variant:
                clip_variants = [e.lower() for e in clip.entities]
                if required_variant.lower() not in clip_variants:
                    return False  # Wrong variant!

    # Event gate: must match exact event + year
    if "events" in beat.entities:
        for event in beat.entities["events"]:
            required_year = event.get("year")
            if required_year and required_year not in clip.description:
                return False  # Wrong year!

    return True
```

---

## 9. Cost Model

### Per-Video Cost Breakdown

| Component | Cost | Notes |
|-----------|------|-------|
| Claude API (Clue Script) | $0.10-0.30 | Sonnet, ~2K tokens |
| Gemini Flash (cataloging) | $0.00-0.50 | Only for NEW clips |
| Pexels API | $0 | Free tier |
| Wikimedia Commons | $0 | Free |
| TTS (edge-tts) | $0 | Free |
| FFmpeg rendering | $0 | Runs locally |
| Multilingual support | $0 | Same cost as English |

### Cost by Phase

```
PHASE 1 (First 10 videos):
  - Library: Empty
  - Scrape: 100% new content
  - Cost: ~$3-5 per video
  - Total: ~$30-50

PHASE 2 (Videos 11-30):
  - Library: Growing (500+ clips)
  - Reuse: 60-80%
  - Scrape: 20-40% new
  - Cost: ~$1-2 per video
  - Total: ~$20-40

PHASE 3 (Videos 31-100):
  - Library: Mature (2000+ clips)
  - Reuse: 85-95%
  - Scrape: 5-15% new
  - Cost: ~$0.30-0.80 per video
  - Total: ~$20-50

PHASE 4 (Videos 100+):
  - Library: Massive (5000+ clips)
  - Reuse: 95%+
  - Scrape: Rare
  - Cost: ~$0.10-0.30 per video
  - Total: ~$10-30 per 100 videos
```

### Token Budget Optimization

The system is designed to minimize AI API calls:

| AI Call | When | Frequency |
|---------|-------|-----------|
| Claude (Clue Script) | Per video | Once |
| Claude (Script generation) | Per script (optional) | Once if generating scripts |
| Gemini (Cataloging) | Per NEW clip | Only when library gap |
| Gemini (Verification) | Per clip (optional) | During quality checks |

**Key insight:** Library hits = $0. Only new content costs money.

---

## 10. Phase Roadmap

### Phase 1: Foundation (Current) ✅
- [x] Project structure
- [x] Data models (Job, Beat, ClipEntry)
- [x] Library DB (JSON-based search)
- [x] Queue management
- [x] Scraper (Pexels, Wikimedia, YouTube)
- [x] TTS generation (edge-tts)
- [x] FFmpeg renderer
- [x] Basic text card rendering
- [x] GitHub repo + CI

### Phase 2: Asset Pipeline (Next)
- [ ] Clue Script integration with Claude API
- [ ] Hard identity gates implementation
- [ ] Smart timeline builder
- [ ] Image support in renderer (Ken Burns)
- [ ] Lower third generation
- [ ] Text overlay system
- [ ] Music/sound effect integration
- [ ] Scene change detection (FFmpeg)
- [ ] Clip cutting automation

### Phase 3: Polish & Automation
- [ ] Automated script generation (Claude writes scripts)
- [ ] Thumbnail generation (AI + text)
- [ ] Description generation
- [ ] Tags/title generation
- [ ] YouTube upload automation
- [ ] Quality scoring system
- [ ] A/B testing for thumbnails
- [ ] Analytics integration

### Phase 4: Production Scale
- [ ] 50+ video library test
- [ ] Cost optimization (caching, batching)
- [ ] Multi-format support (Shorts, Long-form)
- [ ] Multi-language support
- [ ] Distributed processing
- [ ] Web dashboard for monitoring

---

## 11. How to Extend This System

### Adding a New Niche

1. Create `PACKS/niche/my_niche.yaml`:
```yaml
name: cars
display_name: "Supercars"
entities:
  brands: ["Ferrari", "Lamborghini", "Porsche"]
  models: ["SF90", "Aventador", "911 GT3"]
actions:
  - test drive
  - top speed run
  - track lap
strictness_rules:
  vehicles: "exact make + exact model"
```

2. Add style: `PACKS/style/my_style.yaml` (or reuse existing)

3. Create scripts in `scripts/`

4. Run:
```bash
python CODE/demandscout.py \
  --script scripts/ferrari_sf90.txt \
  --niche PACKS/niche/cars.yaml \
  --style PACKS/style/cinematic.yaml
```

### Adding a New Scraper Source

1. Create harvester class in `scraper.py`:
```python
class MyNewHarvester:
    def search(self, query, count=10):
        # Your API integration here
        pass
```

2. Add to `ScraperEngine`:
```python
def _search_my_new_source(self, query, count):
    harvester = MyNewHarvester()
    return harvester.search(query, count)
```

### Adding a New Render Effect

1. Add FFmpeg filter in `renderer.py`:
```python
def _apply_my_effect(self, input_path, output_path):
    cmd = [
        "ffmpeg", "-i", input_path,
        "-vf", "my_custom_filter",
        output_path
    ]
```

2. Wire into timeline processing

### Changing the AI Model

In `demandscout_core.py`:
```python
# Change from Sonnet to Haiku (cheaper, faster)
message = client.messages.create(
    model="claude-haiku-5",  # Change here
    ...
)

# Or use Opus (smarter, more expensive)
message = client.messages.create(
    model="claude-opus-5",  # Change here
    ...
)
```

---

## 10. Multilingual System (12 Languages)

### Core Principle: Visual Content Is Language-Neutral

The system supports 12 languages, but with a critical design rule:

```
┌─────────────────────────────────────────────────────────────────┐
│                    LANGUAGE ARCHITECTURE                         │
├──────────────────────┬──────────────────────────────────────────┤
│   FRONTEND (varies)  │   BACKEND (always English)               │
├──────────────────────┼──────────────────────────────────────────┤
│  Script              │  Library metadata (English)              │
│  Audio/TTS           │  Scraping queries (English)              │
│  Text overlays       │  Cataloging (English)                    │
│  Clue Script narration│ Entity names (universal)                 │
└──────────────────────┴──────────────────────────────────────────┘
```

### Why This Design?

**The Problem:**
```
French script → Scrape "Boxer CRV en français"
             → YouTube returns 0 results
             → Wikimedia returns 0 results
             → Library stays empty
             → German script also fails
             → SYSTEM BROKEN
```

**The Solution:**
```
French script → Extract entities: ["Boxer CRV", "Australian Army"]
             → Search library with ENGLISH query: "Boxer CRV driving"
             → Found! (English metadata, same visual asset) ✓
             → If miss → Scrape with ENGLISH: "Boxer CRV military footage"
             → Asset cataloged in ENGLISH
             → Render: French audio + French text + same asset
```

### The Universal Bridge: Entity Names

Entity names NEVER change across languages:
- "Boxer CRV" in French script = "Boxer CRV" in English library
- "F-35" in Spanish script = "F-35" in English library
- "AH-64 Apache" in German script = "AH-64 Apache" in English library

This is why ONE library serves ALL languages.

### Supported Languages

| Code | Language | TTS Voice | Font | RTL |
|------|----------|-----------|------|-----|
| en | English | Guy Neural | Inter | No |
| fr | French | Henri Neural | Inter | No |
| de | German | Conrad Neural | Inter | No |
| es | Spanish | Alvaro Neural | Inter | No |
| hi | Hindi | Swara Neural | Noto Sans Devanagari | No |
| ar | Arabic | Zayed Neural | Noto Sans Arabic | Yes |
| ja | Japanese | Keita Neural | Noto Sans JP | No |
| ko | Korean | InJoon Neural | Noto Sans KR | No |
| pt | Portuguese | Fabio Neural | Inter | No |
| ru | Russian | Dmitry Neural | Noto Sans | No |
| it | Italian | Diego Neural | Inter | No |
| zh | Chinese | Yunxi Neural | Noto Sans SC | No |

### Usage

```bash
# Explicit language
python CODE/demandscout.py \
  --script scripts/boxer_crv_fr.txt \
  --lang fr \
  --niche PACKS/defence.yaml

# Auto-detect from script content
python CODE/demandscout.py \
  --script scripts/mi_video.txt \
  --lang auto \
  --niche PACKS/defence.yaml
```

### Cost Impact

Multilingual mode adds **$0** to cost:
- Same library (English, already built)
- Same scraping (English queries)
- Same Claude API call (Clue Script generation)
- Only difference: TTS voice changes per language

---

## Quick Reference

### Directory Structure
```
CDev/
├── CODE/                   # Python code
├── PACKS/                  # Configuration packs
├── QUEUE/                  # Job queue
├── SCRIPTS/                # Narration scripts
├── PROMPTS/                # AI prompts
├── DOWNLOADS/              # Downloaded assets (gitignored)
├── audio/                  # Generated audio
├── output/                 # Final videos
├── logs/                   # Logs
├── demandscout.py          # Main CLI
├── README.md               # This repo's README
└── PROCESS.md              # Detailed process docs
```

### Key Commands
```bash
# Single video
python CODE/demandscout.py --script scripts/X.txt --audio audio/X.mp3 --niche PACKS/defence.yaml

# Create queue from folder
python CODE/demandscout.py --queue-from scripts/ audio/ --niche PACKS/defence.yaml

# Process queue
python CODE/demandscout.py --queue QUEUE/jobs.json

# Check status
python CODE/demandscout.py --status

# Library stats
python CODE/demandscout.py --library
```

### Cost Per Video (Mature System)
- Claude API: $0.10
- Gemini (if needed): $0
- Scraping (if needed): $0
- TTS: $0
- Rendering: $0
- **Total: ~$0.10 per video**

---

*Last updated: 2026-08-22*
*System: ProClip Engine v0.1*
