# NEW CHANNEL / NEW NICHE — start-here kit

> **How to use:** open a fresh chat for the channel and paste the PASTE BLOCK below (edit the 5
> values). That is all Claude needs — everything else lives on disk, not in chat memory.

---

## THE PASTE BLOCK (copy, edit 5 values, paste as your first message)

```
Read C:/Users/Dell/Downloads/CDev/FOUNDATION.md and C:/Users/Dell/Downloads/CDev/NEW_CHANNEL_KIT.md first.

PROJECT
  repo          : C:/Users/Dell/Downloads/CDev   (branch: foundation, github.com/nischalshivam/CDev)
  library root  : <SSD path, e.g. E:/CDevData/library>       # ONE shared library for ALL channels
  channel_id    : <e.g. cycles-uk>
  niche         : <e.g. cycles>
  competitors   : <2-3 YouTube channel or video URLs to reverse-engineer the editing style>

I provide : the script (and voiceover, unless we use TTS)
You do    : style pack -> footage acquisition -> library -> clip selection -> render
I keep    : idea, title, thumbnail, metadata (manual, for originality)

Start by confirming the library state and telling me what you need.
```

---

## What Claude does on a new channel (the order)

1. **Read the system** — `FOUNDATION.md` (design), this file (workflow).
2. **Check the library** — `python CODE/catalog_db.py` prints the DB path + stats. The library is
   SHARED across every channel; a new niche just adds new collections to it.
3. **Style pack (once per channel)** — download 2-3 competitor videos and **measure** them, don't
   eyeball: median shot length, cuts/min, clip-vs-stills ratio, text style/position/font, transition
   types, colour grade, grain/texture, SFX, music. Write the result to
   `PACKS/style/<niche>.yaml`. Every render for that channel reads this file.
4. **Format pack (per video type)** — pick one: `HISTORY_ARCHIVAL`, `COMPARISON_EVIDENCE`,
   `PROCUREMENT_TIMELINE`, `PRODUCT_LISTICLE` (see `CODE/format_packs.py`). Niche = WHAT,
   Format = HOW the story is told, Style = LOOK. Three separate dimensions.
5. **Project manifest (per video)** — `projects/<channel>/<video>/project.json` via
   `CODE/project.py`. This, not the chat, is the state.
6. **Per video** — narration lock -> clue script -> coverage check against the shared library ->
   demand tickets for gaps only -> acquire (YouTube/Reddit/IG/stock) -> cheap local gates ->
   Gemini catalog -> retrieval -> render.

---

## Where everything lives (nothing lives in chat)

| Thing | Location |
|---|---|
| Code + docs | `C:/Users/Dell/Downloads/CDev` (branch `foundation`) |
| **Shared library DB** | `<LIBRARY_ROOT>/catalog.sqlite` — ONE file, all channels |
| **Media objects** | `<LIBRARY_ROOT>/objects/<hh>/<sha256>.<ext>` — each file stored ONCE |
| Style pack (per channel) | `PACKS/style/<niche>.yaml` |
| Niche/topic pack | `PACKS/niche/<niche>.json` (auto via `CODE/entity_brain.py`) |
| Project + runs | `projects/<channel>/<video>/` |
| Secrets | `keys.env` (gitignored — never committed) |

`LIBRARY_ROOT` is set by the `CDEV_LIBRARY_ROOT` env var or `config/library.toml`. The DB stores
**relative** paths, so when the external SSD's drive letter changes you edit ONE value, not the DB.

---

## How the library grows and is reused (the money part)

- **One shared library, scoped by collections** — a channel retrieves only from
  `[its PROJECT] + [its ENTITY tags] + [its DOMAIN] + COMMON`. Cycles footage can never leak into a
  boxing video, but COMMON (city, crowd, money, factory) and stock are shared by all 50 channels.
- **Every clip is cataloged once.** Same clip reused by 20 videos = Gemini charged once.
- **Coverage check runs before any acquisition** — only genuine gaps become demand tickets, and
  duplicate tickets merge across a batch of scripts.
- **Cooldown** stops the same clip appearing in consecutive videos.

Result: video 1 of a niche is the expensive one; by video 10-20 most beats are library hits.

---

## What you provide vs what the tool does

| You (human — keeps the channel original) | The tool |
|---|---|
| idea / angle | style pack (measured from competitors) |
| script | footage acquisition + library |
| voiceover **or** just the script (if TTS is wired) | clip selection, alignment, render |
| thumbnail | timeline, transitions, text, grade |
| title, description, tags | QC + reuse tracking |

---

## Scale rules (50-100 channels, 3 min to 3 hours)

- **One chat per channel while working on it.** Chats are disposable; manifests + library are not.
- **Long videos** (1-3 h) are rendered in chunks and concatenated — never one giant filtergraph.
- **Batch mode**: drop N scripts in a channel folder, run once; coverage merges the gaps so shared
  shots are acquired a single time.
- **Never** create a second library per niche. Collections do the separation.

---

## Non-negotiables (learned the hard way, each one cost a rebuild)

1. Measure, don't guess — site metadata lies (a "1920x1440" download arrived as 960x720).
2. Cheap local gates BEFORE any paid vision call (HD, shot cuts, motion/frozen).
3. Fail-closed: no verified clip -> still or text card, never a wrong clip.
4. Every used clip capped at ~7s (copyright posture) and credited by source URL in the DB.
5. Ask before using any paid API.
