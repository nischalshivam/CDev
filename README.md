# CDev — ProClip Engine

**Documentary video automation system. Script → Clue Script → Library → Timeline → Render.**

Built for creators who publish 10-50+ narration-driven videos per month and want 80-90% automation without sacrificing quality.

---

## What It Does

```
Script + Audio
     ↓
[Clue Script] ← Claude writes search keys, not timestamps
     ↓
[Asset Retrieval] ← Library search + smart scraping
     ↓
[Timeline] ← Beats → segments → media → transitions
     ↓
[Render] ← FFmpeg proxy → QC → final
     ↓
Output MP4
```

## Why This Exists

Traditional video automation (thumbnail + voiceover + free B-roll) produces thousands of channels that all look the same. CDev's approach is different:

1. **Script-first, not B-roll-first** — Write narration first, find media after. B-roll-first produces bad results because media availability drives script choices.
2. **Clue Script = search keys, not timestamps** — Describes WHAT to show. The tool searches the library/internet. LLMs guess timestamps wrong 4/5 times. This eliminates that failure mode.
3. **3-Pack system** — Every video has Niche Pack (what's valid), Format Pack (what to show), Style Pack (how it looks). Consistent quality across thousands of videos.
4. **Cumulative library** — Every video adds to the library. Cost drops over time. Phase 1: $2-5/video. Phase 3: $0.10-0.20/video.
5. **Hard identity gates** — Wrong variant of an entity? Rejected. No clever ranking around bad data.
6. **Fail-closed** — Unverified clip renders as still or text card. Never forces wrong moving footage.

## Project Structure

```
CDev/
├── CODE/                      # Python modules
│   ├── demandscout.py         # Main CLI + data models
│   ├── demandscout_core.py    # Core processing pipeline
│   ├── source_hunter.py       # Scraping (Phase 2)
│   ├── smart_cataloger.py     # AI cataloging (Phase 2)
│   └── renderer.py            # FFmpeg rendering (Phase 2)
├── SCRIPTS/                   # Narration scripts (.txt)
├── CLUES/                     # Clue Scripts (JSON, per video)
├── QUEUE/                     # Batch job queues (JSON)
├── PACKS/                     # Pack files
│   ├── niche/                 # Niche packs (YAML)
│   ├── format/                # Format packs (YAML)
│   └── style/                 # Style packs (YAML)
├── PROMPTS/                   # Claude prompts
│   └── CLUE_SCRIPT_PROMPT.md  # Universal Clue Script prompt
├── audio/                     # Narration audio + music
├── clips/                     # Extracted video clips
├── raw/                       # Raw downloaded videos
├── library/                   # Global media vault
├── timelines/                 # Timeline JSONs
├── output/                    # Final videos
├── logs/                      # Processing logs
├── state/                     # Runtime state
├── PROCESS.md                 # System documentation (the manual)
├── CHANGELOG.md               # All decisions and changes
├── TODO.md                    # Task tracking
└── README.md                  # This file
```

## Usage

### Single Video

```bash
python CODE/demandscout.py \
  --script SCRIPTS/my_video.txt \
  --audio audio/my_video.mp3 \
  --niche PACKS/niche/defence.yaml \
  --title "My Video Title"
```

### Batch (Queue Mode)

```bash
# Create queue from folders
python CODE/demandscout.py \
  --queue-from SCRIPTS audio \
  --niche PACKS/niche/defence.yaml

# Process all jobs
python CODE/demandscout.py --queue QUEUE/jobs.json

# Resume (skip done jobs)
python CODE/demandscout.py --queue QUEUE/jobs.json
```

### Overnight Mode

```bash
python CODE/demandscout.py --overnight
```

### Check Status

```bash
python CODE/demandscout.py --status
python CODE/demandscout.py --library
```

## Requirements

```bash
pip install anthropic google-generativeai yt-dlp pyyaml
```

System requirements:
- FFmpeg (for video processing)
- FFprobe (for metadata)
- Python 3.10+

## Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 1: Foundation | **In Progress** | Skeleton, queue, basic render |
| 2: Asset Pipeline | Next | Clue Script integration, hard gates, timeline |
| 3: Polish | Planned | Maps, graphics, feedback loop, QC |
| 4: Production | Planned | First real video, library growth testing |

## Niche Packs

- **defence** — Military vehicles, aircraft, exercises (included)
- Add yours by creating a YAML file in `PACKS/niche/`

## Related Projects

- [ProStudio (Lib)](https://github.com/nischalshivam/ProStudio) — Movie/TV essay system. Separate repo. Untouched.
- [demandscout](https://github.com/nischalshivam/CDev) — Standalone tool (Phase 3+)

## Documentation

- `SYSTEM_OVERVIEW.md` — **Read this first.** Complete system explained for any developer/AI.
- `PROCESS.md` — Detailed system manual (philosophy, architecture, decisions)
- `PROMPTS/CLUE_SCRIPT_PROMPT.md` — Universal Clue Script prompt (copy-paste ready)
- `CHANGELOG.md` — Every decision, why, and when
- `TODO.md` — Task tracking

## License

Proprietary. Not for redistribution.
