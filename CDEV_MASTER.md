# CDEV — MASTER BRAIN (give this file to any new niche chat)

> **SYSTEM VERSION: 2026.09.12-2** — if a chat's understanding predates this, run the sync command
> in §16. The version + what changed is logged in §16.

> **Claude, if you are a fresh session: read this file top to bottom before doing anything.**
> This is the single source of truth for how CDev works. Where older docs disagree with this file,
> this file wins (see §15 for which older docs are stale). Everything real lives on disk, not in
> chat memory. Reply to the owner in **Hinglish** (Latin script), short and direct, numbers not vibes.

---

## 0. What CDev is, in sixty seconds

CDev is a **footage engine** for running **50–100 faceless YouTube channels** across many niches
(cars, defence, sports, celebrities, crime, history, …). Target: **50–70 videos/day, each ≥20 min**.

The human keeps everything that makes a channel original. CDev finds the pictures, cuts them to the
narration, and renders.

| The owner provides (manual, for originality) | CDev does (the tool) |
|---|---|
| idea / angle | style pack, measured from competitors |
| script (and voiceover, or just script if TTS is used) | footage acquisition + the shared library |
| thumbnail | clip selection, alignment to narration, timeline |
| title, description, tags | render (grade, motion, typography, transitions), audio, QC |
| **frame ratings** (the most valuable input — see §13) | reuse tracking, coverage, fail-closed gates |

