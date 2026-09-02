#!/usr/bin/env python3
"""
sync.py — one command that keeps GitHub in step with whatever a chat just did.

    python CODE/sync.py                 # export library index, commit, push
    python CODE/sync.py -m "message"    # with a custom commit message
    python CODE/sync.py --status        # show what would be synced (no push)

WHAT SYNCS TO GITHUB (small, text, portable):
    code, packs, project manifests, clue scripts, coverage/run reports,
    CHANNELS.md, and library_index.jsonl  <- a text snapshot of the library

WHAT NEVER SYNCS (stays on the SSD):
    objects/*.mp4|jpg   hundreds of GB of media
    catalog.sqlite      binary + rewritten every run (git-hostile)
    keys.env            secrets

So a new machine = `git clone` + plug the SSD in. The repo carries the brain, the SSD the media.
"""
from __future__ import annotations
import io
import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

REPO = Path(__file__).resolve().parent.parent
INDEX_OUT = REPO / "library_index.jsonl"


def run(args, **kw):
    return subprocess.run(args, cwd=str(REPO), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def export_library_index() -> int:
    """Write a text snapshot of the catalog so the repo always shows what the library holds,
    even from a machine that does not have the SSD attached."""
    try:
        import catalog_db
        db = config.db_path()
        if not Path(db).exists():
            return 0
        c = catalog_db.Catalog(db)
        rows = []
        for r in c.cx.execute("SELECT * FROM assets WHERE review_status='approved' "
                              "ORDER BY source_id, start_ms"):
            cj = json.loads(r["catalog_json"] or "{}")
            ents = [x["entity_id"] for x in c.cx.execute(
                "SELECT entity_id FROM asset_entities WHERE asset_id=?", (r["asset_id"],))]
            cols = [x["collection_id"] for x in c.cx.execute(
                "SELECT collection_id FROM collection_assets WHERE asset_id=?", (r["asset_id"],))]
            rows.append({"id": r["asset_id"], "source": r["source_id"], "type": r["type"],
                         "from_s": (r["start_ms"] or 0) / 1000, "to_s": (r["end_ms"] or 0) / 1000,
                         "desc": r["description"], "entities": ents, "collections": cols,
                         "serves": cj.get("serves", []), "keywords": cj.get("keywords", []),
                         "shot": cj.get("shot"), "quality": r["quality"],
                         "clean": r["clean_status"], "used": r["times_used"]})
        with io.open(INDEX_OUT, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        c.close()
        return len(rows)
    except Exception as e:                      # never let an index export block a code push
        print(f"[sync] library index skipped: {str(e)[:90]}")
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--message", default=None)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    n = export_library_index()
    if n:
        print(f"[sync] library index: {n} approved assets -> library_index.jsonl")

    changed = run(["git", "status", "--porcelain"]).stdout.strip()
    if not changed:
        print(f"[sync] nothing to sync (branch {branch}, clean)")
        return
    print(f"[sync] branch {branch} — changes:")
    for ln in changed.splitlines()[:25]:
        print("   ", ln)
    if a.status:
        return

    run(["git", "add", "-A"])
    msg = a.message or "Sync: library index + project state"
    r = run(["git", "-c", "user.name=nischalshivam",
             "-c", "user.email=shivamnischal1997@gmail.com",
             "commit", "-m", msg + "\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"])
    if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
        print("[sync] commit failed:", (r.stderr or r.stdout)[-300:]); return
    p = run(["git", "push", "origin", branch])
    if p.returncode != 0:
        print("[sync] push failed:", (p.stderr or p.stdout)[-300:]); return
    print(f"[sync] pushed to origin/{branch}")


if __name__ == "__main__":
    main()
