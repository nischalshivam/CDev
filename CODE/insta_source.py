#!/usr/bin/env python3
"""insta_source.py — Instagram as a STILLS source, for niches where photographs beat footage.

Why Instagram at all. Measured across the three libraries built so far, sourcing is 80-95% YouTube:

    cars   80% YouTube · 7% stock · 13% stills
    ajax   95% YouTube · 5% stock ·  0% stills
    alzado 86% YouTube · 10% stock · 4% stills

That single dependency is the biggest structural risk in the pipeline, and it is worst exactly
where the next niches are going. For CELEBRITY subjects the right mix inverts: agency-owned video
(Getty/AP/paparazzi) is not freely available, while official accounts post high-resolution stills of
the actual person. Stills are also the most precise and the cheapest thing this pipeline can render.

AUTHENTICATION — read this before assuming it is broken.
Anonymous access no longer works. Measured 2026-09-04, first request, no prior traffic:

    JSON Query to api/v1/users/web_profile_info/: 429 Too Many Requests

So a session is required. This module NEVER handles a password. The owner creates a session once,
themselves, in their own terminal:

    python -m instaloader --login YOUR_USERNAME

Instaloader prompts for the password directly and writes a session file next to its config. From
then on `load_session()` here picks it up and nothing further is needed.

VERTICAL CONTENT. The library's HD gate is `width>=1280 AND height>=720 AND width>height`, so a
vertical reel can never pass as video. Photographs are different: a tall photo is still usable
because the renderer gives stills a Ken Burns move over a cropped region. Hence video is filtered on
orientation here, and photos are not.
"""
from __future__ import annotations
import itertools
from pathlib import Path

MIN_PHOTO_W = 900          # below this a still cannot fill a 1280-wide frame without visible softness


def _loader(dest: Path, quiet: bool = True):
    import instaloader
    return instaloader.Instaloader(
        dirname_pattern=str(dest / "{profile}"),
        save_metadata=False, download_video_thumbnails=False,
        download_comments=False, post_metadata_txt_pattern="", quiet=quiet)


def cookies_path() -> str:
    import os
    return os.getenv("INSTA_COOKIES", "")


def have_session(username: str = "") -> bool:
    """Usable if EITHER an instaloader session file exists OR a cookies.txt is configured.

    Two routes because `--cookies-from-browser` is broken on this machine (Chrome DB lock, Edge
    DPAPI failure, no Firefox), so an exported cookies.txt is the mechanism that actually works
    here — the same one already used for YouTube."""
    if cookies_path() and Path(cookies_path()).exists():
        return True
    if not username:
        return False
    import instaloader
    L = instaloader.Instaloader(quiet=True)
    try:
        L.load_session_from_file(username)
        return True
    except Exception:
        return False


def profile_stills(username: str, dest, session_user: str = None, want: int = 20,
                   include_video: bool = False) -> list[dict]:
    """Download up to `want` PHOTOS (and optionally landscape video) from a public profile.

    Returns [{path, width, height, is_video, caption, date}]. Raises nothing on a per-post failure —
    a single bad post must not lose the whole batch."""
    import instaloader
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    L = _loader(dest)
    ck = cookies_path()
    if ck and Path(ck).exists():
        import http.cookiejar
        jar = http.cookiejar.MozillaCookieJar(ck)
        jar.load(ignore_discard=True, ignore_expires=True)
        L.context._session.cookies.update(jar)
    elif session_user:
        try:
            L.load_session_from_file(session_user)
        except Exception as e:
            raise RuntimeError(
                f"no instaloader session for '{session_user}'. Create one yourself with:\n"
                f"    python -m instaloader --login {session_user}\n"
                f"(instaloader asks for the password directly; this tool never sees it)  [{e}]")

    prof = instaloader.Profile.from_username(L.context, username)
    if prof.is_private:
        return []
    got = []
    for post in itertools.islice(prof.get_posts(), want * 3):
        if len(got) >= want:
            break
        w, h = post.dimensions if post.dimensions else (0, 0)
        if post.is_video:
            # a vertical reel can never clear the library's width>height gate — do not spend on it
            if not include_video or w <= h or w < 1280:
                continue
        else:
            if w < MIN_PHOTO_W:
                continue
        try:
            L.download_post(post, target=username)
        except Exception:
            continue
        got.append({"width": w, "height": h, "is_video": post.is_video,
                    "caption": (post.caption or "")[:300], "date": str(post.date_utc.date()),
                    "shortcode": post.shortcode})
    # collect what actually landed on disk
    files = sorted([str(p) for p in (dest / username).glob("*")
                    if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".mp4")])
    for i, g in enumerate(got):
        g["path"] = files[i] if i < len(files) else None
    return [g for g in got if g["path"]]


if __name__ == "__main__":
    import sys
    user = sys.argv[1] if len(sys.argv) > 1 else "gmc"
    sess = sys.argv[2] if len(sys.argv) > 2 else None
    if sess and not have_session(sess):
        print(f"no session for {sess}. Run:  python -m instaloader --login {sess}")
        sys.exit(1)
    out = profile_stills(user, "_insta_test", session_user=sess, want=5)
    print(f"{len(out)} stills")
    for o in out:
        print(" ", o["width"], "x", o["height"], o["path"])
