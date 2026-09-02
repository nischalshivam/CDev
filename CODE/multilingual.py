#!/usr/bin/env python3
"""
multilingual.py — Multi-language support for ProClip Engine
v2.0 — Language-neutral architecture

CORE PRINCIPLE: Visual content is language-neutral. Only the user-facing
parts (script, audio, text overlays) are in the target language.
The library, scraping, and metadata are ALL in English (canonical).

FLOW:
  French Script (narration in French)
       ↓
  Clue Script (French narration + universal entity names)
       ↓
  Asset Search (entities are universal → search English library)
       ↓
  If miss → SCRAPE IN ENGLISH (because YouTube/Wikimedia = mostly English)
       ↓
  Asset cataloged in ENGLISH (canonical)
       ↓
  Render: French audio + French text overlays + English-matched assets
"""

import re
import logging
import json
import os
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from enum import Enum

log = logging.getLogger("ProClip.multilang")

# ============================================================
# LANGUAGE CONFIGURATION
# ============================================================

class Language(Enum):
    ENGLISH = "en"
    FRENCH = "fr"
    GERMAN = "de"
    SPANISH = "es"
    HINDI = "hi"
    ARABIC = "ar"
    JAPANESE = "ja"
    KOREAN = "ko"
    PORTUGUESE = "pt"
    RUSSIAN = "ru"
    ITALIAN = "it"
    CHINESE = "zh"
    AUTO = "auto"

# Only the FRONTEND settings vary by language.
# Backend (scraping, library) is ALWAYS English.
LANG_CONFIG: Dict[str, Dict] = {
    "en": {
        "name": "English",
        "tts_voice": "en-US-GuyNeural",
        "tts_female": "en-US-JennyNeural",
        "rtl": False,
        "font": "Inter",
        "font_noto": "Inter-Regular.ttf",
        "display_name": "English",
    },
    "fr": {
        "name": "French",
        "tts_voice": "fr-FR-HenriNeural",
        "tts_female": "fr-FR-DeniseNeural",
        "rtl": False,
        "font": "Inter",
        "font_noto": "Inter-Regular.ttf",
        "display_name": "Français",
    },
    "de": {
        "name": "German",
        "tts_voice": "de-DE-ConradNeural",
        "tts_female": "de-DE-KatjaNeural",
        "rtl": False,
        "font": "Inter",
        "font_noto": "Inter-Regular.ttf",
        "display_name": "Deutsch",
    },
    "es": {
        "name": "Spanish",
        "tts_voice": "es-ES-AlvaroNeural",
        "tts_female": "es-ES-ElviraNeural",
        "rtl": False,
        "font": "Inter",
        "font_noto": "Inter-Regular.ttf",
        "display_name": "Español",
    },
    "hi": {
        "name": "Hindi",
        "tts_voice": "hi-IN-SwaraNeural",
        "tts_female": "hi-IN-SwaraNeural",
        "rtl": False,
        "font": "Noto Sans Devanagari",
        "font_noto": "NotoSansDevanagari-Regular.ttf",
        "display_name": "हिन्दी",
    },
    "ar": {
        "name": "Arabic",
        "tts_voice": "ar-SA-ZayedNeural",
        "tts_female": "ar-SA-ZariyahNeural",
        "rtl": True,
        "font": "Noto Sans Arabic",
        "font_noto": "NotoSansArabic-Regular.ttf",
        "display_name": "العربية",
    },
    "ja": {
        "name": "Japanese",
        "tts_voice": "ja-JP-KeitaNeural",
        "tts_female": "ja-JP-NanamiNeural",
        "rtl": False,
        "font": "Noto Sans JP",
        "font_noto": "NotoSansJP-Regular.ttf",
        "display_name": "日本語",
    },
    "ko": {
        "name": "Korean",
        "tts_voice": "ko-KR-InJoonNeural",
        "tts_female": "ko-KR-SunHiNeural",
        "rtl": False,
        "font": "Noto Sans KR",
        "font_noto": "NotoSansKR-Regular.ttf",
        "display_name": "한국어",
    },
    "pt": {
        "name": "Portuguese",
        "tts_voice": "pt-BR-FabioNeural",
        "tts_female": "pt-BR-ElzaNeural",
        "rtl": False,
        "font": "Inter",
        "font_noto": "Inter-Regular.ttf",
        "display_name": "Português",
    },
    "ru": {
        "name": "Russian",
        "tts_voice": "ru-RU-DmitryNeural",
        "tts_female": "ru-RU-SvetlanaNeural",
        "rtl": False,
        "font": "Noto Sans",
        "font_noto": "NotoSans-Regular.ttf",
        "display_name": "Русский",
    },
    "it": {
        "name": "Italian",
        "tts_voice": "it-IT-DiegoNeural",
        "tts_female": "it-IT-ElsaNeural",
        "rtl": False,
        "font": "Inter",
        "font_noto": "Inter-Regular.ttf",
        "display_name": "Italiano",
    },
    "zh": {
        "name": "Chinese",
        "tts_voice": "zh-CN-YunxiNeural",
        "tts_female": "zh-CN-XiaoyiNeural",
        "rtl": False,
        "font": "Noto Sans SC",
        "font_noto": "NotoSansSC-Regular.ttf",
        "display_name": "中文",
    },
}

