#!/usr/bin/env python3
"""
project.py — one project's workspace + the clean orchestrator (Catalog-based).

Replaces the legacy flat-JSON `LibraryDB` path in `demandscout_core` (kept only as reference). A
PROJECT is isolated by IDs + a folder, NOT by which chat you're in:

  projects/<channel>/<project_id>/
    project.json          the manifest (workspace/channel/niche/format/style/languages/title)
    scripts/<lang>/       raw.txt, cleaned.txt, approved.txt, approved.sha256  (Stage 0, intake.py)
    plans/<lang>.plan.json  the VisualPlan (clue script)  -> schemas.VisualPlan
    runs/<run_id>/        coverage.json, tickets.json, timeline.json, output/

The shared library (SQLite catalog + objects) lives OUTSIDE the project, on the SSD, and every
project reads/writes the SAME catalog — that is what makes reuse cross-project.
"""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import asdict

import intake
import coverage as CV
from schemas import ProjectManifest, VisualPlan


class Project:
    def __init__(self, base_dir: str | Path, manifest: ProjectManifest):
        self.manifest = manifest.validate()
        self.dir = Path(base_dir) / (manifest.channel_id or "default") / manifest.project_id
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "project.json").write_text(
            json.dumps(asdict(self.manifest), indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- Stage 0: lock a narration (per language) --------------------------
    def add_script(self, lang: str, raw_text: str, fixes: dict = None) -> dict:
        return intake.stage0(self.dir, lang, raw_text, fixes)

    def narration(self, lang: str) -> dict:
        return intake.load_approved(self.dir, lang)

    # ---- the visual plan (clue script) -------------------------------------
    def save_plan(self, plan: VisualPlan):
        plan.validate()
        # the plan MUST be locked to the approved narration it was written from
        approved = self.narration(plan.language)
        if plan.narration_hash != approved["hash"]:
            raise ValueError("plan.narration_hash != approved narration hash — the plan was written "
                             "from a different text than what is locked (broken trio).")
        d = self.dir / "plans"
        d.mkdir(exist_ok=True)
        plan.save(d / f"{plan.language}.plan.json")

    def load_plan(self, lang: str) -> VisualPlan:
        return VisualPlan.load(self.dir / "plans" / f"{lang}.plan.json")

    # ---- coverage against the shared catalog -------------------------------
    def coverage(self, catalog, lang: str, run_id: str, scope_collections=None) -> dict:
        plan = self.load_plan(lang)
        cov = CV.plan_coverage(catalog, plan, scope_collections=scope_collections)
        run = self.dir / "runs" / run_id
        run.mkdir(parents=True, exist_ok=True)
        (run / "coverage.json").write_text(
            json.dumps({"requirements": cov["requirements"],
                        "summary": CV.summarize(cov)}, indent=2, ensure_ascii=False),
            encoding="utf-8")
        (run / "tickets.json").write_text(
            json.dumps([asdict(t) for t in cov["tickets"].values()], indent=2, ensure_ascii=False),
            encoding="utf-8")
        return cov


def collection_ids_for(manifest: ProjectManifest) -> list[str]:
    """The library scope a project may retrieve from: its own project + niche domain + common.
    Keeps niche A's footage from leaking into niche B (the isolation guarantee)."""
    niche = (manifest.niche or "misc").upper().replace(" ", "_")
    proj = manifest.project_id.upper().replace("/", "_").replace(" ", "_")
    return [f"COL_PROJECT_{proj}", f"COL_DOMAIN_{niche}", "COL_COMMON"]
