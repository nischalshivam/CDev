#!/usr/bin/env python3
"""
demandscout_core.py — Core processing pipeline for ProClip Engine

Pipeline: Script → Clue Script → Assets → Timeline → Render
"""

import os
import sys
import json
import re
import time
import shutil
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

# Setup path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from demandscout import (
    Job, Beat, LibraryDB,
    SCRIPTS_DIR, AUDIO_DIR, CLUES_DIR, OUTPUT_DIR,
    TIMELINES_DIR, PACKS_DIR, PROMPTS_DIR, LOGS_DIR,
    RAW_DIR, CLIPS_DIR
)

# Setup logging
log = logging.getLogger("ProClip.core")

# ============================================================
# TTS IMPORT (lazy — edge-tts is optional but recommended)
# ============================================================

def _get_tts_engine():
    """Lazy import of TTS engine."""
    try:
        from CODE.tts import TTSEngine
        return TTSEngine(output_dir=str(AUDIO_DIR))
    except ImportError:
        log.warning("edge-tts not available — TTS generation disabled")
        return None

# ============================================================
# SCRAPER IMPORT (lazy)
# ============================================================

def _get_scraper():
    """Lazy import of scraper."""
    try:
        from CODE.scraper import ScraperEngine
        return ScraperEngine(output_dir=str(RAW_DIR))
    except ImportError:
        log.warning("Scraper module not available")
        return None

# ============================================================
# RENDERER IMPORT (lazy)
# ============================================================