# ============================================================
# LANGUAGE DETECTION (same as before)
# ============================================================

SCRIPT_RANGES = {
    "ja": [(0x3040, 0x309F), (0x30A0, 0x30FF)],
    "ko": [(0xAC00, 0xD7AF), (0x1100, 0x11FF)],
    "ar": [(0x0600, 0x06FF), (0x0750, 0x077F)],
    "hi": [(0x0900, 0x097F)],
    "ru": [(0x0400, 0x04FF)],
    "zh": [(0x4E00, 0x9FFF)],
}

def detect_language(text: str) -> str:
    """Auto-detect the language of a text string."""
    if not text or len(text.strip()) < 10:
        return "en"

    script_counts = {}
    for lang, ranges in SCRIPT_RANGES.items():
        count = 0
        for char in text:
            code = ord(char)
            for start, end in ranges:
                if start <= code <= end:
                    count += 1
                    break
        script_counts[lang] = count

    total_chars = len([c for c in text if c.isalpha()])
    if total_chars > 0:
        for lang, count in script_counts.items():
            if count > total_chars * 0.1:
                return lang

    return _detect_latin_language(text)


def _detect_latin_language(text: str) -> str:
    """Detect language among Latin-script options."""
    words = re.findall(r'\b[a-zA-ZÀ-ÿ]+\b', text.lower())
    if not words:
        return "en"

    markers = {
        "fr": ["le", "la", "les", "des", "est", "une", "pour", "dans", "avec",
               "pas", "aux", "cette", "sont", "plus", "tout", "fait", "droit",
               "chars", "blindé", "militaire", "armée"],
        "de": ["der", "die", "das", "und", "ist", "ein", "eine", "von", "mit",
               "auf", "für", "als", "auch", "sich", "nach", "aus", "wird"],
        "es": ["el", "la", "los", "las", "del", "por", "para", "con", "que",
               "una", "está", "todo", "esta", "pero", "como", "muy"],
        "pt": ["o", "os", "das", "dos", "uma", "umas", "não", "mas",
               "seu", "sua", "como", "mais", "tem", "bem", "até", "isso"],
        "it": ["il", "la", "di", "che", "perché", "questo", "quello",
               "sono", "stato", "anche", "come", "più", "ma", "nel"],
    }

    scores = {}
    for lang, marker_words in markers.items():
        score = sum(1 for w in words if w in marker_words)
        scores[lang] = score / max(len(words), 1)

    best_lang = max(scores, key=scores.get)
    if scores[best_lang] > 0.02:
        return best_lang
    return "en"


# ============================================================
# LANGUAGE CONTEXT
# ============================================================

class LanguageContext:
    """
    Holds frontend-only language settings.
    Backend (library, scraping) always uses English internally.
    """

    def __init__(self, language_code: str = "en"):
        self.code = language_code
        self.config = LANG_CONFIG.get(language_code, LANG_CONFIG["en"])
        self.name = self.config["name"]
        self.display_name = self.config["display_name"]
        self.tts_voice = self.config["tts_voice"]
        self.tts_female = self.config["tts_female"]
        self.is_rtl = self.config["rtl"]
        self.font = self.config["font"]
        self.font_file = self.config["font_noto"]

    @classmethod
    def from_text(cls, text: str) -> "LanguageContext":
        code = detect_language(text)
        return cls(code)

    @classmethod
    def from_code(cls, code: str) -> "LanguageContext":
        return cls(code)

    def get_tts_voice(self, gender: str = "male") -> str:
        return self.tts_voice if gender == "male" else self.tts_female

    def get_text_direction(self) -> str:
        return "rtl" if self.is_rtl else "ltr"

    def __repr__(self):
        return f"Lang({self.code}: {self.name})"


