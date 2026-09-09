# CDev — HANDOVER

**Read this first, completely, before touching anything.** It is written for a Claude session that
starts with zero context. Everything here was measured on a real corpus; where something is a guess
it says so.

---

## 0. Sixty-second version

CDev is a **footage engine**. The owner writes the script, idea, title and thumbnail by hand. CDev
finds the pictures, cuts them to the narration, and renders the video.

Target: **50–70 videos per day, minimum 20 minutes each**, across many niches (cars, defence,
sports, celebrities, …). Each niche is a separate channel with its own library and its own look.

Current honest state: **three ~3-minute samples exist** (cars, defence, boxing). A 20-minute video
has never been attempted. Nothing is at competitor quality yet. Sections 8 and 9 say exactly why.

---

## 1. How the owner works — read this before writing code

These are not preferences, they are how the project has actually gone wrong.

**Reply in Hinglish** (Latin script, not Devanagari). Short, direct, no padding.

**Never say something is done from vibes.** Run the check and quote the number. The owner has caught
"fixed" claims that were false more than once — a mix declared done that measured −53 dB (silence),
a frame called a "CGI bumper" that was real footage nobody had looked at.

**Measure before optimising, and measure the right thing.**
- Three rounds of obvious optimisation produced *zero* improvement (860s → 869s) because they
  targeted the wrong stage. Stage timers found the real one immediately.
- The audio bed measured fine in total energy and was inaudible: all of it sat below 300 Hz, which
  laptop speakers do not reproduce. The measurement was of the wrong quantity.

**Show frames FULL SIZE, one at a time — not a contact-sheet grid.** The owner said plainly of a
grid: *"aise mujhe kya samajh aayegi?"* Every serious defect in this project was caught by the owner
looking at a frame, not by a measurement. Measurement then explained *why*.

**A clean zero deserves more suspicion than a messy number.** "0 cuts detected" once meant a log
flag had suppressed the detector's output. "0% watermarks" once meant the field did not exist.
`None` and `[]` are different things.

**Decide by running, not by reading.** A stale code comment once produced wrong advice. A 591-star
scraper's README claims "No API keys required!" — it does not work (§6).

**When a bug is found in one place, search everywhere for it.** It is never alone. `zoompan` was
fixed in three builds and was still live in a fourth plus three unused modules. A hard-coded path
bug had already been fixed twice before a third copy was found.

**The owner's rule is often not the first rule you would infer.** "Too many clips from one video"
did not mean "cap clips per video" — ten clips from ten *different rooms* were fine; the objection
was to clips that *looked the same*.

---

## 2. Where things are, and how paths work

```
<REPO>/                         git: github.com/nischalshivam/CDev
  CODE/                         all shared modules
  _quadrasteer/                 niche: cars      (Quadrasteer script)
  _ajax/                        niche: defence   (British Army Ajax)
  _alzado/                      niche: sports    (Lyle Alzado)
  _spinks/  _tyson/             niche: boxing    (Tyson–Spinks; _tyson holds its library)
  keys.env                      API keys — GITIGNORED, never committed
  HANDOVER.md                   this file
```

**No absolute path appears in any script.** Every script derives the repo root from its own
location:

```python
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
```

**The drive letter does not matter.** Libraries are portable because `objects.rel_path` in SQLite is
relative (`objects/03/03bf52….mp4`) and is resolved against the `CDEV_LIBRARY_ROOT` environment
variable, which each niche script sets to its own folder. Copy a library anywhere and it works.

Environment variables that matter (all optional except the keys):

```
CDEV_LIBRARY_ROOT   set automatically by each niche script
YT_COOKIES          path to a cookies.txt for YouTube
REDDIT_COOKIES      path to a cookies.txt for Reddit      (required — see §6)
INSTA_COOKIES       path to a cookies.txt for Instagram   (required — see §6)
INSTA_SESSION_USER  alternative to INSTA_COOKIES
```

---

## 3. The pipeline, end to end

