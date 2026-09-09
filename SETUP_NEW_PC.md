# SETUP — new machine, from nothing to a working build

Follow this top to bottom. Every step ends with a check you can actually run; if a check fails, stop
there rather than continuing.

**Read `HANDOVER.md` first** — it explains what the system is and how the owner works. This file is
only installation.

---

## 0. What must be copied by hand

Git carries the code. It does **not** carry these three things:

| what | where it lives now | where it goes |
|---|---|---|
| `keys.env` | repo root | repo root on the new machine |
| Claude memory (`*.md`, 8 files) | `C:\Users\<you>\.claude\projects\<proj>\memory\` | same folder on the new machine |
| Libraries (`_quadrasteer/library`, `_ajax/library`, `_alzado/library`, `_tyson/library`) | ~20 GB total | anywhere — paths are relative |

Everything else comes from `git clone`.

**The libraries are the expensive part.** They hold downloaded footage, the SQLite catalogue and the
analysis proxies — hours of downloading and paid vision calls. Copy them rather than rebuild. They
are portable: `objects.rel_path` in SQLite is relative and resolves against `CDEV_LIBRARY_ROOT`,
which each niche script sets from its own location. **The drive letter genuinely does not matter.**

---

## 1. System tools

Install these first. On Windows, winget is the least painful route.

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id Gyan.FFmpeg -e
```