# ============================================================
# ENTITY EXTRACTION — THE BRIDGE BETWEEN LANGUAGES
# ============================================================

def extract_entities_from_beat(beat: Dict) -> List[str]:
    """
    Extract entities from a beat. These are UNIVERSAL names.
    Uses niche-specific entity patterns to avoid false positives.
    """
    entities = beat.get("entities", [])
    if entities:
        return entities

    narration = beat.get("narration_verbatim", "")

    # Universal entity patterns — only actual entity names
    entity_patterns = [
        # Vehicle brands (capitalized, often multi-word)
        r'\b(?:Wildax|Swift|Bailey|Elddis|Auto[- ]?Roller|Pilot|Globe[- ]?Traveler|Benimar|Grand Frontier|Hymer|Trigano)\b',
        # Model names
        r'\b(?:Autograph|Accordo|Carrera|Mileo|Evo\s*77)\b',
        # Currency + amounts (price mentions)
        r'(?:£|GBP)\s*[\d,]+',
        # Military/tech model numbers
        r'\b(?:F-35[A-C]?|F-22|F-16|AH-64\s*Apache|MH-60[RST]?|Boxer\s*CRV?|Bradley|Abrams|T-90)\b',
        # Organizations (all caps or proper)
        r'\b(?:NATO|BAE|Rheinmetall|Lockheed\s*Martin)\b',
        # Events
        r'\b(?:Exercise\s+\w+|RIMPAC|Talisman\s*Sabre)\b',
    ]

    found = []
    for pattern in entity_patterns:
        matches = re.findall(pattern, narration, re.IGNORECASE)
        found.extend(matches)

    return list(set(found))


# ============================================================
# CLUE SCRIPT — Multilingual but entities are universal
# ============================================================

MULTILINGUAL_CLUE_PROMPT = """You are a documentary video production AI. Break a narration script into a structured "Clue Script" — a production blueprint.

CRITICAL RULES:
1. Keep narration_verbatim EXACTLY as in the script (in its original language).
2. Entity names (vehicle names, aircraft names, locations, organizations) MUST stay as-is.
   These are UNIVERSAL — "Boxer CRV" is "Boxer CRV" in every language.
   "F-35" is "F-35" in every language.
   DO NOT translate entity names.
3. search_terms should be in ENGLISH (because YouTube/Wikimedia content is mostly in English).
   Use entity names + English action words.
   Example: search_terms = "Boxer CRV driving military exercise"
4. text_overlay_title and text_overlay_subtitle should be in the SCRIPT LANGUAGE.
5. visual_role: literal|context|evidence|atmospheric|map|text_only

BEAT STRUCTURE:
{{
  "beat_id": "B001",
  "narration_verbatim": "Exact text from script (original language)",
  "start_time": 0.0,
  "end_time": 5.0,
  "duration": 5.0,
  "entities": ["Boxer CRV", "Australian Army"],
  "actions": ["driving"],
  "visual_role": "literal",
  "asset_type": "video|image|text_card",
  "search_terms": "Boxer CRV driving military exercise",
  "mood": "neutral|curious|tension|dark|hopeful|triumphant|action|epic",
  "text_overlay_title": "Le Boxer CRV — L'Avenir Blindé de l'Australie",
  "text_overlay_subtitle": "Développé par Rheinmetall",
  "strictness": "exact|high|general"
}}

STRICTNESS GUIDE:
- "exact": Must match exact variant (Boxer CRV ≠ generic Boxer)
- "high": Must match type (any armored vehicle if none exact)
- "general": Any related content works

Script language: {language_name}
Video title: {title}

Narration Script:
{script_text}

Respond with ONLY valid JSON:
{{
  "beats": [...],
  "title": "{title}",
  "total_duration": number
}}"""


