#!/usr/bin/env python3
"""
ProClip Engine / demandscout.py — Universal Documentary Video Automation

Architecture:
  Claude (AI Brain) → Clue Script JSON
  Python (Engine)   → Scrape → Catalog → Match → Timeline → Render

Usage:
  python demandscout.py --script scripts/S001.txt --audio audio/S001.mp3 --niche packs/defence.yaml
  python demandscout.py --queue QUEUE/jobs.json
  python demandscout.py --overnight
"""

import argparse
import json
import os
import sys
import time
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Tuple

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

# Directories
SCRIPTS_DIR = BASE_DIR / "scripts"
AUDIO_DIR = BASE_DIR / "audio"
CLUES_DIR = BASE_DIR / "clues"
OUTPUT_DIR = BASE_DIR / "output"
TIMELINES_DIR = BASE_DIR / "timelines"
QUEUE_DIR = BASE_DIR / "QUEUE"
PACKS_DIR = BASE_DIR / "PACKS"
PROMPTS_DIR = BASE_DIR / "PROMPTS"
LOGS_DIR = BASE_DIR / "logs"
STATE_DIR = BASE_DIR / "state"
RAW_DIR = BASE_DIR / "raw"
CLIPS_DIR = BASE_DIR / "clips"
LIBRARY_DIR = BASE_DIR / "library"