If winget is unavailable: [git-scm.com](https://git-scm.com) · [python.org](https://python.org)
(tick **Add Python to PATH**) · [ffmpeg.org](https://ffmpeg.org/download.html) (extract, then add its
`bin` folder to PATH).

**Check — all three must print a version:**

```bash
git --version
python --version          # 3.10 or newer
ffmpeg -version           # must include: --enable-gpl  (the perspective filter needs it)
ffprobe -version
```

**One check that is easy to skip and will silently break the stills:**

```bash
ffmpeg -hide_banner -filters | grep perspective
```
Ken Burns uses the `perspective` filter. Without it, stills fall back to visible shake. See
`HANDOVER.md` §5.

---

## 2. Get the code

```bash
git clone https://github.com/nischalshivam/CDev.git
cd CDev
```

---

## 3. Python packages

```bash
python -m pip install --upgrade pip
python -m pip install numpy pillow requests scipy imagehash pyyaml defusedxml pytest
python -m pip install yt-dlp instaloader
python -m pip install bdfr "praw==7.7.1"
```

**The praw pin is not optional.** bdfr 2.6.2 needs `praw.reddit.BaseTokenManager`, removed in
praw 7.8. With 7.8.x installed, bdfr fails on import:

```
AttributeError: module 'praw.reddit' has no attribute 'BaseTokenManager'
```

Optional, only if you touch those subsystems: `faster-whisper` (transcription), `edge-tts`,
`pandas`, `opencv-python`.

**Check:**

```bash
python -c "import numpy, PIL, requests, scipy, imagehash; print('core ok')"
yt-dlp --version
python -m instaloader --version
python -m bdfr --help | head -3
```

---

## 4. Keys

Copy `keys.env` into the repo root. It is gitignored and must never be committed.

```
GEMINI_RELAY_BASE=https://api.openlux.ai/v1
GEMINI_RELAY_KEY=...
GEMINI_RELAY_MODEL=gemini-2.5-flash
AI33_API_KEY=...
PEXELS_KEY=...
PIXABAY_KEY=...
```

**Check — this must print `RELAY_OK`:**

```bash
python - <<'EOF'
import os, json, urllib.request
for line in open("keys.env"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1); os.environ.setdefault(k, v)
b = os.environ["GEMINI_RELAY_BASE"].rstrip("/"); k = os.environ["GEMINI_RELAY_KEY"]
body = {"model": "gemini-2.5-flash", "max_tokens": 20,
        "messages": [{"role": "user", "content": "Reply with exactly: RELAY_OK"}]}
r = urllib.request.Request(b + "/chat/completions", data=json.dumps(body).encode(),
    headers={"Authorization": "Bearer " + k, "Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(r, timeout=60))["choices"][0]["message"]["content"])
EOF
```

---

## 5. Cookies — needed for three platforms

`--cookies-from-browser` was measured **not working** on the old machine (Chrome's cookie DB could
not be copied, Edge failed DPAPI decryption, Firefox absent). Try it once on the new machine; if it
fails, export `cookies.txt` manually with any "Get cookies.txt" browser extension while logged in.

```bash
setx YT_COOKIES      "E:/keys/youtube_cookies.txt"
setx REDDIT_COOKIES  "E:/keys/reddit_cookies.txt"
setx INSTA_COOKIES   "E:/keys/instagram_cookies.txt"
```

Reddit and Instagram **refuse anonymous access entirely** (measured — `HANDOVER.md` §6), so without
cookies those two sources simply skip themselves. They do not crash the run.

**Never type a password into a tool, and never give one to Claude.** Instaloader's own
`python -m instaloader --login <user>` prompts you directly if you prefer that to cookies.

---

## 6. Put the libraries somewhere

Copy the library folders anywhere with space (~20 GB). Keep each one inside its niche folder if you
want zero configuration:

```
<REPO>/_quadrasteer/library/
<REPO>/_ajax/library/
<REPO>/_alzado/library/
<REPO>/_tyson/library/
```

To keep them on a separate drive instead, point the variable at the new location before running a
niche script:

```bash
set CDEV_LIBRARY_ROOT=E:/CDev-libraries/_quadrasteer/library
```

**Check — must report objects with `missing on disk: 0`:**

```bash
set CDEV_LIBRARY_ROOT=<path to _quadrasteer/library>
python -c "
import sys, os; sys.path.insert(0,'CODE'); import catalog_db
c = catalog_db.Catalog(); root = os.environ['CDEV_LIBRARY_ROOT']
rows = c.cx.execute('SELECT rel_path FROM objects').fetchall()
missing = [r[0] for r in rows if not os.path.exists(os.path.join(root, r[0]))]
print(f'objects: {len(rows)}   missing on disk: {len(missing)}')"
```

---

## 7. Claude's memory

Copy the 8 `.md` files into the new machine's Claude memory folder:

```
C:\Users\<you>\.claude\projects\<project-key>\memory\
    MEMORY.md
    user-cdev.md
    feedback-machine-qc.md
    feedback-own-brain.md
    project-cdev-niches.md
    project-cdev-performance.md
    reference-competitor-benchmark.md
    reference-kenburns-and-indexing.md
```

`MEMORY.md` is the index Claude loads every session; the others are loaded when relevant. Without
these, a new session forgets how the owner works and what has already been measured.

---

## 8. Final verification

```bash
python -m pytest -q
```
**Expect `64 passed`.** If a test fails, fix that before building anything — the tests pin bugs that
have already shipped once.

Then rebuild a known-good video and QC it:

```bash
python _quadrasteer/build.py
python CODE/qc.py _quadrasteer/QUADRASTEER_SAMPLE.mp4
```

Expected, on the old machine:

```
plan: 35 video + 23 stills + 2 cards | 58 UNIQUE assets for 60 slots
DONE  duration ~186.9
QC ... => PASS      (audible_bed, frozen_runs, dark_runs, static_ratio, repeat_shots)
```
Build time ~190s for 3 minutes of video. A first run is slower because analysis proxies are built
once per source.

---

## 9. If something is wrong

| symptom | cause |
|---|---|
| Stills visibly shake | ffmpeg lacks `perspective`, or `-framerate` was dropped from an image input |
| `bdfr` will not import | praw is 7.8.x — pin `praw==7.7.1` |
| Reddit/Instagram return nothing | no cookies configured; both refuse anonymous access |
| Retrieval finds nothing | `CDEV_LIBRARY_ROOT` points at the wrong folder, or the objects were not copied |
| A build writes to an unexpected place | a hard-coded path has crept back in — grep for `C:/Users` and for absolute drive letters |
| QC fails `repeat_shots` | the library is too small for the video length — source more, do not loosen the check |
| Unicode crash on Windows | run with `PYTHONIOENCODING=utf-8`; a printed title once killed an entire overnight build |