def generate_multilingual_clue_script(
    script_text: str,
    lang_context: LanguageContext,
    niche_config: Dict,
    title: str
) -> Dict:
    """
    Generate Clue Script.
    Key: narration is in script's language, but search_terms are ALWAYS in English.
    """

    prompt = MULTILINGUAL_CLUE_PROMPT.format(
        language_name=lang_context.display_name,
        title=title
    )

    input_text = f"""Niche: {niche_config.get('display_name', 'unknown')}
Video Title: {title}
Language: {lang_context.name} ({lang_context.code})

Narration Script (keep narration_verbatim exactly as-is, in {lang_context.name}):
{script_text}

Generate the Clue Script JSON. Remember: search_terms MUST be in ENGLISH."""

    try:
        import anthropic
        client = anthropic.Anthropic()

        message = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=4096,
            temperature=0.3,
            messages=[{"role": "user", "content": f"{prompt}\n\n{input_text}"}]
        )

        response_text = message.content[0].text
        clue_script = _extract_json(response_text)

        clue_script["script_id"] = f"S{abs(hash(script_text)) % 1000:03d}"
        clue_script["language"] = lang_context.code
        clue_script["language_name"] = lang_context.name
        clue_script["niche"] = niche_config.get('name', 'unknown')
        clue_script["title"] = title
        clue_script["estimated_duration"] = len(script_text.split()) * 0.15
        clue_script["generated_at"] = datetime.now().isoformat()

        return clue_script

    except ImportError:
        log.warning("anthropic not installed — using placeholder")
        return _placeholder_clue(script_text, lang_context, title)
    except Exception as e:
        log.error(f"Clue Script generation failed: {e}")
        return _placeholder_clue(script_text, lang_context, title)


def _placeholder_clue(script_text: str, lang_ctx: LanguageContext, title: str) -> Dict:
    """Generate basic Clue Script without API."""
    sentences = re.split(r'(?<=[.!?])\s+', script_text.strip())
    beats = []
    current_time = 0.0

    for i, sentence in enumerate(sentences):
        if not sentence or len(sentence) < 5:
            continue
        words = len(sentence.split())
        duration = words * 0.15 + 1.5
        entities = extract_entities_from_beat({"narration_verbatim": sentence})

        beats.append({
            "beat_id": f"B{i + 1:03d}",
            "narration_verbatim": sentence.strip(),
            "start_time": round(current_time, 2),
            "end_time": round(current_time + duration, 2),
            "duration": round(duration, 2),
            "entities": entities,
            "actions": [],
            "visual_role": "literal",
            "asset_type": "text_card",
            "search_terms": " ".join(entities) if entities else sentence.strip()[:80],
            "mood": "neutral",
            "text_overlay_title": sentence.strip()[:100],
            "text_overlay_subtitle": "",
            "strictness": "general",
            "matched_assets": None,
            "media_type": "text_card"
        })
        current_time += duration + 0.3

    return {
        "script_id": f"S{abs(hash(script_text)) % 1000:03d}",
        "title": title,
        "language": lang_ctx.code,
        "language_name": lang_ctx.name,
        "beats": beats,
        "total_duration": round(current_time, 2),
        "estimated_duration": round(current_time, 2),
        "niche": "unknown",
        "style": "clean_doc",
        "generated_at": datetime.now().isoformat()
    }


# ============================================================
# LIBRARY SEARCH — Language-neutral
# ============================================================