def _get_renderer():
    """Lazy import of renderer."""
    try:
        from CODE.renderer import RendererEngine
        return RendererEngine()
    except ImportError:
        log.warning("Renderer module not available")
        return None

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _load_script(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read().strip()


def _load_yaml(path: str) -> Dict:
    try:
        import yaml
        with open(path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log.error(f"Failed to load YAML {path}: {e}")
        return {}


def _extract_json(text: str) -> Dict:
    """Extract JSON from Claude API response (handles markdown wrapping)."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON in markdown code block
    match = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find first { to last }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from response: {text[:200]}")


# ============================================================
# CLUE SCRIPT GENERATION
# ============================================================

def generate_clue_script(script_text: str, niche_config: Dict, title: str) -> Dict:
    """
    Generate Clue Script using Claude API.

    The Clue Script breaks narration into timed beats with asset requirements.
    """

    # Load prompt
    prompt_path = PROMPTS_DIR / "CLUE_SCRIPT_PROMPT.md"
    if prompt_path.exists():
        with open(prompt_path, 'r') as f:
            base_prompt = f.read()
    else:
        base_prompt = _default_clue_script_prompt()

    # Build input
    input_text = f"""Niche: {niche_config.get('name', 'unknown')}
Video Title: {title}
Style: {niche_config.get('default_style', 'clean_doc')}

Narration Script:
{script_text}

Generate the Clue Script JSON for this documentary video."""

    try:
        import anthropic
        client = anthropic.Anthropic()

        message = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=4096,
            temperature=0.3,
            messages=[{"role": "user", "content": f"{base_prompt}\n\n{input_text}"}]
        )

        response_text = message.content[0].text
        clue_script = _extract_json(response_text)

        # Add metadata
        clue_script["script_id"] = f"S{abs(hash(script_text)) % 1000:03d}"
        clue_script["niche"] = niche_config.get('name', 'unknown')
        clue_script["title"] = title
        clue_script["style"] = niche_config.get('default_style', 'clean_doc')
        clue_script["estimated_duration"] = len(script_text.split()) * 0.15
        clue_script["generated_at"] = datetime.now().isoformat()

        return clue_script

    except ImportError:
        log.warning("anthropic not installed — using placeholder")
        return _placeholder_clue_script(script_text, title)
    except Exception as e:
        log.error(f"Clue Script generation failed: {e}")
        return _placeholder_clue_script(script_text, title)


def _default_clue_script_prompt() -> str:
    return """You are a documentary video production AI. Your job is to convert a narration script into a structured "Clue Script" — a production blueprint that tells the engine what visual assets to find and how to assemble them.

Break the script into narration beats. Each beat should have:
- narration_verbatim: The exact text spoken
- start_time: When this beat starts (seconds)
- end_time: When this beat ends (seconds)
- entities: Specific objects/people/places mentioned
- visual_role: "literal" (show the actual thing) / "context" (related B-roll) / "evidence" (map/document) / "atmospheric"
- asset_type: "video" / "image" / "text_card" / "lower_third"
- search_terms: Keywords for finding this asset
- mood: neutral/curious/tension/dark/tragic/emotional/hopeful/triumphant/action/epic

Respond with ONLY valid JSON, no markdown code blocks.
Format: {"beats": [...], "title": "...", "total_duration": number}"""


def _placeholder_clue_script(script_text: str, title: str) -> Dict:
    """Generate a basic placeholder Clue Script when API is unavailable."""

    sentences = re.split(r'(?<=[.!?])\s+', script_text.strip())
    beats = []
    current_time = 0.0

    for i, sentence in enumerate(sentences):
        if not sentence or len(sentence) < 5:
            continue

        words = len(sentence.split())
        duration = words * 0.15 + 1.5  # ~150ms per word + pause

        beats.append({
            "beat_id": f"B{i + 1:03d}",
            "narration_verbatim": sentence.strip(),
            "start_time": round(current_time, 2),
            "end_time": round(current_time + duration, 2),
            "duration": round(duration, 2),
            "entities": _extract_entities(sentence),
            "visual_role": "literal",
            "asset_type": "text_card",
            "search_terms": sentence.strip()[:50],
            "mood": "neutral",
            "matched_assets": None,
            "media_type": "text_card"
        })

        current_time += duration + 0.3  # Small gap between beats

    return {
        "script_id": f"S{abs(hash(script_text)) % 1000:03d}",
        "title": title,
        "beats": beats,
        "total_duration": round(current_time, 2),
        "estimated_duration": round(current_time, 2),
        "niche": "unknown",
        "style": "clean_doc",
        "generated_at": datetime.now().isoformat()
    }


def _extract_entities(text: str) -> List[str]:
    """Simple entity extraction from text (keywords/capitalized words)."""
    entities = []

    # Capitalized multi-word entities
    caps = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
    entities.extend(caps[:5])

    # Known entity types (military, vehicles, countries)
    military_terms = [
        "Boxer", "Apache", "Seahawk", "ASLAV", "Abrams", "Bradley",
        "F-35", "F-22", "Rafale", "T-90", "Patriot", "Iron Dome",
        "NATO", "Army", "Navy", "Air Force", "Rheinmetall", "Boeing",
        "Lockheed", "BAE Systems", "Pentagon"
    ]
    for term in military_terms:
        if term.lower() in text.lower():
            entities.append(term)

    return list(set(entities))[:8]


# ============================================================
# ASSET RETRIEVAL
# ============================================================

def retrieve_assets_for_beat(beat: Dict, library: LibraryDB) -> Dict:
    """
    Find assets for a single beat.
    Searches library first, returns info about whether scraping is needed.
    """
    entities = beat.get("entities", [])
    search_terms = beat.get("search_terms", "")
    asset_type = beat.get("asset_type", "text_card")
    strictness = beat.get("strictness", "general")

    # Skip text cards — no assets needed
    if asset_type == "text_card":
        return {"media_type": "text_card", "needs_scraping": False}

    # Search library (BUG-FIX: param is entity_filter, not entities; top_k now supported)
    results = library.search(
        search_terms,
        entity_filter=entities or None,
        strictness=strictness,
        top_k=3,
    )

    if results:
        best = results[0]
        return {
            "media_type": best.get("type", "text_card"),
            "matched_asset": best,
            "needs_scraping": False,
            "source": "library"
        }

    # Nothing in library — needs scraping
    return {
        "media_type": "text_card",  # Fallback
        "needs_scraping": True,
        "search_terms": search_terms,
        "entities": entities,
        "asset_type": asset_type,
        "source": "scrape_required"
    }


# ============================================================
# TIMELINE BUILDING
# ============================================================

def build_timeline(beats: List[Dict], job: Job, style_config: Dict) -> Dict:
    """
    Build render timeline from beats + matched assets.
    """
    segments = []
    current_time = 0.0

    for beat in beats:
        narration = beat.get("narration_verbatim", "")
        duration = beat.get("duration", 5.0)
        media_type = beat.get("media_type", "text_card")
        matched = beat.get("matched_assets")

        segment = {
            "beat_id": beat.get("beat_id", "unknown"),
            "narration": narration,
            "start": round(current_time, 2),
            "end": round(current_time + duration, 2),
            "duration": round(duration, 2),
            "media_type": media_type,
            "mood": beat.get("mood", "neutral"),
        }

        if matched:
            segment["asset"] = matched
            segment["motion"] = _assign_motion(matched, beat.get("mood", "neutral"))
            segment["transition"] = "cut"

        segments.append(segment)
        current_time += duration

    return {
        "job_id": job.id,
        "title": job.title,
        "segments": segments,
        "duration_seconds": round(current_time, 2),
        "audio_path": job.audio,
        "style_pack": style_config.get("name", "clean_doc"),
        "resolution": "1920x1080",
        "fps": 30
    }


def _assign_motion(asset: Dict, mood: str) -> str:
    """Assign motion effect based on asset quality and mood."""
    if mood in ("tension", "action", "epic"):
        return "push_in_slow"
    elif mood in ("hopeful", "triumphant"):
        return "pan_right"
    elif asset.get("quality") == "high":
        return "push_in_slow"
    return "static"


# ============================================================
# RENDERING
# ============================================================

def render_video(timeline: Dict, job: Job, output_path: str) -> str:
    """
    Render final video using FFmpeg.

    For now: produces a working MP4 with audio + text overlays.
    Full clip-based rendering comes after library is populated.
    """
    renderer = _get_renderer()
    if not renderer:
        raise RuntimeError("Renderer module not available")

    segments = timeline.get("segments", [])
    audio_path = timeline.get("audio_path", "")

    # Convert segments to TimelineItem objects
    from CODE.renderer import TimelineItem, RenderJob

    timeline_items = []
    for seg in segments:
        item = TimelineItem(
            file_path=seg.get("asset", {}).get("file_path", ""),
            item_type=seg.get("media_type", "text_card"),
            start_time=seg["start"],
            duration=seg["duration"],
            text_overlay=seg.get("narration", "")[:150],
            text_position="bottom",
            motion=seg.get("motion", "static")
        )
        timeline_items.append(item)

    render_job = RenderJob(
        job_id=job.id,
        title=job.title,
        output_path=output_path,
        timeline=timeline_items,
        audio_path=audio_path
    )

    return renderer.render(render_job)


# ============================================================
# TTS GENERATION
# ============================================================

def generate_narration_audio(script_text: str, output_name: str = None) -> Optional[str]:
    """Generate narration audio from script using edge-tts."""
    tts = _get_tts_engine()
    if not tts:
        return None

    try:
        audio_path = tts.generate_from_script(script_text, output_name=output_name)
        return str(audio_path)
    except Exception as e:
        log.error(f"TTS generation failed: {e}")
        return None


def generate_beat_audio(beats: List[Dict], output_prefix: str) -> List[Dict]:
    """Generate narration audio for each beat individually."""
    tts = _get_tts_engine()
    if not tts:
        return []

    return tts.generate_from_beats(beats, output_prefix=output_prefix)


# ============================================================
# MAIN PIPELINE
# ============================================================

def process_job(job: Job) -> str:
    """
    Process a single production job through the complete pipeline.

    Pipeline:
    1. Load inputs (script, niche config)
    2. Check/generate audio (TTS if missing)
    3. Generate Clue Script (break into beats)
    4. Search library for assets per beat
    5. Build timeline
    6. Render video

    Returns: Path to output MP4 file
    """
    log.info(f"=== Processing: {job.title} ===")
    start_time = time.time()

    try:
        # ==========================================
        # STEP 1: LOAD INPUTS
        # ==========================================
        log.info("Step 1/6: Loading inputs")
        job.progress = 5.0

        script_text = _load_script(job.script)
        niche_config = _load_yaml(job.niche)

        log.info(f"  Script: {len(script_text)} chars")
        log.info(f"  Niche: {niche_config.get('display_name', 'unknown')}")

        # ==========================================
        # STEP 2: AUDIO (TTS if missing)
        # ==========================================
        log.info("Step 2/6: Audio")
        job.progress = 10.0

        if job.audio and Path(job.audio).exists():
            log.info(f"  Using existing audio: {job.audio}")
        else:
            log.info("  No audio found — generating TTS narration...")
            audio_name = Path(job.script).stem
            audio_path = generate_narration_audio(script_text, output_name=audio_name)
            if audio_path:
                job.audio = audio_path
                log.info(f"  TTS generated: {audio_path}")
            else:
                log.warning("  TTS generation failed — rendering without narration")

        # ==========================================
        # STEP 3: CLUE SCRIPT
        # ==========================================
        log.info("Step 3/6: Generating Clue Script")
        job.progress = 20.0

        if job.clue and Path(job.clue).exists():
            with open(job.clue, 'r') as f:
                clue_script = json.load(f)
            log.info(f"  Loaded existing: {clue_script.get('script_id')}")
        else:
            clue_script = generate_clue_script(script_text, niche_config, job.title)

            # Save clue script
            clue_path = CLUES_DIR / f"{job.id}_clue.json"
            with open(clue_path, 'w') as f:
                json.dump(clue_script, f, indent=2)
            job.clue = str(clue_path)
            log.info(f"  Generated: {clue_script.get('script_id')} ({len(clue_script.get('beats', []))} beats)")

        # ==========================================
        # STEP 4: ASSET RETRIEVAL
        # ==========================================
        log.info("Step 4/6: Asset retrieval")
        job.progress = 30.0

        library = LibraryDB()
        beats = clue_script.get("beats", [])
        total_beats = len(beats)
        needs_scraping = []

        for i, beat in enumerate(beats):
            result = retrieve_assets_for_beat(beat, library)

            # Update beat with result
            beat["matched_assets"] = result.get("matched_asset")
            beat["media_type"] = result.get("media_type", "text_card")

            if result.get("needs_scraping"):
                needs_scraping.append(beat)

            job.progress = 30.0 + (40.0 * (i + 1) / total_beats)

        log.info(f"  Library coverage: {total_beats - len(needs_scraping)}/{total_beats} beats covered")

        # Scrape missing assets (if scraper available)
        if needs_scraping:
            scraper = _get_scraper()
            if scraper:
                log.info(f"  Scraping for {len(needs_scraping)} uncovered beats...")
                for beat in needs_scraping:
                    _try_scrape_for_beat(beat, scraper, library)

        # ==========================================
        # STEP 5: BUILD TIMELINE
        # ==========================================
        log.info("Step 5/6: Building timeline")
        job.progress = 80.0

        timeline = build_timeline(beats, job, niche_config)

        # Save timeline
        timeline_path = TIMELINES_DIR / f"{job.id}_timeline.json"
        with open(timeline_path, 'w') as f:
            json.dump(timeline, f, indent=2)

        log.info(f"  Timeline: {len(timeline['segments'])} segments, {timeline['duration_seconds']:.1f}s")

        # ==========================================
        # STEP 6: RENDER
        # ==========================================
        log.info("Step 6/6: Rendering video")
        job.progress = 85.0

        output_path = str(OUTPUT_DIR / f"{job.id}_{Path(job.script).stem}.mp4")

        try:
            final_path = render_video(timeline, job, output_path)
        except Exception as e:
            log.warning(f"Full render failed: {e}")
            log.info("  Falling back to audio-only MP3...")
            final_path = _render_audio_only(job)

        elapsed = time.time() - start_time
        log.info(f"=== DONE: {final_path} ({elapsed:.1f}s) ===")
        job.progress = 100.0

        return final_path

    except Exception as e:
        log.error(f"Job failed: {e}", exc_info=True)
        job.status_str = "error"
        raise


def _try_scrape_for_beat(beat: Dict, scraper, library: LibraryDB):
    """Try to scrape assets for a beat and add to library."""
    search_terms = beat.get("search_terms", "")
    entities = beat.get("entities", [])

    if not search_terms:
        return

    try:
        assets = scraper.scrape_for_topic(
            topic=search_terms,
            entities=entities,
            count=2,
            asset_type="both"
        )

        for asset in assets:
            # Add to library
            from demandscout import ClipEntry
            entry = ClipEntry(
                id=asset.id,
                type=asset.type,
                file=asset.file_path,
                source_type=asset.source_type,
                source_url=asset.source_url,
                topic=search_terms[:50],
                entities=entities,
                description=asset.description[:200],
                quality="medium",
                duration=asset.duration,
                width=asset.width,
                height=asset.height,
                license=asset.license
            )
            library.add_entry(entry)

            # Update beat with found asset
            beat["matched_assets"] = asdict(asset)
            beat["media_type"] = asset.type
            log.info(f"    Scraped: {asset.type} for '{search_terms[:30]}'")

    except Exception as e:
        log.warning(f"  Scrape failed for '{search_terms[:30]}': {e}")


def _render_audio_only(job: Job) -> str:
    """Fallback: just copy audio as output if video rendering fails."""
    if job.audio and Path(job.audio).exists():
        output_path = str(OUTPUT_DIR / f"{job.id}_{Path(job.script).stem}.mp3")
        shutil.copy(job.audio, output_path)
        return output_path
    raise RuntimeError("No audio available to render")