```
1  SCRIPT            written by the owner, one idea per line
2  TTS               CODE/tts_ai33.py     ai33.pro, returns word-level timings
3  ALIGN             CODE/align_beats.py  script line -> exact [start,end]
4  SLOTS             build_core.split_beats — beats cut to the niche's max_shot
5  LIBRARY           per niche, built ONCE:
                       yt-dlp -> media_probe (free gates) -> RelayVision (paid) -> SQLite+FTS5
                       + document stills, + stock, + proxies
6  RETRIEVAL         build_core.pick — bm25 + subject gate + global & perceptual de-dup
7  RENDER            per-shot exposure, branding crop, Ken Burns, per-niche grade + typography
8  AUDIO             CODE/audio_design.py — bed, whooshes, side-chain
9  QC                CODE/qc.py — fail-closed. Nothing ships that fails.
```

Run a niche:

```bash
python _quadrasteer/hunt.py      # build the library — ONCE per niche, slow (hours)
python _quadrasteer/build.py     # build the video   — ~190s for 3 minutes
python CODE/qc.py _quadrasteer/QUADRASTEER_SAMPLE.mp4
```

---

## 4. The modules that matter

| module | what it is |
|---|---|
| `build_core.py` | **The shared core. Read this first.** Style profiles, crop, exposure, gating, retrieval, de-duplication, Ken Burns. Written once so a fix reaches every niche. |
| `qc.py` | Automated QC on the finished file. Every check maps to a defect that shipped. |
| `catalog_db.py` | SQLite + FTS5. Fail-closed retrieval: approved + clean + file-exists + entity/era/roster gates. |
| `frame_quality.py` | Free local measurement: sharpness, ghosting, static-overlay, branding_box, windowed decode. |
| `media_probe.py` | HD gate, histogram cut detection, motion/still_run. Runs BEFORE any paid call. |
| `vision.py` | `RelayVision` — openlux relay, **gemini-2.5-flash only**. Cheap gates first, vision on survivors. |
| `align_beats.py` | Global sequence alignment of script to spoken words. |
| `typography.py` | Cards. Style-parameterised (`boxing` / `clean` / `sportsdoc` / `defence`). |
| `audio_design.py` | Bed, impacts, punch-ins, final mix. |
| `entity_bind.py` | Beat → person resolution, roster, alias normalisation. |
| `docs_source.py` | Document stills: brochure page extraction, Wikimedia. |
| `insta_source.py` / `reddit_source.py` | Cookie-based sources. |
| `stock_source.py` / `yt_source.py` | Pexels+Pixabay, and cookie-aware YouTube with HD filtering before download. |

Dead, do not revive without re-measuring: `renderer.py`, `renderer_core.py`, `_p1_r107/`.

---

## 5. Numbers that are settled — do not re-derive these

**Competitor benchmark** (three videos the owner supplied, measured identically):

```
                      len    cuts/min  med shot  stills%  motion  bed-under-speech
COMP cars           12.0m      14.4      4.2s      44%      3.3      13.7 dB
COMP sports         20.7m      23.1      2.6s      16%      4.4      10.9 dB
COMP defence        12.3m      20.1      3.0s       0%     13.0       5.8 dB
```
All three ship **1280×720**, not 1080p.

**The real gap is DOCUMENTS, not footage quality.** The cars competitor's stills are brochure scans,
spec sheets with the relevant line highlighted in yellow, window stickers, price lists, quote cards
("white text on black"), and number cards ("$850 → INFLATION"). That is where its 44% stills and low
motion come from. Stills are simultaneously the most *precise* option and the *cheapest to render* —
accuracy and speed point the same way.

**Style profiles** (`build_core.STYLES`) — `max_shot` is measured from each reference channel:
`clean` 4.2s · `defence` 3.0s · `sportsdoc` 2.6s · `boxing` 3.0s.

**Performance**, 3-minute video: **869s → ~190s**.
```
pre-gate  402.5 -> 25.6s   analysis proxies (480p CRF30, 45x smaller, 10x faster gating)
mux        96.2 ->  8.5s   -c:v copy (the video was already finished)
render    191.0 -> ~155s   720p instead of 1080p
```
A **720p edit-proxy for rendering was tried and REVERTED**: 998s one-time to save 14s per build.
Marked "measured negative" in `build_core.edit_proxy`. Do not re-enable without re-measuring.