def search_library_for_beat(library_db, beat: Dict) -> List[Dict]:
    """
    Search library for a beat's assets.

    IMPORTANT: The library is ALWAYS searched with English queries.
    Because:
    - All library metadata is in English (canonical)
    - Entity names are universal (Boxer CRV = same in all languages)
    - search_terms in Clue Script are always in English

    This means a French script, a German script, and a Spanish script
    ALL search the SAME English library and find the SAME assets.
    """

    entities = beat.get("entities", [])
    # search_terms are ALREADY in English (Clue Script ensures this)
    search_terms = beat.get("search_terms", "")
    asset_type = beat.get("asset_type", "video_clip")
    strictness = beat.get("strictness", "general")

    results = []

    # Search the library
    for entry_id, entry in library_db.data.get("entries", {}).items():
        score = 0

        # ENTITY MATCHING (universal — language independent)
        entry_entities = [e.lower() for e in entry.get("entities", [])]
        for entity in entities:
            entity_lower = entity.lower()
            if entity_lower in entry_entities:
                score += 5.0  # Strong match
            else:
                for ee in entry_entities:
                    if entity_lower in ee or ee in entity_lower:
                        score += 2.0
                        break

        # ACTION MATCHING
        entry_actions = [a.lower() for a in entry.get("actions", [])]
        beat_actions = [a.lower() for a in beat.get("actions", [])]
        for action in beat_actions:
            if action in entry_actions:
                score += 1.5

        # TEXT MATCHING (English to English)
        if search_terms:
            desc = entry.get("description", "").lower()
            search_words = search_terms.lower().split()
            desc_words = set(desc.split())
            overlap = sum(1 for w in search_words if w in desc_words)
            score += overlap * 0.5

        # TYPE FILTER
        entry_type = entry.get("type", "")
        if asset_type == "video" and entry_type != "video_clip":
            continue
        if asset_type == "image" and entry_type not in ("image", "video_clip"):
            continue

        if score > 0:
            results.append({**entry, "score": score})

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:5]


# ============================================================
# SCRAPING — ALWAYS IN ENGLISH
# ============================================================

def build_scraping_queries(beat: Dict, niche_config: Dict) -> List[str]:
    """
    Build search queries for scraping.
    ALL queries are in ENGLISH because:
    - YouTube content is 80%+ English titles
    - Wikimedia Commons descriptions are in English
    - Pexels API works best with English queries

    The script language does NOT affect scraping.
    """

    entities = beat.get("entities", [])
    actions = beat.get("actions", [])
    search_terms = beat.get("search_terms", "")

    # search_terms from Clue Script are ALREADY in English
    # Use them directly
    queries = []

    if search_terms:
        queries.append(search_terms)

    # Add entity-specific queries (always English)
    for entity in entities[:2]:
        for action in actions[:2]:
            queries.append(f"{entity} {action}")
        if not actions:
            queries.append(f"{entity} footage")

    # If nothing specific, use the narration first 50 chars as query
    if not queries:
        narration = beat.get("narration_verbatim", "")
        queries.append(narration[:80])

    # Deduplicate and limit
    queries = list(dict.fromkeys(queries))  # preserve order, deduplicate
    return queries[:5]


# ============================================================
# CATALOGING — Always in ENGLISH
# ============================================================

def catalog_asset_as_english(
    file_path: str,
    source_type: str,
    source_url: str,
    gemini_model
) -> Dict:
    """
    Catalog a new asset with ENGLISH metadata.

    This ensures that no matter what language the script was in,
    the library entry is always in English — so it can be found
    by ANY future script in ANY language.
    """

    try:
        import google.generativeai as genai
        video_file = genai.upload_file(file_path)

        import time
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)

        prompt = """Describe this video clip for a documentary footage library.
Be specific and detailed. RESPOND IN ENGLISH.

DESCRIPTION: [What is shown - vehicles, people, equipment, terrain, actions]
ENTITIES: [List of identifiable objects/vehicles/people/places]
ACTIONS: [What is happening]
ENVIRONMENT: [Indoor/outdoor, terrain, weather]
QUALITY: [high/medium/low]
SHOT_TYPE: [wide/medium/close-up/aerial/static/tracking]
"""

        response = gemini_model.generate_content(
            [video_file, prompt],
            generation_config={"max_tokens": 1000}
        )

        genai.delete_file(video_file.name)

        # Parse response
        def extract(label):
            for line in response.text.split('\n'):
                if line.startswith(label + ':'):
                    return line.split(':', 1)[1].strip()
            return ""

        import hashlib
        id_hash = hashlib.md5(file_path.encode()).hexdigest()[:6]
        source_prefix = {"pexels": "PEX", "wikimedia": "WIK", "youtube": "YT", "local": "LOC"}
        prefix = source_prefix.get(source_type, "UNK")

        return {
            "id": f"{prefix}_{id_hash}",
            "type": "video_clip",
            "file": file_path,
            "source_type": source_type,
            "source_url": source_url,
            "description": extract("DESCRIPTION"),
            "entities": [e.strip() for e in extract("ENTITIES").split(',') if e.strip()],
            "actions": [a.strip() for a in extract("ACTIONS").split(',') if a.strip()],
            "environment": [e.strip() for e in extract("ENVIRONMENT").split(',') if e.strip()],
            "quality": extract("QUALITY") or "medium",
            "shot_type": extract("SHOT_TYPE") or "medium",
            "cataloged_by": "gemini-2.0-flash",
            "catalog_language": "en",  # ALWAYS English
        }

    except Exception as e:
        log.error(f"Cataloging failed: {e}")
        return None


