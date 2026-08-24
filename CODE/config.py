#!/usr/bin/env python3
"""
config.py — one place for machine-specific paths + tunable constants.

WHY: the library lives on an external SSD whose Windows drive letter CHANGES on reconnect
(E:->F:->G:). If any absolute path is baked into code or the database, a letter change breaks
everything. So the ONLY place a drive letter appears is LIBRARY_ROOT here (or the env var), and the
database stores paths RELATIVE to it. Drive letter changed? Edit one value; the DB is never touched.

Set the SSD path with the CDEV_LIBRARY_ROOT env var, or a `config/library.toml` with `root = "..."`,
otherwise it defaults to `<repo>/library` (fine for local dev/tests).
"""
from __future__ import annotations
import os
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


def _load_keys_env():
    """Load gitignored keys.env (KEY=VALUE lines) into os.environ once. Never hard-code secrets."""
    p = REPO_DIR / "keys.env"
    if not p.exists():
        return
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_keys_env()


def _read_toml_root() -> str | None:
    cfg = REPO_DIR / "config" / "library.toml"
    if not cfg.exists():
        return None
    try:
        import tomllib  # py3.11+
        data = tomllib.loads(cfg.read_text(encoding="utf-8"))
        return data.get("root")
    except Exception:
        # tolerant hand-parse: a line like  root = "X:/CDevData/library"
        for ln in cfg.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln.startswith("root"):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def library_root() -> Path:
    """Resolve the library root at call time (never cache a drive letter)."""
    root = os.getenv("CDEV_LIBRARY_ROOT") or _read_toml_root() or str(REPO_DIR / "library")
    return Path(root)


def objects_dir() -> Path:
    return library_root() / "objects"


def db_path() -> Path:
    return library_root() / "catalog.sqlite"


# ---- tunables ---------------------------------------------------------------
# Full-auto approval guard (operator chose full-auto): a freshly cataloged asset becomes
# 'approved' only if clean/fixable AND Gemini match confidence >= this, else 'quarantined'.
AUTO_APPROVE_CONF = float(os.getenv("CDEV_AUTO_APPROVE_CONF", "0.70"))

# Copyright posture (operator decision): no rights DB, but every USED clip is capped in length.
MAX_CLIP_SECONDS = float(os.getenv("CDEV_MAX_CLIP_SECONDS", "7.0"))

# Gemini catalog model + prompt/schema versions (for the result cache key).
GEMINI_MODEL = os.getenv("CDEV_GEMINI_MODEL", "gemini-3.6-flash")
CATALOG_PROMPT_VERSION = "cat-v1"
CATALOG_SCHEMA_VERSION = "seg-v2"

# Third-party Gemini relay (OpenAI-compatible) + YouTube cookies — values live in keys.env.
GEMINI_RELAY_BASE = os.getenv("GEMINI_RELAY_BASE", "")
GEMINI_RELAY_KEY = os.getenv("GEMINI_RELAY_KEY", "")
GEMINI_RELAY_MODEL = os.getenv("GEMINI_RELAY_MODEL", "gemini-2.5-flash")
YT_COOKIES = os.getenv("YT_COOKIES", "")