**Ken Burns**: `zoompan` truncates its crop origin (and, in a zoom, the crop height) to whole pixels.
Measured per-frame displacement on our own stills: **zoompan 0.352px → perspective 0.000px**. Canvas
width must be a multiple of 16 and the image input MUST get `-framerate`, or every 6th frame
duplicates. Motion mix measured from the reference: zoom 0.99%/s, 18% of shots fully static, pan
about 1 in 34. There is a test (`test_no_zoompan_in_active_render_paths`) that fails if it returns.

**Library depth**, measured on the cars library: gate pass rate **60%** → 310 usable video + 76
stills = pool 386.
```
 3-minute video ~ 42 slots   -> comfortable
20-minute video ~285 slots   -> TIGHT; a 20-min video needs 3-4x this library
```

---

## 6. Sourcing — measured reality, 2026-09-04

Current mix across all three libraries: **80–95% YouTube**, 5–10% Pexels/Pixabay, 0–13% stills.
That single dependency is the biggest structural risk in the project.

```
                anonymous access        route that works
YouTube         works                   yt-dlp (+ cookies.txt for age/rate limits)
Pexels/Pixabay  works (API keys)        stock_source.py
Reddit          BLOCKED                 cookies.txt  (REDDIT_COOKIES)
Instagram       BLOCKED (429 on 1st)    cookies.txt  (INSTA_COOKIES) or instaloader session
archive.org     works                   NOT YET WIRED — 10k+ PD films, 1.8k CC newsreels
Wikimedia       works                   weak implementation, returns almost nothing — needs fixing
```

Reddit, five routes tried, all fail: `www…/top.json` → 403; `old…/top.json` → 404; session warm-up
→ 200 but an HTML "Welcome to Reddit" wall; + `over18` / `eu_cookie` → same wall. The popular
`ksanjeev284/reddit-universal-scraper` (591 stars) advertises "No API keys required!" — that is the
technique the wall now defeats. Its README is out of date.

`--cookies-from-browser` **does not work on the owner's machine**: Chrome's cookie DB cannot be
copied, Edge fails DPAPI decryption, Firefox is not installed. Export `cookies.txt` manually with a
browser extension. **Never ask the owner for a password and never handle one.**

Per-niche guidance:
- **Sports** — YouTube is strong (453 clips of 1970s–90s NFL were found). Watch for other channels'
  branding baked in; the crop handles horizontal bands but **not corner logos**.
- **Celebrities** — invert the mix to **stills-first**. Video is agency-owned (Getty/AP) and not
  freely available; official accounts post high-resolution photographs. Identity error is instantly
  visible here and there is no identity verification yet (§9).

---

## 7. QC — what it checks and why

`python CODE/qc.py VIDEO.mp4` exits non-zero on failure. Each check exists because that exact defect
shipped and the owner found it.

| check | why |
|---|---|
| `audible_bed` / `audible_hits` | measured **above 300 Hz**. A bed of pure sub-bass measured −20 dB overall and was inaudible. |
| `frozen_runs` | catches a dead card, **not** a deliberate still. Distinguished by frame DETAIL — a photograph is detailed, a dropout card is flat. |
| `dark_runs` | 30 seconds of one cut sat below YAVG 40 — visibly black. |
| `static_ratio` | limit 25%: the reference channel is 18% static, so a stills-led cut is supposed to be partly still. |
| `repeat_shots` | perceptual hash on the finished file. A 187s cut once contained **64 repeated shots**. Flat frames are excluded — their hash is meaningless. |

An output-level "foreign watermark" check was written and **deliberately removed**: it flagged our
own lower-thirds and every 4:3 pillarbox seam, 26 hits on a clean cut. A check that cries wolf is
worse than none. Foreign branding is prevented at SOURCE level instead (`frame_quality.branding_box`,
which measured 26×–43× over baseline on genuinely branded sources).

`python -m pytest -q` — **64 tests**. Notable ones pin bugs that could otherwise return: the roster
gate is fail-closed, cards must fit the frame at any resolution, no active render path may use
`zoompan`.

---