CDev must stay **separate from ProStudio** (the owner's movie/TV-essay system at `D:\Lib`). Never
mix them.

---

## 1. THE ONE ARCHITECTURE DECISION — one shared library, scoped by collections + a COMMON pool

This is the "hybrid" model and it is the whole game. Read it carefully.

**There is ONE library for ALL channels** — a single `catalog.sqlite` + one `objects/` store, on a
big drive. A niche never gets its own separate library file. Isolation happens at **retrieval time**
by *collections*, not by separate databases. This is already built into `CODE/catalog_db.py`.

Every asset is tagged into one or more **layers** (`catalog_db.VALID_LAYERS`):

| layer | holds | shared across niches? |
|---|---|---|
| `PROJECT` | footage specific to one video/story | no — scoped to that project |
| `ENTITY` | footage of a specific person/vehicle/place (tagged by entity) | only where that entity is valid |
| `DOMAIN` | niche-generic (e.g. "military vehicles", "1980s boxing") | within that niche |
| `COMMON` | truly generic b-roll: city, crowd, money, factory, drone, headline sting, stock | **YES — every channel** |
| `GENERATED` | cards, postcards, graphics the tool made | as needed |

A channel retrieves only from **`[its PROJECT] + [its ENTITY tags] + [its DOMAIN] + COMMON`**. So
cars footage can never leak into a boxing video, but the COMMON pool and stock are shared by all 50
channels. **Reuse — including across many chats running at once — happens mostly in COMMON + shared
ENTITY tags.** That is where "clips reused wherever needed" comes from, safely.

Two fail-closed guards make sharing safe (both in `catalog_db.search`):
- **`roster`** — a project declares which *people* may appear. A clip showing anyone else is
  rejected outright, no matter how relevant. This is what stops "narration says one name, a
  different face on screen." (It only judges people; places/events/objects are exempt.)
- **`era`** — if a project needs a time window, clips outside it (or of unknown era, unless allowed)
  are rejected.

### Where the shared library lives (decided 2026-09-12: FRESH start)
The production shared library is **fresh**, at the repo-default root **`D:/CDev/library`**
(`config.library_root()` default; `**/library/` is gitignored so media never enters git). It is
initialised with an empty `catalog.sqlite` (full schema) + `objects/` + a seeded **`COMMON`**
collection. Collection-id convention: `COMMON`, `DOMAIN:<niche>`, `ENTITY:<kind>:<slug>`,
`PROJECT:<niche>:<video>`. The old **test-phase** libraries (`_quadrasteer`, `_ajax`, `_alzado`,
`_tyson`) are **kept for reference only** — they are NOT migrated in (owner's call: start clean). A
new niche populates the shared library at onboarding (hunt tags each asset into COMMON + its own
DOMAIN/ENTITY/PROJECT collections). Populating COMMON and the first niche needs a real `hunt` run
(paid + cookies) — ASK first. Verify current state any time with `python CODE/catalog_db.py` /
`stats()`.

### Concurrency — deliberately deferred (operator's call)
Running 10+ chats writing one SQLite library at once needs a concurrency-safe design (a shared
usage-ledger + safe locking) so reuse/anti-repeat works across chats without "database is locked".
The operator chose to **defer** this. Until it is designed, treat concurrent writes to one shared
library as unproven — one writer per library at a time is safe. This is a placeholder, not a
solution.

---

## 2. Where everything lives (nothing lives in chat)

```
D:\CDev\                         repo (branch: foundation — github.com/nischalshivam/CDev)
  CODE/                          all shared modules (fix once, reaches every niche)
  _quadrasteer/ _ajax/ _alzado/  test niches (cars / defence / sports); each has build.py + hunt.py
  _spinks/ _tyson/               boxing test niche (currently blocked — see §12)
  PACKS/style/<niche>.yaml       per-channel look, measured from competitors
  PACKS/niche/<niche>.*          entities/actions/trusted channels for the niche
  keys.env                       API keys — GITIGNORED, never committed, never printed
  .venv/                         isolated Python (see §11) — NOT the global interpreter
  CDEV_MASTER.md                 this file
```

- **No absolute path in any script.** Each derives the repo root from its own location, and the DB
  stores `objects.rel_path` **relative** to `CDEV_LIBRARY_ROOT`. Move the library to any drive
  letter and it still works — you edit one env var, never the DB.
- `CDEV_LIBRARY_ROOT` points at the shared library root. In the test niches each `build.py` sets it
  to its own folder; in production it points at the ONE shared root.

---

## 3. The pipeline, end to end

```
1  SCRIPT        owner writes it, one idea/line (or DeepSeek/GPT via OpenRouter to save tokens; Claude polishes the hook)
2  TTS           CODE/tts_ai33.py     ai33.pro -> audio + WORD-LEVEL timestamps  (the backbone)
3  ALIGN         CODE/align_beats.py  script line -> exact [start,end] against spoken words
4  SLOTS         build_core.split_beats — beats cut to the niche's max_shot length
5  QUERY+RETRIEVE build_core.pick — per beat: FTS/bm25 + hard gates + scope_collections + roster/era + de-dup + cooldown
6  RENDER        per-shot exposure, branding crop, Ken Burns, per-niche grade + typography (SRT-synced)
7  AUDIO         CODE/audio_design.py — bed + whooshes/impacts + side-chain under speech
8  QC            CODE/qc.py — fail-closed. Nothing ships that fails.
9  DELIVER       final mp4 (+ owner's thumbnail/metadata); Drive per-video folder
```

Run a niche (use the venv python — see §11):
```bash
python _quadrasteer/hunt.py      # build/extend the library — SLOW (hours), paid; ASK before running
python _quadrasteer/build.py     # build the video — ~190s for 3 min on the old PC, ~31s here
python CODE/qc.py _quadrasteer/QUADRASTEER_SAMPLE.mp4
python -m pytest -q              # expect: 64 passed
python CODE/catalog_db.py        # prints library DB path + stats (objects/approved/collections)
```

**Core principle — search keys, not timestamps.** Beats describe WHAT to show (entities, actions,
context, strictness, media_type); the tool searches the library. LLMs cannot reliably find a 3s clip
inside a 10-min video, so timestamps are never used.

---

## 4. The 3-pack system (three independent dimensions)

Keeps 50 videos looking like one editor made them, without a config explosion.

- **Niche pack** (`PACKS/niche/<niche>`) — WHAT is valid: entities (exact make/model/variant),
  actions, trusted channels, strictness rules.
- **Format pack** (`CODE/format_packs.py`) — HOW the story is told: `HISTORY_ARCHIVAL`,
  `COMPARISON_EVIDENCE`, `PROCUREMENT_TIMELINE`, `PRODUCT_LISTICLE`. Chosen per video.
- **Style pack** (`PACKS/style/<niche>.yaml`) — the LOOK: grade, motion, transitions, typography,
  grain, SFX, music, and the measured `max_shot`/cut-rate. Read on every render for that channel.

Measured style profiles (`build_core.STYLES`, `max_shot` from each reference channel):
`clean` 4.2s · `defence` 3.0s · `sportsdoc` 2.6s · `boxing` 3.0s.

---

## 5. Hard identity gates (the most important retrieval concept)

Retrieval uses **hard gates, then ranking** — never soft ranking alone (`catalog_db.search`). An
asset surfaces ONLY if: `review_status='approved'` AND `clean_status in (clean|fixable)` AND the
object file exists AND it passes type + entity + era + quality gates + roster + scope. Then FTS/bm25
ranks the survivors. A wrong variant (Boxer APC when CRV was asked) is **rejected**, not ranked
lower.

Strictness levels: `exact` (only exact entity) · `specific` (exact or close variant) · `general`
(related, score penalty) · `loose` (ambient, heavy penalty).

**Fail-closed everywhere:** if nothing verified matches, render a **still or a text card of the
right thing — never forced moving footage of the wrong thing.** Copyright posture: no rights DB, but
every USED clip is capped at **≤7s** (`config.MAX_CLIP_SECONDS`) and credited by source URL.

---

## 6. How the library grows and pays off

- **Need-driven, not bulk.** Analyse the script(s) first, check the library for gaps, acquire ONLY
  what is missing. Coverage merges duplicate gaps across a batch, so a shared shot is fetched once.
- **Cataloged once, reused forever.** A clip used by 20 videos is charged to Gemini once.
- **Cooldown** stops the same clip appearing in consecutive videos; anti-repeat runs on the finished
  file in QC.
- **Cumulative cost curve** (measured shape): video 1 of a niche is expensive; by video 10–20 most
  beats are library hits. Per-video marginal cost drops toward **$0.10–0.50** once the library is
  deep. Gemini catalog uses cheap local gates first, vision only on survivors.

Cheap-first order (never pay before the free gates run): HD/resolution → shot-cut → motion/frozen →
(only survivors) → Gemini vision.

---

## 7. Sourcing — measured reality (2026-09), the biggest structural risk

Current mix is **80–95% YouTube**. That single dependency is the project's biggest risk; broaden it.

```
                anonymous?     route that works
YouTube         yes            yt-dlp (+ cookies.txt for age/rate) — HD filter BEFORE download
Pexels/Pixabay  yes (keys)     stock_source.py  (COMMON-tier ambience)
Reddit          BLOCKED        cookies.txt (REDDIT_COOKIES)  — 5 anon routes all fail
Instagram       BLOCKED        cookies.txt (INSTA_COOKIES) or instaloader session
Wikimedia       yes            docs_source.py — weak, returns little, needs work
Google Images   yes (SERPER_KEY) serper.dev — open-web stills, returns width/height for HD-before-download; KEY VERIFIED 2026-09-12, but a serper_source.py module is NOT WIRED yet
archive.org     yes            NOT WIRED yet (10k+ PD films) — opportunity
Documents       —             docs_source.py — brochure/spec-sheet stills (proven on cars only)
```

- **Never ask the owner for a password.** Cookies come from an exported `cookies.txt` (a browser
  extension), and `--cookies-from-browser` does NOT work on this machine.
- Per-niche: **celebrities** invert to **stills-first** (video is agency-owned; identity error is
  instantly visible and there is no identity layer yet — §12). **Sports** YouTube is strong but watch
  for other channels' corner logos (crop handles bands, not corners).
- **The real quality gap is DOCUMENTS, not footage** — the cars competitor is 44% stills (brochure
  scans, spec sheets with the line highlighted, window stickers, price/number cards). Stills are the
  most precise AND the cheapest to render. Build documents per niche.

---

## 8. Render + QC

Render (per shot): exposure normalise → branding crop → scale/crop to 1280×720 → Ken Burns
(`perspective` filter, **never `zoompan`** — it shakes; there is a test that fails if it returns) →
per-niche grade → SRT-synced typography → transition → concat → mux audio with `-c:v copy` → one
encode. Output is **1280×720 / 30fps** (all three competitors ship 720p, not 1080p).

`python CODE/qc.py VIDEO.mp4` exits non-zero on failure — nothing ships that fails:
- `audible_bed` / `audible_hits` — measured **above 300 Hz** (a pure sub-bass bed was inaudible yet "fine" overall).
- `frozen_runs` — a dead flat card, NOT a deliberate detailed still (distinguished by frame detail).
- `dark_runs` — a cut sitting near-black.
- `static_ratio` — limit 25% (reference is ~18% static, so stills-led cuts are meant to be partly still).
- `repeat_shots` — perceptual hash on the finished file; flat frames excluded (see the known limit in §12).

---

## 9. Onboarding a new niche (this is what "training the chat" means)

Do this once per channel, in that channel's chat:
1. **Confirm the library** — `python CODE/catalog_db.py`; note stats and whether COMMON exists.
2. **Style pack** — download 2–3 competitor videos and **measure** (median shot, cuts/min,
   clips-vs-stills, text style/position/font, transitions, grade, grain, SFX, music). Write
   `PACKS/style/<niche>.yaml`. Do not eyeball.
3. **Niche pack** — entities (exact make/model/variant), actions, trusted channels, strictness.
4. **Roster + era** — who may appear, and the time window (feeds the fail-closed gates).
5. **Format pack** — pick the structure for this video type.
6. **First video** — narration lock → align → coverage check vs the shared library → demand tickets
   for gaps only → acquire → cheap gates → Gemini catalog → retrieve → render → QC. Show the owner
   frames (§13), take ratings, and double down on what he approves.

Onboarding facts that stay the SAME for every sub-chat: this file, the code, the shared library, the
gates, the QC rules, §11 machine setup, §13 operator rules. What changes per chat: the niche pack,
style pack, roster/era, and the competitor analysis.

---

## 10. Running at scale

- **One chat per channel** while working on it. Chats are disposable; the manifests + library are
  not.
- **Batch**: drop N scripts in a channel folder, run once — coverage merges shared gaps so a shot is
  acquired a single time.
- **Long videos** (20 min–3 h) render in chunks and concatenate, never one giant filtergraph.
- **Multi-chat concurrency**: deferred (§1). Until designed, one writer per shared library at a time.

---

## 11. THIS MACHINE (new PC, set up 2026-09-11) — read before running anything

- Repo: `D:\CDev`, branch **`foundation`** (GitHub default `main` is stale — always `-b foundation`).
- **Use the venv Python, not `python`.** A bare `python` is the GLOBAL interpreter (shared with
  ProStudio) and lacks CDev's packages. Use `D:\CDev\.venv\Scripts\python.exe`, or activate the venv.
  `hunt.py` calls `yt-dlp` through PATH and **crashes unless the venv is activated**.
- `pytest -q` → **64 passed**. ffmpeg 9.0.1 full build (has `perspective`, `--enable-gpl`).
- `keys.env` is present and git-ignored (ai33, Gemini relay, Pexels, Pixabay, **SERPER_KEY**). Serper
  is **verified** (Google Images returns dimensioned results). The rest are **not live-tested** —
  every one is a paid/rate-limited call; ASK the owner before the first real call.
- **Cookies are missing**: the `YT_COOKIES` path in keys.env does not exist, and there are no
  Reddit/Instagram cookies/session. Sourcing new footage is degraded until the owner exports
  `cookies.txt` himself.

---

## 12. Honest state — what is proven, and what is NOT

**Proven:** cold-start sourcing (three libraries built), speed 869s→~190s (per 3-min), Ken Burns
0.000px, repeats 64→0 on the cars sample it was tuned on, cars stills 3%→38%, audio 18 dB under
speech in the audible band, alignment weak_alignment 0, per-niche looks measurably differ, one
shared core (a fix reached a brand-new niche unwired).

**NOT proven / open (be honest, don't overclaim):**
1. **No sample has ever been owner-approved** — real defects found in all three.
2. **Alzado (sports) video never built**; **no 20-minute video ever built**; **no two videos back to
   back** (50–70/day is arithmetic, not a demonstration).
3. **No accuracy layer** — no `identity_continuity` (subject changing mid-clip), only 2-frame
   sampling; no `footage_class` (only a `talking_head` bool; ~15/777 Ajax clips are graphics treated
   as real). This is the root of wrong-face/wrong-shot.
4. **Clip variety weakness (confirmed 2026-09-12):** the cars sample repeats the same drone shot
   (v009≈v052) AND the same dashboard shot (v005≈v039); the old sample has the same duplication.
   Perceptual-dedup alone does not catch "same room/framing" — the fix is per-source/per-place
   diversity caps (canonicalise `places`, cap by place+framing). Do NOT rely on QC's 1-fps sampling
   to catch it.
5. **Boxing niche is blocked**: 6 scripts use `ROOT` before defining it; `typography.lower_third`
   raises NameError `size_px`; and `_tyson/fx/grain.mp4`, `_spinks/raw2/lN4s_HNoIaQ.mp4`,
   `_tyson/vo.wav` are missing (only the owner's old machine has them).
6. **Documents exist only for cars.** **Shared-library unification not wired** (§1). **archive.org
   not wired; Wikimedia weak.** **Corner-logo branding not removed.**

Recommended order (from HANDOVER §10): shared-library + COMMON wiring → accuracy layer
(`footage_class` + `identity_continuity`) → diversity caps → one real 20-min video → documents for
more niches → broaden sources beyond YouTube.

---

## 13. How the owner works — these are rules, not preferences

- **Never say "done" from vibes.** Run the check, quote the number (dB, frames, counts).
- **Show frames FULL SIZE, one at a time** — never a contact-sheet grid. The owner's eye caught every
  serious defect; measurement then explained why. His frame ratings are the highest-value input.
- **A clean zero is suspicious** — "0 cuts", "0% watermarks" have both meant the check never ran.
  `None` ≠ `[]`. Confirm a measurement actually ran before trusting a zero.
- **Decide by running, not by reading** — stale comments and starred READMEs have both lied.
- **When a bug is found in one place, grep for it everywhere** — it is never alone.
- **The owner's rule is often not the first one you'd infer** — ask when unsure (e.g. "too many
  clips from one video" meant *looked the same*, not *same source*).
- **Ask before any paid API call; never ask for or handle a password.** Any single used clip ≤7s.

---

## 14. BOOTSTRAP — the paste block for a new niche chat

Open a fresh chat for the channel and paste this (edit the 4 values):
```
Read D:/CDev/CDEV_MASTER.md first, completely.

PROJECT
  repo         : D:/CDev            (branch: foundation)
  python       : D:/CDev/.venv/Scripts/python.exe   (NOT bare `python`)
  channel_id   : <e.g. cycles-uk>
  niche        : <e.g. cycles>
  competitors  : <2-3 YouTube channel/video URLs to reverse-engineer the editing style>

I provide : idea, script (+ voiceover unless we use TTS), thumbnail, title/description/tags, frame ratings.
You do    : style pack -> footage -> shared library (COMMON + niche collections) -> clip selection -> render -> QC.
Library   : ONE shared library, scoped by collections + COMMON (see §1). Never make a second library per niche.

Start by confirming the library state (python CODE/catalog_db.py) and telling me exactly what you need.
```

---

## 15. Deeper docs — and which are stale

Accurate and worth reading: **`HANDOVER.md`** (whole system, measured), `CODE/build_core.py` and
`CODE/qc.py` docstrings (every non-obvious decision with its measurement), `SETUP_NEW_PC.md`,
`DOWNLOADERS.md`, and the owner-supplied FOOTAGE-WORKFLOW case studies + V3 index spec.

**Stale — trust THIS file over them:** `PROCESS.md` describes an older `demandscout.py` + JSON-library
flow that the SQLite `catalog_db` + `_<niche>/build.py` path has superseded. `NEW_CHANNEL_KIT.md`'s
paste block still uses the old `C:/Users/Dell/Downloads/CDev` path — use §14 above instead.

---

## 16. HOW UPDATES REACH EVERY CHAT (future-proofing) — read this

The whole point of "nothing important lives in chat" is that **you update ONE place (this git repo),
not N chats.** A new finding, a new source, or a whole new subsystem propagates like this:

1. **One source of truth = the repo.** All logic is in `CODE/`; all doctrine is in this file. Every
   niche chat reads the code from disk *at run time* and reads this file when pointed at it. Chats
   are disposable; the repo is not.
2. **To ship a change:** edit `CODE/` and/or this file → bump the `SYSTEM VERSION` at the top →
   add a line to the changelog below → `git add -A && git commit && git push`.
3. **To update a machine:** `cd D:/CDev && git pull`. That is it — every chat on that machine now
   runs the new code the next time it executes anything, because they all share `CODE/`. You do NOT
   edit 10 chats.
4. **To sync an already-open chat's understanding**, paste this one line into it:
   > `cd D:/CDev && git pull` — then: *"re-read D:/CDev/CDEV_MASTER.md; we're now on the version at the top. Tell me what changed vs what you assumed."*
   A niche chat's own config (its style pack, roster, niche pack) is untouched by a system update —
   only the shared engine + doctrine change.
5. **A massive change / a whole new system:** same model — bump the version, rewrite the affected
   sections, commit, pull, re-read. If it is genuinely a different system, make it a new branch (or
   a new repo + a new MASTER file) and point new chats at that; the propagation mechanism is
   identical. Keep the old branch until the new one is proven.
6. **Memory vs repo:** Claude's persistent *memory* is only for how the owner works (§13) and
   machine facts — never the pipeline spec. Pipeline truth lives in the repo so a `git pull` is the
   only update anyone needs.

**A chat can self-check it is current:** compare the `SYSTEM VERSION` it read against
`git -C D:/CDev log -1 --format=%h` / this file's top line. If older, it must `git pull` and re-read
before doing niche work.

### System changelog (newest first)
- **2026.09.12-2** — Fresh shared library initialised at `D:/CDev/library` (empty catalog + COMMON
  seeded), old test libraries kept for reference only (§1). Added Serper/Google Images as a data
  source — key saved + verified, source module still to be written (§7).
- **2026.09.12-1** — First `CDEV_MASTER.md`: unified doctrine grounded in live code; declared the
  shared-library + COMMON hybrid as the target; documented the update/propagation protocol (this
  section); listed current data sources (§7). Supersedes `PROCESS.md` / `NEW_CHANNEL_KIT.md` paths.

