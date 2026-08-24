#!/usr/bin/env python3
"""
schemas.py — the versioned contracts every stage agrees on.

Kept deliberately lean (dataclasses + validate + JSON), not a 30-table ORM. The point is a stable
SHAPE so stages don't drift:

  ShotRequirement   one visual need inside a beat (a beat can have several)
  Beat              a verbatim span of the approved narration + its shot requirements
  VisualPlan        the whole ordered list of beats for one video (Claude's clue script)
  DemandTicket      a coverage GAP: "this shot is missing / short", merged across a batch
  ProjectManifest   the IDs + paths that isolate one project (chat is NOT state)

Enums match catalog_db so a ShotRequirement maps straight onto Catalog.search().
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

SCHEMA_VERSION = "plan-v1"

ROLES = {"literal", "evidence", "context", "atmospheric", "graphic"}
MEDIA = {"video", "image", "graphic", "map", "text"}
COMPOSITIONS = {"single", "comparison", "split_screen", "price_card", "document", "map",
                "timeline", "montage"}
STRICTNESS = {"exact", "specific", "general", "loose"}


class ValidationError(ValueError):
    pass


@dataclass
class ShotRequirement:
    role: str = "context"
    media: str = "video"
    query_text: str = ""
    required_all: list = field(default_factory=list)   # canonical entity ids
    required_any: list = field(default_factory=list)
    forbidden: list = field(default_factory=list)
    era: list | None = None                            # [from, to] or None
    min_seconds: float = 2.0
    max_seconds: float = 7.0                            # copyright cap (operator posture)
    composition: str = "single"
    strictness: str = "specific"
    # fallback chain if the primary media isn't found (explicit, never accidental)
    fallbacks: list = field(default_factory=lambda: ["image", "graphic", "text"])

    def validate(self):
        if self.role not in ROLES:
            raise ValidationError(f"role {self.role!r} not in {ROLES}")
        if self.media not in MEDIA:
            raise ValidationError(f"media {self.media!r} not in {MEDIA}")
        if self.composition not in COMPOSITIONS:
            raise ValidationError(f"composition {self.composition!r} not in {COMPOSITIONS}")
        if self.strictness not in STRICTNESS:
            raise ValidationError(f"strictness {self.strictness!r} not in {STRICTNESS}")
        if self.era is not None and (len(self.era) != 2 or self.era[0] > self.era[1]):
            raise ValidationError(f"era must be [from,to] with from<=to, got {self.era}")
        if self.min_seconds > self.max_seconds:
            raise ValidationError("min_seconds > max_seconds")
        for f in self.fallbacks:
            if f not in MEDIA:
                raise ValidationError(f"fallback {f!r} not in {MEDIA}")
        return self


@dataclass
class Beat:
    beat_id: str
    narration: str                       # VERBATIM span of the approved narration
    start_ms: int | None = None          # from word timestamps (filled after TTS)
    end_ms: int | None = None
    shots: list = field(default_factory=list)   # list[ShotRequirement]

    def validate(self):
        if not self.narration.strip():
            raise ValidationError(f"beat {self.beat_id} has empty narration")
        if self.start_ms is not None and self.end_ms is not None and self.start_ms >= self.end_ms:
            raise ValidationError(f"beat {self.beat_id} start>=end")
        if not self.shots:
            raise ValidationError(f"beat {self.beat_id} has no shots")
        for s in self.shots:
            s.validate()
        return self


@dataclass
class VisualPlan:
    project_id: str
    narration_hash: str                  # locks the plan to the approved narration (intake.py)
    format_pack: str = ""
    language: str = "en"
    beats: list = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def validate(self):
        if not self.narration_hash:
            raise ValidationError("VisualPlan must carry the approved narration_hash")
        seen = set()
        for b in self.beats:
            if b.beat_id in seen:
                raise ValidationError(f"duplicate beat_id {b.beat_id}")
            seen.add(b.beat_id)
            b.validate()
        return self

    # ---- (de)serialization -------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict) -> "VisualPlan":
        beats = []
        for b in d.get("beats", []):
            shots = [ShotRequirement(**s) for s in b.get("shots", [])]
            beats.append(Beat(beat_id=b["beat_id"], narration=b["narration"],
                              start_ms=b.get("start_ms"), end_ms=b.get("end_ms"), shots=shots))
        return VisualPlan(project_id=d["project_id"], narration_hash=d["narration_hash"],
                          format_pack=d.get("format_pack", ""), language=d.get("language", "en"),
                          beats=beats, schema_version=d.get("schema_version", SCHEMA_VERSION))

    def save(self, path: str | Path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
                              encoding="utf-8")

    @staticmethod
    def load(path: str | Path) -> "VisualPlan":
        return VisualPlan.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass
class DemandTicket:
    ticket_id: str
    query_text: str
    media: str = "video"
    required_all: list = field(default_factory=list)
    required_any: list = field(default_factory=list)
    era: list | None = None
    # diversity targets (coverage is NOT binary — see FOUNDATION §10)
    needed_variants: int = 1
    needed_seconds: float = 0.0
    needed_sources: int = 1
    from_beats: list = field(default_factory=list)     # which beats/projects want this
    status: str = "open"                               # open | partial | filled

    def merge(self, other: "DemandTicket"):
        """Fold a duplicate requirement in: raise the diversity targets, union the beats."""
        self.needed_variants = max(self.needed_variants, other.needed_variants)
        self.needed_seconds = max(self.needed_seconds, other.needed_seconds)
        self.needed_sources = max(self.needed_sources, other.needed_sources)
        self.from_beats = sorted(set(self.from_beats) | set(other.from_beats))
        return self


@dataclass
class ProjectManifest:
    project_id: str
    workspace_id: str = "default"
    channel_id: str = ""
    niche: str = ""
    format_pack: str = ""
    style: str = "clean_doc"
    languages: list = field(default_factory=lambda: ["en"])
    batch_id: str = ""
    title: str = ""

    def validate(self):
        if not self.project_id:
            raise ValidationError("project_id is required (chat name is not state)")
        return self

    def save(self, path: str | Path):
        Path(path).write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False),
                              encoding="utf-8")

    @staticmethod
    def load(path: str | Path) -> "ProjectManifest":
        return ProjectManifest(**json.loads(Path(path).read_text(encoding="utf-8")))