## 8. What is PROVEN

- Cold-start sourcing: three libraries built from nothing (518 / 777 / 507 clips).
- Speed: 869s → ~190s per 3-minute video, verified twice end to end.
- Ken Burns smooth: 0.000px, measured through the build's real code path.
- Repeats: 64 → 0.
- Stills ratio (cars): 3% → 38%, against a competitor's 44%.
- Audio: bed inaudible → 18 dB under speech in the audible band.
- Alignment: weak_alignment 0 on all three scripts.
- Style profiles produce measurably different looks per niche.
- One shared core; a fix now reaches every niche (proved when Ajax, a brand-new niche, cropped
  branding on three sources without anything being wired for it).

## 9. What is NOT proven — be honest about this

1. **The owner has never approved a sample.** Three were delivered; the owner found real defects in
   every one. Nothing has ever been clean first time.
2. **The Alzado (sports) video has never been built.** Library and build script are ready; the build
   has not been run.
3. **A 20-minute video has never been attempted.** Library depth is the binding constraint (§5).
4. **Two videos have never been built back to back.** There is no batch or queue. 50–70/day is
   arithmetic, not a demonstration.
5. **No accuracy layer.** The V3 indexing spec asks for `identity_continuity` (does the subject
   change mid-clip?) and 7-frame sampling; we sample 2 frames and have no continuity field. This is
   the root of "the narration says one name and a different face is on screen".
6. **No `footage_class`.** Only a `talking_head` boolean. Measured: **15 of 777 Ajax clips are
   graphics/animations** currently treated as real event footage.
7. **Documents exist only for cars** (one brochure source, 66 pages). Ajax has 0 images.
8. **`typography.highlight()` is built but never used** — nothing decides *which* line of a spec
   sheet to highlight.
9. **No per-source / per-scene diversity cap.** Note that perceptual de-duplication is the method
   the FOOTAGE-WORKFLOW case studies say FAILS for this: clips a machine calls different (median
   hash distance 62) can be "the same room, same person, same framing" to a human. The documented
   fix is canonicalising `places` and capping by place + framing.
10. **Corner-logo branding is not removed** — only horizontal bands.

---

## 10. Recommended order of work

1. **Build the Alzado video** — closes the third niche, library is ready.
2. **`footage_class` + `identity_continuity`** — the accuracy layer; fixes the wrong-shot class.
3. **Attempt one 20-minute video** — find where library depth actually breaks.
4. **Documents for Ajax and Alzado** — the single biggest quality lever, proven on cars.
5. **Wikimedia + archive.org sources** — reduce the 90% YouTube dependency.
6. **Per-source/place diversity caps**; **corner-logo crop**.

---

## 11. Reference documents to read

In the repo:
- `SYSTEM_OVERVIEW.md`, `FOUNDATION.md`, `PROCESS.md` — earlier architecture writing
- `DOWNLOADERS.md` — which downloader per platform, with measured auth reality
- `CODE/build_core.py` and `CODE/qc.py` docstrings — every non-obvious decision is explained where
  it lives, with the measurement that forced it

Supplied by the owner (keep these — they are the source of several core design decisions):
- **FOOTAGE-WORKFLOW package** — 12 measured case studies. `media_probe.py` and `vision.py` were
  built from it. Read `CASE-STUDIES.md` in full.
- **V3 Semantic Visual Index spec + addendum** — the target architecture. §9 items 5 and 6 come from
  here.
- **KEN-BURNS-FIX.md** — the shake fix, applied and verified.
- The three competitor videos — the benchmark in §5.

---

## 12. Setup on a new machine

See `SETUP_NEW_PC.md` in this folder. Short version:

```bash
git clone https://github.com/nischalshivam/CDev.git
cd CDev
pip install -r requirements.txt          # or the list in SETUP_NEW_PC.md
# copy keys.env into the repo root (NOT in git)
# copy the memory/*.md files to the new machine's Claude memory folder
# copy the library folders (_quadrasteer, _ajax, _alzado, _tyson) anywhere — paths are relative
python -m pytest -q                      # expect 64 passed
```

`keys.env` and the libraries are the only things git does not carry.
