# DOWNLOADERS — source-material grabbers (reference)

> Drop this file into any chat and say "use these to pull source material." It lists the tool for
> each platform, how it is installed, and one working command. These FEED the footage library
> (CDev cataloger / FOOTAGE-WORKFLOW) — every clip/image they pull is a candidate that then goes
> through the cheap gates + Gemini cataloging.

Everything below was installed + verified on this PC (Windows, Python 3.14). Scripts install to
`...\pythoncore-3.14-64\Scripts` which is not on PATH, so call them with `python -m <tool>`.

---

## Chosen tool per platform (and why)

| Platform | Tool | Status | Why this one |
|---|---|---|---|
| **Reddit** | **bdfr** (bulk-downloader-for-reddit) | ✅ installed | trusted pip package; downloads a whole subreddit's images/videos/galleries |
| **Instagram** | **instaloader** | ✅ installed (4.15.3) | trusted pip package; posts / reels / profiles / hashtags |
| **YouTube** | **`CODE/yt_source.py`** (ours) + yt-dlp | ✅ already built | cookie-aware + **HD-filter BEFORE download** (better than the batch wrapper) |
| **TikTok** | **yt-dlp** directly | ✅ available | yt-dlp has a TikTok extractor; no extra tool needed |

### Vetted but NOT used (with reason)
- **EDM115/bulk-youtube-download** — legitimate (MIT, yt-dlp+ffmpeg+Deno wrapper, no shady steps),
  but **redundant**: `yt_source.py` already does cookie + HD-filtered YouTube downloads, better
  integrated with our gates.
- **The-Senile-Developers/TikTok-Bulk-Downloader** — **SKIPPED for safety**: it ships a prebuilt
  Windows `.exe` from a small (13-star, 4-commit) repo; running an untrusted binary is a risk.
  yt-dlp already downloads TikTok, so it's unnecessary.

---

## Install (already done here)

```bash
python -m pip install --upgrade bdfr instaloader
python -m pip install "praw>=7.7,<8"     # bdfr needs praw 7.x; praw 8.x breaks it (BaseTokenManager)
```

`praw` note: a fresh install pulls praw 8.x which bdfr cannot use — pin to 7.x as above. Verified:
`instaloader 4.15.3`, `bdfr download` runs, `praw 7.8.2`.

---

## Usage — one working command each

### Reddit (bdfr)
Needs a free Reddit "script" app (client_id + secret) in `bdfr` config the first time.
```bash
# a subreddit's top posts of the year -> a folder
python -m bdfr download "D:/source/reddit" --subreddit Watches --sort top --time year --limit 100
# a specific user
python -m bdfr download "D:/source/reddit" --user someuser --limit 50
```

### Instagram (instaloader)
Works anonymously for public content (rate-limited); `--login <user>` (you type the password) for more.
```bash
# a profile's posts (images + videos)
python -m instaloader profile <account>            # e.g. a watch brand
# only posts with a hashtag
python -m instaloader "#luxurywatches" --count 50
# a single reel/post by shortcode
python -m instaloader -- -<shortcode>
```

### YouTube (ours — cookie + HD filter)
```bash
python CODE/yt_source.py "Mercedes R107 SL review"   # searches, HD-prechecks, downloads passers
# or in code: from yt_source import fetch_hd; fetch_hd(query, n, out_dir, avoid=[...])
```

### TikTok (yt-dlp)
```bash
yt-dlp --cookies www.youtube.com_cookies.txt "https://www.tiktok.com/@user/video/123..."
yt-dlp "https://www.tiktok.com/@user"                # a whole account
```

---

## Safety + limits
- **Login/credentials:** you type passwords yourself — never share them in chat. bdfr uses a Reddit
  API app (id/secret); instaloader/yt-dlp use cookies or anonymous access.
- **Vertical content:** TikTok/Instagram reels are usually 9:16. Our HD gate rejects portrait for
  motion footage — so these are best for **images / landscape clips**, not hero video.
- **Rights posture (project decision):** commentary/fair-use, keep any used clip ≤7s. These tools
  are for gathering *candidate* source material; the cataloger's gates decide what is kept.
- **Do not run untrusted prebuilt binaries.** Prefer pip/official tools (as chosen above).

*Installed + verified 2026-08-25. Tools: bdfr, instaloader, yt-dlp, yt_source.py.*