# ============================================================
# TEXT OVERLAYS — in target language
# ============================================================

class TextOverlaySystem:
    """
    Generates text overlays in the TARGET language.
    This is the ONLY place where target language is used for rendering.
    """

    def __init__(self, lang_context: LanguageContext):
        self.lang = lang_context

    def get_title_style(self, beat: Dict) -> Dict:
        """Get text style for a beat. Text is in the target language."""

        title = beat.get("text_overlay_title", beat.get("narration_verbatim", ""))[:120]
        subtitle = beat.get("text_overlay_subtitle", "")[:80]

        return {
            "title": title,
            "subtitle": subtitle,
            "font": self.lang.font,
            "font_file": self.lang.font_file,
            "direction": self.lang.get_text_direction(),
            "title_size": "52px",
            "subtitle_size": "30px",
            "color": "#FFFFFF",
            "bg_color": "#000000@0.7",
            "rtl": self.lang.is_rtl,
        }

    def get_ffmpeg_text_filter(self, style: Dict, duration: float,
                               y_pos: int = 980) -> str:
        """Generate FFmpeg drawtext filter."""

        title = style.get("title", "")
        subtitle = style.get("subtitle", "")
        font_file = style.get("font_file", "Inter-Regular.ttf")
        rtl = style.get("rtl", False)

        # Escape for FFmpeg
        title_escaped = title.replace("'", "\\'").replace(":", "\\:").replace("%", "\\%")
        subtitle_escaped = subtitle.replace("'", "\\'").replace(":", "\\:").replace("%", "\\%")

        filters = []

        if rtl:
            # RTL: right-aligned
            filters.append(
                f"drawtext=text='{subtitle_escaped}':"
                f"fontfile='{font_file}':fontsize=30:fontcolor=white:"
                f"box=1:boxcolor=black@0.7:boxborderw=10:"
                f"x=w-text_w-50:y=h-100:"
                f"enable='between(t,0,{duration})'"
            )
            filters.append(
                f"drawtext=text='{title_escaped}':"
                f"fontfile='{font_file}':fontsize=52:fontcolor=white:"
                f"box=1:boxcolor=black@0.7:boxborderw=10:"
                f"x=w-text_w-50:y=h-160:"
                f"enable='between(t,0,{duration})'"
            )
        else:
            # LTR: center-aligned
            if subtitle:
                filters.append(
                    f"drawtext=text='{subtitle_escaped}':"
                    f"fontfile='{font_file}':fontsize=30:fontcolor=white:"
                    f"box=1:boxcolor=black@0.7:boxborderw=10:"
                    f"x=(w-text_w)/2:y=h-80:"
                    f"enable='between(t,0,{duration})'"
                )
            filters.append(
                f"drawtext=text='{title_escaped}':"
                f"fontfile='{font_file}':fontsize=52:fontcolor=white:"
                f"box=1:boxcolor=black@0.7:boxborderw=10:"
                f"x=(w-text_w)/2:y=h-140:"
                f"enable='between(t,0,{duration})'"
            )

        return ",".join(filters)


# ============================================================
# MAIN MULTILINGUAL PIPELINE
# ============================================================