# Ensure directories exist
for d in [SCRIPTS_DIR, AUDIO_DIR, CLUES_DIR, OUTPUT_DIR, TIMELINES_DIR,
          QUEUE_DIR, PACKS_DIR, PROMPTS_DIR, LOGS_DIR, STATE_DIR,
          RAW_DIR, CLIPS_DIR, LIBRARY_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# DATA MODELS
# ============================================================

class JobStatus(Enum):
    QUEUED = "queued"
    BLOCKED = "blocked"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class ClipEntry:
    """A single video clip or image in the library."""
    id: str
    type: str  # "video" | "image" | "map" | "graphic" | "document"
    file: str
    source_type: str  # "youtube" | "wikimedia" | "pexels" | "generated"
    source_url: str
    topic: str
    entities: List[str] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    environment: List[str] = field(default_factory=list)
    description: str = ""
    quality: str = "medium"  # "low" | "medium" | "high"
    duration: float = 0.0
    width: int = 0
    height: int = 0
    license: str = ""
    strictness: str = "general"  # "exact" | "specific" | "general" | "loose"
    times_used: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    cataloged_by: str = ""


@dataclass
class Job:
    """A single production job in the queue."""
    id: str
    script: str
    audio: str
    clue: Optional[str]
    niche: str
    title: str
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    error: Optional[str] = None
    output: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    format_variant: str = "F1"


@dataclass
class Beat:
    """A single narration beat from the Clue Script."""
    beat_id: str
    beat_number: int
    narration_verbatim: str
    start: float
    end: float
    visual_intent: str
    primary_visual: Dict
    fallback_visual: Optional[Dict] = None
    last_resort: Optional[Dict] = None
    text_overlay: Optional[Dict] = None
    transition_in: str = "fade_in"
    transition_out: str = "dissolve"
    mood: str = "neutral"
    notes: str = ""


@dataclass
class Segment:
    """A timeline segment (one or more media items covering a beat)."""
    segment_id: str
    beat_id: str
    narration: str
    start: float
    end: float
    items: List[Dict] = field(default_factory=list)
    mood: str = "neutral"
    color_grade: str = "default"


# ============================================================
# LIBRARY DATABASE (JSON-based, Phase 1)
# ============================================================

class LibraryDB:
    """JSON-based library database. Upgradable to SQLite later."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(LIBRARY_DIR / "library_root.json")
        self.data = self._load()

    def _load(self) -> Dict:
        if os.path.exists(self.db_path):
            with open(self.db_path, 'r') as f:
                return json.load(f)
        return {
            "version": "2.0",
            "last_updated": datetime.now().isoformat(),
            "total_videos": 0,
            "total_images": 0,
            "total_maps": 0,
            "total_graphics": 0,
            "niches": [],
            "entities": {},
            "entries": {}
        }

    def save(self):
        self.data["last_updated"] = datetime.now().isoformat()
        with open(self.db_path, 'w') as f:
            json.dump(self.data, f, indent=2)

    def add_entry(self, entry: ClipEntry):
        """Add a new clip/image to the library."""
        self.data["entries"][entry.id] = asdict(entry)
        self._update_indexes(entry)
        self._update_counts()
        self.save()

    def search(self, query: str,
               entity_filter: List[str] = None,
               type_filter: str = None,
               min_quality: str = "medium",
               context_filter: List[str] = None,
               action_filter: List[str] = None,
               strictness: str = "general") -> List[Dict]:
        """
        Search library with hard identity gates.

        Gate 1: Entity match (exact or downgrade)
        Gate 2: Action match (exact or downgrade)
        Gate 3: Context match (exact or downgrade)
        Gate 4: Quality gate
        Only THEN rank by relevance.
        """
        quality_rank = {"low": 0, "medium": 1, "high": 2}
        min_q = quality_rank.get(min_quality, 0)

        passed_gates = []

        for entry in self.data["entries"].values():
            # --- GATE 1: Entity ---
            if entity_filter:
                entity_match = self._entity_match(entry, entity_filter, strictness)
                if entity_match == "reject":
                    continue  # Wrong entity entirely
                entity_score = entity_match  # "exact"=3, "downgrade"=1

            # --- GATE 2: Action ---
            if action_filter:
                action_match = self._action_match(entry, action_filter)
                if action_match == "reject":
                    continue
                action_score = action_match

            # --- GATE 3: Context ---
            if context_filter:
                context_match = self._context_match(entry, context_filter)
                if context_match == "reject":
                    continue
                context_score = context_match

            # --- GATE 4: Quality ---
            if quality_rank.get(entry.get("quality", "medium"), 0) < min_q:
                continue

            # --- RANKING (after all gates pass) ---
            text_score = self._text_match(query, entry)
            total_score = text_score
            if entity_filter:
                total_score += entity_score
            if action_filter:
                total_score += action_score * 0.5
            if context_filter:
                total_score += context_score * 0.3

            # Penalty for overuse
            times_used = entry.get("times_used", 0)
            reuse_penalty = min(times_used * 0.2, 1.0)
            total_score -= reuse_penalty

            passed_gates.append({**entry, "score": total_score})

        passed_gates.sort(key=lambda x: x["score"], reverse=True)
        return passed_gates[:20]

    def _entity_match(self, entry: Dict, requested: List[str], strictness: str) -> str:
        """
        Hard entity gate.
        Returns: "exact" | "downgrade" | "reject"
        """
        entry_entities = [e.lower() for e in entry.get("entities", [])]

        for req in requested:
            req_lower = req.lower()

            # Exact match
            if req_lower in entry_entities:
                return "exact"

            # Partial match (downgrade for specific/general, reject for exact)
            for ent in entry_entities:
                if req_lower in ent or ent in req_lower:
                    if strictness in ["exact", "specific"]:
                        return "reject"
                    else:
                        return "downgrade"

        return "reject"

    def _action_match(self, entry: Dict, requested: List[str]) -> str:
        """Action match gate."""
        entry_actions = [a.lower() for a in entry.get("actions", [])]
        for req in requested:
            req_lower = req.lower()
            for act in entry_actions:
                if req_lower in act or act in req_lower:
                    return "exact"
        return "reject"

    def _context_match(self, entry: Dict, requested: List[str]) -> str:
        """Context/environment match gate."""
        entry_env = [e.lower() for e in entry.get("environment", [])]
        for req in requested:
            req_lower = req.lower()
            for env in entry_env:
                if req_lower in env or env in req_lower:
                    return "exact"
        return "reject"

    def _text_match(self, query: str, entry: Dict) -> float:
        """Simple text relevance score."""
        query_words = set(query.lower().split())
        desc_words = set(entry.get("description", "").lower().split())
        topic_words = set(entry.get("topic", "").lower().split())
        tag_words = set()
        for tag in entry.get("entities", []) + entry.get("actions", []):
            tag_words.update(tag.lower().split())

        overlap_desc = len(query_words & desc_words)
        overlap_topic = len(query_words & topic_words)
        overlap_tags = len(query_words & tag_words)

        return overlap_desc * 0.3 + overlap_topic * 0.5 + overlap_tags * 1.0

    def _update_indexes(self, entry: ClipEntry):
        """Update entity/action indexes."""
        for entity in entry.entities:
            idx = self.data.setdefault("entity_index", {})
            idx.setdefault(entity.lower(), []).append(entry.id)

        for action in entry.actions:
            idx = self.data.setdefault("action_index", {})
            idx.setdefault(action.lower(), []).append(entry.id)

    def _update_counts(self):
        """Update total counts."""
        videos = sum(1 for e in self.data["entries"].values() if e.get("type") == "video")
        images = sum(1 for e in self.data["entries"].values() if e.get("type") == "image")
        maps = sum(1 for e in self.data["entries"].values() if e.get("type") == "map")
        graphics = sum(1 for e in self.data["entries"].values() if e.get("type") == "graphic")

        self.data["total_videos"] = videos
        self.data["total_images"] = images
        self.data["total_maps"] = maps
        self.data["total_graphics"] = graphics

    def get_coverage(self) -> Dict:
        """Get coverage statistics."""
        entities = {}
        for entry in self.data["entries"].values():
            for entity in entry.get("entities", []):
                if entity not in entities:
                    entities[entity] = {"clips": 0, "duration": 0.0}
                entities[entity]["clips"] += 1
                entities[entity]["duration"] += entry.get("duration", 0)

        return {
            "total_entries": len(self.data["entries"]),
            "videos": self.data["total_videos"],
            "images": self.data["total_images"],
            "maps": self.data["total_maps"],
            "graphics": self.data["total_graphics"],
            "unique_entities": len(entities),
            "entity_details": entities
        }


# ============================================================
# QUEUE MANAGER
# ============================================================

class QueueManager:
    """Manages batch processing queue."""

    def __init__(self, queue_file: str = None):
        self.queue_file = queue_file or str(QUEUE_DIR / "jobs.json")
        self.jobs: List[Job] = []
        self.current_format = 1

    def load_queue(self):
        """Load jobs from JSON."""
        if not os.path.exists(self.queue_file):
            return

        with open(self.queue_file, 'r') as f:
            data = json.load(f)

        self.jobs = []
        for j in data.get("jobs", []):
            status = JobStatus(j.get("status", "queued"))
            self.jobs.append(Job(
                id=j["id"],
                script=j["script"],
                audio=j["audio"],
                clue=j.get("clue"),
                niche=j["niche"],
                title=j["title"],
                status=status,
                progress=j.get("progress", 0.0),
                error=j.get("error"),
                output=j.get("output"),
                started_at=j.get("started_at"),
                finished_at=j.get("finished_at"),
                format_variant=j.get("format_variant", "F1")
            ))

    def save_queue(self):
        """Save jobs to JSON."""
        data = {
            "queue_version": "1.0",
            "total_jobs": len(self.jobs),
            "completed": sum(1 for j in self.jobs if j.status == JobStatus.DONE),
            "failed": sum(1 for j in self.jobs if j.status == JobStatus.ERROR),
            "remaining": sum(1 for j in self.jobs if j.status == JobStatus.QUEUED),
            "jobs": [self._job_to_dict(j) for j in self.jobs]
        }

        with open(self.queue_file, 'w') as f:
            json.dump(data, f, indent=2)

    def _job_to_dict(self, job: Job) -> Dict:
        d = {
            "id": job.id,
            "script": job.script,
            "audio": job.audio,
            "clue": job.clue,
            "niche": job.niche,
            "title": job.title,
            "status": job.status.value,
            "progress": job.progress,
            "error": job.error,
            "output": job.output,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "format_variant": job.format_variant
        }
        return {k: v for k, v in d.items() if v is not None}

    def preflight(self) -> Tuple[List[Job], List[Job], List[Job]]:
        """
        Pre-flight all jobs: check inputs, classify.
        Returns: (ready_jobs, gap_jobs, blocked_jobs)

        Auto-fixable gaps:
        - Missing audio (can generate via TTS)
        - Missing clue script (can generate via Claude)
        - Missing niche pack (will use default)

        Blocked (cannot proceed):
        - Missing script file
        """
        ready = []
        gaps = []
        blocked = []

        for job in self.jobs:
            issues = []
            auto_fixable = []

            # Check script (REQUIRED — cannot auto-generate)
            if not os.path.exists(job.script):
                issues.append(f"Script not found: {job.script}")

            # Check audio (auto-fixable with TTS)
            if not os.path.exists(job.audio):
                auto_fixable.append(f"Audio not found: {job.audio} (will generate TTS)")

            # Check clue script (auto-fixable with Claude)
            if not job.clue or not os.path.exists(job.clue):
                auto_fixable.append("Clue script missing (can auto-generate)")

            # Check niche pack (auto-fixable with default)
            if not os.path.exists(job.niche):
                auto_fixable.append(f"Niche pack not found: {job.niche} (will use default)")
                job.niche = str(PACKS_DIR / "defence.yaml")  # Default fallback

            if not issues and not auto_fixable:
                ready.append(job)
            elif issues:
                # Hard failure — cannot proceed
                job.status = JobStatus.BLOCKED
                job.error = "; ".join(issues + auto_fixable)
                blocked.append(job)
            else:
                # Only auto-fixable issues
                job.error = "; ".join(auto_fixable)
                gaps.append(job)

        return ready, gaps, blocked

    def run_queue(self, resume: bool = True):
        """Process all jobs serially."""
        self.load_queue()

        ready, gaps, blocked = self.preflight()

        print(f"\n{'='*60}")
        print(f"QUEUE: {len(self.jobs)} jobs")
        print(f"  Ready: {len(ready)}")
        print(f"  Gaps (auto-fixable): {len(gaps)}")
        print(f"  Blocked: {len(blocked)}")
        print(f"  Skipping done: {sum(1 for j in self.jobs if j.status == JobStatus.DONE and resume)}")
        print(f"{'='*60}\n")

        all_process = ready + gaps

        for i, job in enumerate(all_process):
            # Skip completed if resuming
            if resume and job.status == JobStatus.DONE:
                print(f"[{i+1}/{len(all_process)}] SKIP (done): {job.title}")
                continue

            # Assign format variant
            job.format_variant = f"F{(self.current_format % 10) + 1}"
            self.current_format += 1

            print(f"\n{'='*60}")
            print(f"[{i+1}/{len(all_process)}] PROCESSING: {job.title}")
            print(f"  Script: {job.script}")
            print(f"  Audio:  {job.audio}")
            print(f"  Niche:  {job.niche}")
            print(f"  Format: {job.format_variant}")
            print(f"{'='*60}\n")

            job.status = JobStatus.RUNNING
            job.started_at = datetime.now().isoformat()
            self.save_queue()

            try:
                from CODE.demandscout_core import process_job
                result = process_job(job)
                job.status = JobStatus.DONE
                job.output = result
                print(f"\n  ✓ DONE: {result}")

            except Exception as e:
                job.status = JobStatus.ERROR
                job.error = str(e)
                print(f"\n  ✗ ERROR: {e}")

            job.finished_at = datetime.now().isoformat()
            self.save_queue()

        self._print_summary()

    def _print_summary(self):
        """Print queue summary."""
        done = sum(1 for j in self.jobs if j.status == JobStatus.DONE)
        error = sum(1 for j in self.jobs if j.status == JobStatus.ERROR)
        blocked = sum(1 for j in self.jobs if j.status == JobStatus.BLOCKED)

        print(f"\n{'='*60}")
        print(f"QUEUE COMPLETE")
        print(f"  Done:   {done}")
        print(f"  Error:  {error}")
        print(f"  Blocked: {blocked}")
        print(f"  Total:  {len(self.jobs)}")
        print(f"{'='*60}\n")

    def add_job(self, script: str, audio: str, niche: str, title: str,
                clue: str = None) -> Job:
        """Add a new job to the queue."""
        self.load_queue()

        job_id = f"J{len(self.jobs) + 1:03d}"
        job = Job(
            id=job_id,
            script=script,
            audio=audio,
            clue=clue,
            niche=niche,
            title=title
        )
        self.jobs.append(job)
        self.save_queue()
        return job

    def create_queue_from_folder(self, scripts_dir: str, audio_dir: str,
                                  niche: str) -> List[Job]:
        """Create queue from folders of scripts and audio files."""
        scripts_path = Path(scripts_dir)
        audio_path = Path(audio_dir)

        added = []
        for script_file in sorted(scripts_path.glob("*.txt")):
            stem = script_file.stem
            audio_file = audio_path / f"{stem}.mp3"

            if audio_file.exists():
                job = self.add_job(
                    script=str(script_file),
                    audio=str(audio_file),
                    niche=niche,
                    title=stem.replace("_", " ").title()
                )
                added.append(job)
                print(f"  + {job.title}")
            else:
                print(f"  ! No audio for: {script_file.name}")

        return added


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="ProClip Engine — Documentary Video Automation"
    )
    parser.add_argument("--script", help="Path to narration script")
    parser.add_argument("--audio", help="Path to narration audio")
    parser.add_argument("--clue", help="Path to clue script (optional, auto-generated)")
    parser.add_argument("--niche", help="Path to niche pack YAML")
    parser.add_argument("--title", help="Video title")
    parser.add_argument("--queue", help="Path to queue JSON file")
    parser.add_argument("--overnight", action="store_true", help="Run overnight mode")
    parser.add_argument("--add", action="store_true", help="Add to queue instead of processing")
    parser.add_argument("--queue-from", nargs=2, metavar=("SCRIPTS_DIR", "AUDIO_DIR"),
                        help="Create queue from folders")
    parser.add_argument("--status", action="store_true", help="Show queue status")
    parser.add_argument("--library", action="store_true", help="Show library stats")

    args = parser.parse_args()

    if args.library:
        db = LibraryDB()
        stats = db.get_coverage()
        print(json.dumps(stats, indent=2))
        return

    if args.status:
        qm = QueueManager()
        qm.load_queue()
        done = sum(1 for j in qm.jobs if j.status == JobStatus.DONE)
        error = sum(1 for j in qm.jobs if j.status == JobStatus.ERROR)
        queued = sum(1 for j in qm.jobs if j.status == JobStatus.QUEUED)
        print(f"Queue: {len(qm.jobs)} jobs")
        print(f"  Done: {done}")
        print(f"  Error: {error}")
        print(f"  Queued: {queued}")
        return

    if args.overnight:
        qm = QueueManager()
        print("🌙 Overnight mode activated")
        while True:
            qm.load_queue()
            remaining = sum(1 for j in qm.jobs if j.status == JobStatus.QUEUED)
            if remaining == 0:
                print("  Queue empty. Sleeping 1 hour...")
                time.sleep
                continue
            print(f"  Processing {remaining} jobs...")
            qm.run_queue(resume=True)
            remaining = sum(1 for j in qm.jobs if j.status == JobStatus.QUEUED)
            if remaining == 0:
                print("  All done. Sleeping 1 hour...")
                time.sleep

    elif args.queue_from:
        qm = QueueManager()
        scripts_dir, audio_dir = args.queue_from
        niche = args.niche or str(PACKS_DIR / "defence.yaml")
        print(f"Creating queue from {scripts_dir} + {audio_dir}")
        added = qm.create_queue_from_folder(scripts_dir, audio_dir, niche)
        print(f"\nAdded {len(added)} jobs to queue")

    elif args.add and args.script:
        qm = QueueManager()
        niche = args.niche or str(PACKS_DIR / "defence.yaml")
        job = qm.add_job(
            script=args.script,
            audio=args.audio or "",
            niche=niche,
            title=args.title or Path(args.script).stem,
            clue=args.clue
        )
        print(f"Added job {job.id}: {job.title}")

    elif args.queue:
        qm = QueueManager(args.queue)
        qm.run_queue()

    elif args.script and args.audio and args.niche:
        # Single video mode
        job = Job(
            id="J001",
            script=args.script,
            audio=args.audio,
            clue=args.clue,
            niche=args.niche,
            title=args.title or Path(args.script).stem
        )
        print(f"Processing: {job.title}")
        try:
            from CODE.demandscout_core import process_job
            result = process_job(job)
            print(f"✓ Done: {result}")
        except ImportError:
            print("Core module not yet implemented. Coming soon.")
        except Exception as e:
            print(f"✗ Error: {e}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
