#!/usr/bin/env python3
"""
coverage.py — the coverage planner. Maps each visual requirement onto the library and decides
reuse-vs-gap, diversity-aware (not binary hit/miss). Missing capacity becomes DemandTickets that
merge across a whole batch of scripts, so a shot 3 scripts want is acquired + cataloged ONCE.

Statuses per requirement:
  GENERATE        we make it (chart/map/price card/title) — no acquisition
  EXACT_REUSE     library already has enough distinct clips + seconds
  ACCEPTABLE_REUSE library has usable but not exact-strictness matches
  PARTIAL         some coverage, but short on variants/seconds -> ticket for the shortfall
  COMPOSITE       a comparison/split-screen needing >1 entity assembled from parts
  ACQUIRE         nothing usable -> ticket for the full need

Coverage is DIVERSITY-AWARE: if N beats want the same shot, needed_variants ~ N so 10 videos
don't reuse one forecourt clip 10 times (FOUNDATION §10).
"""
from __future__ import annotations
import re
from schemas import VisualPlan, DemandTicket

GENERATED_MEDIA = {"graphic", "map", "text"}
GENERATED_COMPOSITIONS = {"price_card", "timeline", "document"}


def _sig(media: str, required_all, required_any, query_text: str, era) -> str:
    q = re.sub(r"\s+", " ", (query_text or "").lower()).strip()
    ra = ",".join(sorted(required_all or []))
    an = ",".join(sorted(required_any or []))
    e = f"{era[0]}-{era[1]}" if era else ""
    return f"{media}|{ra}|{an}|{e}|{q}"


def _clip_seconds(asset: dict, shot) -> float:
    if asset.get("start_ms") is not None and asset.get("end_ms") is not None:
        return min((asset["end_ms"] - asset["start_ms"]) / 1000.0, shot.max_seconds)
    return shot.min_seconds          # a still holds for min_seconds under Ken Burns


def _is_generated(shot) -> bool:
    return shot.media in GENERATED_MEDIA or shot.composition in GENERATED_COMPOSITIONS


def plan_coverage(catalog, plan: VisualPlan, *, scope_collections=None, channel=None) -> dict:
    """Return {requirements: [...], tickets: {sig: DemandTicket}} for one plan.
    Diversity need per unique shot signature = how many beats want it."""
    # 1) group shots by signature to compute diversity need
    groups: dict[str, dict] = {}
    for b in plan.beats:
        for i, shot in enumerate(b.shots):
            if _is_generated(shot):
                continue
            sig = _sig(shot.media, shot.required_all, shot.required_any, shot.query_text, shot.era)
            g = groups.setdefault(sig, {"shot": shot, "beats": [], "need_seconds": 0.0})
            g["beats"].append(b.beat_id)
            g["need_seconds"] += shot.min_seconds

    tickets: dict[str, DemandTicket] = {}
    reqs = []

    for b in plan.beats:
        for i, shot in enumerate(b.shots):
            base = {"beat_id": b.beat_id, "shot_index": i, "media": shot.media,
                    "query": shot.query_text}
            if _is_generated(shot):
                reqs.append({**base, "status": "GENERATE", "candidates": 0})
                continue

            sig = _sig(shot.media, shot.required_all, shot.required_any, shot.query_text, shot.era)
            g = groups[sig]
            need_variants = len(g["beats"])
            need_seconds = g["need_seconds"]

            cands = catalog.search(
                query_text=shot.query_text or None, type=shot.media,
                required_all=shot.required_all, required_any=shot.required_any,
                forbidden=shot.forbidden, era=tuple(shot.era) if shot.era else None,
                scope_collections=scope_collections, top_k=50)
            have_variants = len(cands)
            have_seconds = sum(_clip_seconds(c, shot) for c in cands)

            composite = shot.composition in {"comparison", "split_screen"} and \
                len(shot.required_all) >= 2

            if have_variants >= need_variants and have_seconds >= need_seconds:
                status = "EXACT_REUSE" if shot.strictness in ("exact", "specific") else "ACCEPTABLE_REUSE"
            elif have_variants > 0:
                status = "PARTIAL"
            else:
                status = "ACQUIRE"
            if composite:
                status = "COMPOSITE"

            if status in ("PARTIAL", "ACQUIRE", "COMPOSITE"):
                short_v = max(0, need_variants - have_variants)
                short_s = max(0.0, need_seconds - have_seconds)
                t = tickets.get(sig)
                new = DemandTicket(
                    ticket_id=f"DT_{abs(hash(sig)) % 10**8:08d}",
                    query_text=shot.query_text, media=shot.media,
                    required_all=list(shot.required_all), required_any=list(shot.required_any),
                    era=list(shot.era) if shot.era else None,
                    needed_variants=max(1, short_v or need_variants),
                    needed_seconds=short_s or need_seconds,
                    needed_sources=min(max(1, need_variants), 3),
                    from_beats=[b.beat_id], status="open")
                tickets[sig] = t.merge(new) if t else new

            reqs.append({**base, "status": status, "candidates": have_variants,
                         "have_seconds": round(have_seconds, 1),
                         "need_variants": need_variants, "need_seconds": round(need_seconds, 1),
                         "ticket": tickets.get(sig).ticket_id if sig in tickets else None})

    return {"requirements": reqs, "tickets": tickets}


def plan_coverage_batch(catalog, plans: list[VisualPlan], *, scope_collections=None) -> dict:
    """Run coverage for a whole batch and MERGE duplicate tickets across all scripts.
    This is the step that saves scrape + Gemini cost across a 10-script batch."""
    all_reqs = []
    merged: dict[str, DemandTicket] = {}
    for plan in plans:
        r = plan_coverage(catalog, plan, scope_collections=scope_collections)
        all_reqs.append({"project_id": plan.project_id, "requirements": r["requirements"]})
        for sig, t in r["tickets"].items():
            merged[sig] = merged[sig].merge(t) if sig in merged else t
    return {"per_project": all_reqs, "tickets": list(merged.values())}


def summarize(cov: dict) -> dict:
    counts: dict[str, int] = {}
    for r in cov["requirements"]:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"status_counts": counts, "open_tickets": len(cov["tickets"])}