def process_job_multilingual(
    script_text: str,
    audio_path: str = None,
    niche_config: Dict = None,
    title: str = None,
    language_override: str = None,
    library_db=None,
) -> Dict:
    """
    Process a job with full multilingual support.

    KEY ARCHITECTURE:
    - Script/audio/overlays: in target language
    - Library/scraping/cataloging: ALWAYS in English
    - Entities: universal bridge between all languages
    """

    # ==========================================
    # STEP 0: DETECT TARGET LANGUAGE
    # ==========================================
    if language_override and language_override != "auto":
        lang_ctx = LanguageContext.from_code(language_override)
    else:
        lang_ctx = LanguageContext.from_text(script_text)

    log.info(f"[ML] Target language: {lang_ctx.name} ({lang_ctx.code})")
    log.info(f"[ML] Backend: ALWAYS English (canonical)")

    # ==========================================
    # STEP 1: GENERATE CLUE SCRIPT
    # ==========================================
    # - narration_verbatim: in target language (from script)
    # - entities: universal (never translated)
    # - search_terms: ALWAYS in English
    # - text_overlay_*: in target language
    log.info(f"[ML] Generating Clue Script ({lang_ctx.name} frontend, English backend)...")

    clue_script = generate_multilingual_clue_script(
        script_text, lang_ctx, niche_config or {}, title or "Untitled"
    )

    beats = clue_script.get("beats", [])

    # Verify: search_terms should be in English
    for beat in beats:
        search_terms = beat.get("search_terms", "")
        if search_terms:
            log.debug(f"  Beat {beat.get('beat_id')}: search_terms = \"{search_terms}\"")

    # ==========================================
    # STEP 2: ASSET RETRIEVAL (English backend)
    # ==========================================
    from CODE.demandscout_core import LibraryDB, search_library_for_beat, build_scraping_queries

    db = library_db or LibraryDB()
    overlay_sys = TextOverlaySystem(lang_ctx)

    for beat in beats:
        asset_type = beat.get("asset_type", "video_clip")
        if asset_type == "text_only":
            beat["matched_assets"] = None
            beat["media_type"] = "text_card"
            continue

        # Search library using ENGLISH entities + ENGLISH search_terms
        entities = beat.get("entities", [])
        search_terms = beat.get("search_terms", "")

        log.info(f"[ML] Searching library for: entities={entities}, query=\"{search_terms}\"")

        results = search_library_for_beat(db, beat)

        if results:
            best = results[0]
            beat["matched_assets"] = best
            beat["media_type"] = best.get("type", "video_clip")
            log.info(f"[ML]   → Library HIT: {best.get('id')} (score: {best.get('score', 0):.1f})")
        else:
            # MISS — need to scrape
            # Scraping queries are ALREADY in English
            queries = build_scraping_queries(beat, niche_config or {})
            beat["scrape_queries"] = queries  # Store for later
            beat["matched_assets"] = None
            beat["media_type"] = "text_card"  # Fallback until scraped
            log.info(f"[ML]   → Library MISS. Will scrape: {queries}")

        # Add overlay style (in target language)
        beat["overlay_style"] = overlay_sys.get_title_style(beat)

    # ==========================================
    # STEP 3: BUILD TIMELINE
    # ==========================================
    from CODE.demandscout_core import build_timeline_from_beats

    job_info = {
        "id": "ML_JOB",
        "title": title or "Untitled",
        "niche": niche_config or {},
        "style": niche_config.get("style", "clean_doc") if niche_config else "clean_doc",
    }

    timeline = build_timeline_from_beats(beats, job_info, niche_config or {})

    # ==========================================
    # RETURN everything for rendering
    # ==========================================
    return {
        "clue_script": clue_script,
        "beats": beats,
        "timeline": timeline,
        "language": lang_ctx.code,
        "language_name": lang_ctx.name,
        "tts_voice": lang_ctx.tts_voice,
        "overlay_system": overlay_sys,
        "scrape_needed": [b for b in beats if not b.get("matched_assets")],
        "scrape_queries": {
            b["beat_id"]: b.get("scrape_queries", [])
            for b in beats if not b.get("matched_assets")
        },
    }


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _extract_json(text: str) -> Dict:
    """Extract JSON from response text."""
    import json
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not extract JSON: {text[:200]}")


def get_language_info(code: str) -> Dict:
    """Get language configuration by code."""
    return LANG_CONFIG.get(code, LANG_CONFIG["en"])


def list_supported_languages() -> List[Dict]:
    """List all supported languages."""
    return [
        {"code": code, "name": cfg["name"], "display_name": cfg["display_name"],
         "tts": cfg["tts_voice"], "rtl": cfg["rtl"]}
        for code, cfg in LANG_CONFIG.items()
    ]
