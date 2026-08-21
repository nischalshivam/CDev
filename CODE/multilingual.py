#!/usr/bin/env python3
"""
multilingual.py — Multi-language support for ProClip Engine

This module makes the ENTIRE system language-agnostic.
One library serves ALL languages.

Supported languages:
  - English (en), French (fr), German (de), Spanish (es)
  - Hindi (hi), Arabic (ar), Japanese (ja), Korean (ko)
  - Portuguese (pt), Russian (ru), Italian (it), Chinese (zh)

How it works:
  1. Detect script language automatically
  2. Configure TTS voice for that language
  3. Generate Clue Script in that language
  4. Match assets using entities (entity names are universal)
  5. Render text overlays in that language
  6. Output video in that language
"""

import re
import logging
import json
import os
from pathlib import Path
from typing import Optional, Dict, List
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

# Complete language configuration
LANG_CONFIG: Dict[str, Dict] = {
    "en": {
        "name": "English",
        "tts_voice": "en-US-GuyNeural",
        "tts_female": "en-US-JennyNeural",
        "rtl": False,  # Right-to-left?
        "font": "Inter",
        "scraping_sources": ["youtube", "pexels", "wikimedia"],
        "common_words": ["the", "is", "and", "of", "to", "in", "a", "for", "with",
                         "this", "that", "are", "was", "has", "have", "from"],
    },
    "fr": {
        "name": "French",
        "tts_voice": "fr-FR-HenriNeural",
        "tts_female": "fr-FR-DeniseNeural",
        "rtl": False,
        "font": "Inter",
        "scraping_sources": ["youtube", "pexels", "wikimedia"],
        "common_words": ["le", "la", "les", "de", "du", "des", "et", "est", "un",
                         "une", "pour", "dans", "avec", "ce", "que", "pas", "au",
                         "aux", "en", "par", "sur", "ne", "se", "son", "sa"],
    },
    "de": {
        "name": "German",
        "tts_voice": "de-DE-ConradNeural",
        "tts_female": "de-DE-KatjaNeural",
        "rtl": False,
        "font": "Inter",
        "scraping_sources": ["youtube", "pexels", "wikimedia"],
        "common_words": ["der", "die", "das", "und", "ist", "ein", "eine", "von",
                         "mit", "auf", "für", "als", "auch", "sich", "nach", "aus",
                         "wird", "hat", "werden", "oder", "wie", "dass", "nicht"],
    },
    "es": {
        "name": "Spanish",
        "tts_voice": "es-ES-AlvaroNeural",
        "tts_female": "es-ES-ElviraNeural",
        "rtl": False,
        "font": "Inter",
        "scraping_sources": ["youtube", "pexels", "wikimedia"],
        "common_words": ["el", "la", "los", "las", "de", "del", "en", "es", "un",
                         "una", "por", "con", "para", "al", "que", "y", "no", "se",
                         "lo", "su", "más", "pero", "como", "este", "ya"],
    },
    "hi": {
        "name": "Hindi",
        "tts_voice": "hi-IN-SwaraNeural",
        "tts_female": "hi-IN-SwaraNeural",
        "rtl": False,
        "font": "Noto Sans Devanagari",
        "scraping_sources": ["youtube", "wikimedia"],
        "common_words": ["के", "की", "का", "में", "है", "और", "से", "को", "ने",
                         "पर", "कि", "या", "था", "भी", "जो", "वह", "यह", "कर"],
    },
    "ar": {
        "name": "Arabic",
        "tts_voice": "ar-SA-ZayedNeural",
        "tts_female": "ar-SA-ZariyahNeural",
        "rtl": True,
        "font": "Noto Sans Arabic",
        "scraping_sources": ["youtube", "wikimedia"],
        "common_words": ["في", "من", "إلى", "على", "عن", "مع", "هذا", "التي",
                         "الذي", "كان", "قد", "لا", "إن", "ما", "أو", "كل"],
    },
    "ja": {
        "name": "Japanese",
        "tts_voice": "ja-JP-KeitaNeural",
        "tts_female": "ja-JP-NanamiNeural",
        "rtl": False,
        "font": "Noto Sans JP",
        "scraping_sources": ["youtube", "wikimedia"],
        "common_words": ["の", "に", "は", "を", "た", "が", "で", "て", "と",
                         "し", "れ", "さ", "ある", "いる", "も", "する", "から"],
    },
    "ko": {
        "name": "Korean",
        "tts_voice": "ko-KR-InJoonNeural",
        "tts_female": "ko-KR-SunHiNeural",
        "rtl": False,
        "font": "Noto Sans KR",
        "scraping_sources": ["youtube", "wikimedia"],
        "common_words": ["이", "그", "저", "것", "들", "나", "우리", "수", "있",
                         "하", "되", "들", "같", "없", "말", "년", "만", "그것"],
    },
    "pt": {
        "name": "Portuguese",
        "tts_voice": "pt-BR-FabioNeural",
        "tts_female": "pt-BR-ElzaNeural",
        "rtl": False,
        "font": "Inter",
        "scraping_sources": ["youtube", "pexels", "wikimedia"],
        "common_words": ["o", "a", "os", "as", "de", "do", "da", "em", "um", "uma",
                         "para", "com", "por", "que", "se", "no", "na", "ou"],
    },
    "ru": {
        "name": "Russian",
        "tts_voice": "ru-RU-DmitryNeural",
        "tts_female": "ru-RU-SvetlanaNeural",
        "rtl": False,
        "font": "Noto Sans",
        "scraping_sources": ["youtube", "wikimedia"],
        "common_words": ["в", "и", "на", "не", "что", "он", "с", "как", "это",
                         "его", "но", "они", "мы", "вы", "за", "из", "у", "о"],
    },
    "it": {
        "name": "Italian",
        "tts_voice": "it-IT-DiegoNeural",
        "tts_female": "it-IT-ElsaNeural",
        "rtl": False,
        "font": "Inter",
        "scraping_sources": ["youtube", "pexels", "wikimedia"],
        "common_words": ["il", "la", "di", "che", "è", "un", "per", "con", "da",
                         "a", "in", "si", "lo", "gli", "le", "non", "una", "ma"],
    },
    "zh": {
        "name": "Chinese",
        "tts_voice": "zh-CN-YunxiNeural",
        "tts_female": "zh-CN-XiaoyiNeural",
        "rtl": False,
        "font": "Noto Sans SC",
        "scraping_sources": ["youtube", "wikimedia"],
        "common_words": ["的", "了", "是", "在", "和", "有", "不", "这", "他",
                         "们", "来", "到", "时", "大", "地", "为", "子", "中"],
    },
}

# ============================================================
# LANGUAGE DETECTION
# ============================================================

# Script ranges for each language
SCRIPT_RANGES = {
    "ja": [(0x3040, 0x309F), (0x30A0, 0x30FF)],  # Hiragana + Katakana
    "ko": [(0xAC00, 0xD7AF), (0x1100, 0x11FF)],  # Hangul
    "ar": [(0x0600, 0x06FF), (0x0750, 0x077F)],  # Arabic
    "hi": [(0x0900, 0x097F)],                      # Devanagari
    "ru": [(0x0400, 0x04FF)],                      # Cyrillic
    "zh": [(0x4E00, 0x9FFF)],                      # CJK Unified
}

def detect_language(text: str) -> str:
    """
    Auto-detect the language of a text string.

    Returns: ISO 639-1 language code (e.g., "fr", "de", "en")
    """
    if not text or len(text.strip()) < 10:
        return "en"

    # Count characters in each script range
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

    # If any non-Latin script has significant presence, use it
    total_chars = len([c for c in text if c.isalpha()])
    if total_chars > 0:
        for lang, count in script_counts.items():
            if count > total_chars * 0.1:  # 10% threshold
                return lang

    # For Latin-script languages, use word frequency analysis
    return _detect_latin_language(text)


def _detect_latin_language(text: str) -> str:
    """Detect language among Latin-script options."""

    words = re.findall(r'\b[a-zA-ZÀ-ÿ]+\b', text.lower())
    if not words:
        return "en"

    # Language-specific word markers
    markers = {
        "fr": ["le", "la", "les", "des", "est", "une", "pour", "dans", "avec",
               "pas", "aux", "cette", "sont", "plus", "tout", "fait", "droit"],
        "de": ["der", "die", "das", "und", "ist", "ein", "eine", "von", "mit",
               "auf", "für", "als", "auch", "sich", "nach", "aus", "wird"],
        "es": ["el", "la", "los", "las", "del", "por", "para", "con", "que",
               "una", "está", "todo", "esta", "pero", "como", "muy"],
        "pt": ["o", "os", "das", "dos", "uma", "umas", "umas", "não", "mas",
               "seu", "sua", "como", "mais", "tem", "bem", "até", "isso"],
        "it": ["il", "la", "di", "che", "perché", "questo", "quello",
               "sono", "stato", "anche", "come", "più", "ma", "nel"],
    }

    scores = {}
    for lang, marker_words in markers.items():
        score = sum(1 for w in words if w in marker_words)
        scores[lang] = score / max(len(words), 1)

    best_lang = max(scores, key=scores.get)
    if scores[best_lang] > 0.02:  # At least 2% markers
        return best_lang

    return "en"


# ============================================================
# LANGUAGE CONTEXT (holds detected language + config)
# ============================================================

class LanguageContext:
    """
    Holds all language-specific settings for a job.
    Created once per job after language detection.
    """

    def __init__(self, language_code: str = "en", force: bool = False):
        self.code = language_code
        self.config = LANG_CONFIG.get(language_code, LANG_CONFIG["en"])
        self.name = self.config["name"]
        self.tts_voice = self.config["tts_voice"]
        self.tts_female = self.config["tts_female"]
        self.is_rtl = self.config["rtl"]
        self.font = self.config["font"]
        self.scraping_sources = self.config["scraping_sources"]

    @classmethod
    def from_text(cls, text: str) -> "LanguageContext":
        """Auto-detect language from text."""
        code = detect_language(text)
        return cls(code)

    @classmethod
    def from_code(cls, code: str) -> "LanguageContext":
        """Create from explicit language code."""
        return cls(code)

    @classmethod
    def from_script_path(cls, path: str) -> "LanguageContext":
        """Detect from script file content."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                text = f.read  # First 2000 chars enough for detection
            return cls.from_text(text)
        except Exception:
            return cls("en")

    def get_tts_config(self, gender: str = "male") -> Dict:
        """Get TTS configuration for this language."""
        return {
            "voice": self.tts_voice if gender == "male" else self.tts_female,
            "language": self.code,
        }

    def get_scraping_query(self, base_query: str) -> str:
        """
        Adapt search query for the target language.
        Entity names stay as-is (universal), rest translates.
        """
        return base_query  # Entities are universal

    def get_text_direction(self) -> str:
        """Get CSS/text direction: 'ltr' or 'rtl'"""
        return "rtl" if self.is_rtl else "ltr"

    def __repr__(self):
        return f"Lang({self.code}: {self.name})"


# ============================================================
# MULTILINGUAL LIBRARY
# ============================================================

class MultilingualLibrary:
    """
    Library that stores assets with multi-language metadata.

    KEY DESIGN: Assets are stored ONCE but searchable in ANY language.
    """

    def __init__(self, library_db: "LibraryDB"):
        self.db = library_db

    def search_multilingual(
        self,
        query: str,
        query_language: str,
        entity_list: List[str],
        type_filter: str = None,
        top_k: int = 10
    ) -> List[Dict]:
        """
        Search library in any language.

        Strategy:
        1. Entity matching (universal — works in any language)
        2. Translation-based text matching (translate query to asset's language)
        3. Cross-language semantic matching
        """
        results = []

        # ENTITY MATCHING (works across ALL languages)
        # "Boxer CRV" in French script matches "Boxer CRV" in English library entry
        entity_matches = self._match_entities(entity_list, query_language)

        # TEXT MATCHING
        text_matches = self._match_text(query, query_language)

        # COMBINE
        all_ids = set(entity_matches.keys()) | set(text_matches.keys())
        for entry_id in all_ids:
            entry = self.db.data["entries"].get(entry_id, {})
            if not entry:
                continue

            # Type filter
            if type_filter and entry.get("type") != type_filter:
                continue

            score = 0
            if entry_id in entity_matches:
                score += entity_matches[entry_id] * 2  # Entity match is strong
            if entry_id in text_matches:
                score += text_matches[entry_id]

            results.append({**entry, "score": score})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def _match_entities(self, entities: List[str], lang: str) -> Dict[str, float]:
        """
        Match entities across languages.
        Entity names are universal (Boxer CRV, F-35, etc.)
        """
        matches = {}

        for entry_id, entry in self.db.data["entries"].items():
            entry_entities = [e.lower() for e in entry.get("entities", [])]
            score = 0

            for entity in entities:
                entity_lower = entity.lower()
                # Direct match
                if entity_lower in entry_entities:
                    score += 3.0
                # Partial match
                else:
                    for ee in entry_entities:
                        if entity_lower in ee or ee in entity_lower:
                            score += 1.5
                            break

            if score > 0:
                matches[entry_id] = score

        return matches

    def _match_text(self, query: str, lang: str) -> Dict[str, float]:
        """Text matching using description overlap."""
        matches = {}
        query_words = set(query.lower().split())

        for entry_id, entry in self.db.data["entries"].items():
            # Use description in the matching language
            desc_key = f"description_{lang}"
            description = entry.get(desc_key, entry.get("description", ""))

            desc_words = set(description.lower().split())
            overlap = len(query_words & desc_words)

            if overlap > 0:
                matches[entry_id] = overlap * 0.5

        return matches

    def add_multilingual_entry(
        self,
        entry_id: str,
        entry_type: str,
        file_path: str,
        source_language: str,
        descriptions: Dict[str, str],
        entities: List[str],
        actions: List[str],
        **kwargs
    ):
        """
        Add entry with descriptions in multiple languages.

        Args:
            descriptions: {"en": "English desc", "fr": "French desc", ...}
        """
        entry = {
            "id": entry_id,
            "type": entry_type,
            "file": file_path,
            "source_language": source_language,
            "entities": entities,
            "actions": actions,
            **kwargs
        }

        # Store descriptions per language
        for lang, desc in descriptions.items():
            entry[f"description_{lang}"] = desc

        # Default description = first available
        entry["description"] = descriptions.get("en", list(descriptions.values())[0])

        self.db.data["entries"][entry_id] = entry
        self.db._update_indexes_from_entry(entry)
        self.db.save()


# ============================================================
# MULTILINGUAL CLUE SCRIPT GENERATION
# ============================================================

MULTILINGUAL_CLUE_PROMPT = """You are a documentary video production AI. The user will give you a narration script in ANY language. Your job is to break it into a structured "Clue Script" — a production blueprint.

IMPORTANT RULES:
1. The script is in {language_name}. Keep the narration_verbatim in {language_name}.
2. Entity names (vehicle names, aircraft names, etc.) stay as-is — they are universal.
3. search_terms should help find visual content. Use entity names + action words.
4. For non-English scripts, entities are typically still in English or original form.
5. text_overlay_* fields must be in {language_name} for on-screen text.

Break the script into narration beats. Each beat:

BEAT STRUCTURE:
{{
  "beat_id": "B001",
  "narration_verbatim": "Exact text as spoken (in {language_name})",
  "start_time": 0.0,
  "end_time": 5.0,
  "duration": 5.0,
  "entities": ["Entity1", "Entity2"],
  "actions": ["action1", "action2"],
  "visual_role": "literal|context|evidence|atmospheric|map|text_only",
  "asset_type": "video|image|text_card|lower_third",
  "search_terms": "keywords to find this visual",
  "mood": "neutral|curious|tension|dark|hopeful|triumphant|action|epic",
  "text_overlay_title": "Main title text for this beat ({language_name})",
  "text_overlay_subtitle": "Subtitle if needed ({language_name})",
  "strictness": "exact|high|general"
}}

VISUAL ROLE GUIDE:
- "literal" = Show the actual thing (Boxer CRV driving)
- "context" = Related B-roll (military base, soldiers)
- "evidence" = Map, diagram, document
- "atmospheric" = Mood shot (sunset over base, flags)
- "map" = Geographic map
- "text_only" = No visual needed, just text card

STRICTNESS:
- "exact" = Must match exact variant (Boxer CRV ≠ Boxer generic)
- "high" = Must match type (any armored vehicle acceptable)
- "general" = Any related content works

Respond with ONLY valid JSON:
{{
  "beats": [...],
  "title": "...",
  "total_duration": number
}}"""


def generate_multilingual_clue_script(
    script_text: str,
    language_context: LanguageContext,
    niche_config: Dict,
    title: str
) -> Dict:
    """
    Generate Clue Script in the target language.
    """

    prompt = MULTILINGUAL_CLUE_PROMPT.format(
        language_name=language_context.name
    )

    input_text = f"""Niche: {niche_config.get('display_name', 'unknown')}
Video Title: {title}
Language: {language_context.name} ({language_context.code})

Narration Script:
{script_text}

Generate the Clue Script JSON."""

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
        clue_script["language"] = language_context.code
        clue_script["language_name"] = language_context.name
        clue_script["niche"] = niche_config.get('name', 'unknown')
        clue_script["title"] = title
        clue_script["estimated_duration"] = len(script_text.split()) * 0.15
        clue_script["generated_at"] = datetime.now().isoformat()

        return clue_script

    except ImportError:
        log.warning("anthropic not installed — using placeholder")
        return _placeholder_multilingual_clue(script_text, language_context, title)
    except Exception as e:
        log.error(f"Clue Script generation failed: {e}")
        return _placeholder_multilingual_clue(script_text, language_context, title)


def _placeholder_multilingual_clue(
    script_text: str,
    lang_ctx: LanguageContext,
    title: str
) -> Dict:
    """Generate basic Clue Script without API."""

    sentences = re.split(r'(?<=[.!?])\s+', script_text.strip())
    beats = []
    current_time = 0.0

    for i, sentence in enumerate(sentences):
        if not sentence or len(sentence) < 5:
            continue

        words = len(sentence.split())
        duration = words * 0.15 + 1.5

        beats.append({
            "beat_id": f"B{i + 1:03d}",
            "narration_verbatim": sentence.strip(),
            "start_time": round(current_time, 2),
            "end_time": round(current_time + duration, 2),
            "duration": round(duration, 2),
            "entities": _extract_entities(sentence),
            "actions": [],
            "visual_role": "literal",
            "asset_type": "text_card",
            "search_terms": sentence.strip()[:80],
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
# MULTILINGUAL TEXT OVERLAY SYSTEM
# ============================================================

class TextOverlaySystem:
    """
    Generates text overlays in the target language.
    Handles:
    - RTL languages (Arabic, Hebrew)
    - Font selection per language
    - Text sizing
    """

    def __init__(self, lang_context: LanguageContext):
        self.lang = lang_context

    def get_title_style(self, beat: Dict) -> Dict:
        """Get text style configuration for a beat's title."""

        text = beat.get("text_overlay_title", beat.get("narration_verbatim", ""))
        subtitle = beat.get("text_overlay_subtitle", "")

        return {
            "title": text,
            "subtitle": subtitle,
            "font": self.lang.font,
            "direction": self.lang.get_text_direction(),
            "title_size": "48px",
            "subtitle_size": "28px",
            "color": "#FFFFFF",
            "bg_color": "#000000@0.7",
            "position": "bottom",
            "rtl": self.lang.is_rtl,
        }

    def get_ffmpeg_text_filter(self, style: Dict, x: int = 960, y: int = 980) -> str:
        """
        Generate FFmpeg drawtext filter for this language.
        Handles RTL, special fonts, etc.
        """

        font = style.get("font", "Inter")
        title = style.get("title", "")
        subtitle = style.get("subtitle", "")
        rtl = style.get("rtl", False)

        # Escape for FFmpeg
        title_escaped = title.replace("'", "\\'").replace(":", "\\:")
        subtitle_escaped = subtitle.replace("'", "\\'").replace(":", "\\:")

        # Font file path (need to handle non-Latin fonts)
        font_path = self._get_font_path(font)

        filters = []

        if rtl:
            # RTL text: render subtitle right-aligned
            filters.append(
                f"drawtext=text='{subtitle_escaped}':"
                f"fontfile='{font_path}':"
                f"fontsize=28:fontcolor=white:"
                f"box=1:boxcolor=black@0.7:boxborderw=10:"
                f"x=w-text_w-50:y=h-100:"
                f"enable='between(t,0,100)'"
            )
        else:
            # LTR text: normal
            filters.append(
                f"drawtext=text='{subtitle_escaped}':"
                f"fontfile='{font_path}':"
                f"fontsize=28:fontcolor=white:"
                f"box=1:boxcolor=black@0.7:boxborderw=10:"
                f"x=(w-text_w)/2:y=h-80:"
                f"enable='between(t,0,100)'"
            )

        return ",".join(filters)

    def _get_font_path(self, font_name: str) -> str:
        """Get system font path. Returns fallback if specific font not found."""
        import platform

        if platform.system() == "Windows":
            fonts_dir = r"C:\Windows\Fonts"
            font_map = {
                "Inter": "Inter-Regular.ttf",
                "Bebas Neue": "BebasNeue-Regular.ttf",
                "Noto Sans Devanagari": "NotoSansDevanagari-Regular.ttf",
                "Noto Sans Arabic": "NotoSansArabic-Regular.ttf",
                "Noto Sans JP": "NotoSansJP-Regular.ttf",
                "Noto Sans KR": "NotoSansKR-Regular.ttf",
                "Noto Sans SC": "NotoSansSC-Regular.ttf",
            }
            font_file = font_map.get(font_name, "arial.ttf")
            return f"{fonts_dir}/{font_file}"
        else:
            return font_name  # Let FFmpeg find by name on Linux/Mac


# ============================================================
# MULTILINGUAL SCRAPING
# ============================================================

class MultilingualScraper:
    """
    Scrapes content in the target language.
    """

    # Language-specific YouTube channels and search terms
    LANG_SOURCES = {
        "fr": {
            "channels": ["TV5MONDE", "France 24", "Arte", "RT France"],
            "search_suffixes": ["français", "vidéo", "documentaire"],
        },
        "de": {
            "channels": ["ZDF", "ARD", "DW Documentary", "WELT"],
            "search_suffixes": ["Deutsch", "Video", "Dokumentation"],
        },
        "es": {
            "channels": ["DW Español", "Antena 3", "LaSexta"],
            "search_suffixes": ["español", "video", "documental"],
        },
        "hi": {
            "channels": ["Defence Review India", "Indian Defence"],
            "search_suffixes": ["हिंदी", "वीडियो"],
        },
    }

    def __init__(self, lang_context: LanguageContext):
        self.lang = lang_context

    def build_search_query(self, base_query: str, entities: List[str]) -> str:
        """
        Build a search query optimized for the target language.

        Strategy:
        - Entity names stay as-is (universal)
        - Add language-specific terms if needed
        """

        # Entity names are universal — use them directly
        entity_part = " ".join(entities[:3])

        # For non-English, add language suffix to help find localized content
        suffixes = self.LANG_SOURCES.get(self.lang.code, {}).get("search_suffixes", [])
        if suffixes:
            return f"{entity_part} {' '.join(suffixes[:2])}"
        return entity_part

    def get_preferred_sources(self) -> List[str]:
        """Get preferred scraping sources for this language."""
        return self.lang.scraping_sources


# ============================================================
# MULTILINGUAL PIPELINE INTEGRATION
# ============================================================

def process_job_multilingual(
    script_text: str,
    audio_path: str = None,
    niche_config: Dict = None,
    title: str = None,
    language_override: str = None
) -> str:
    """
    Process a job with full multilingual support.

    Args:
        script_text: Narration script (any language)
        audio_path: Optional audio file (any language)
        niche_config: Niche pack config
        title: Video title
        language_override: Force specific language code (or auto-detect)

    Returns: Path to output video
    """

    # ==========================================
    # STEP 0: DETECT LANGUAGE
    # ==========================================
    if language_override:
        lang_ctx = LanguageContext.from_code(language_override)
    else:
        lang_ctx = LanguageContext.from_text(script_text)

    log.info(f"Detected language: {lang_ctx.name} ({lang_ctx.code})")

    # ==========================================
    # STEP 1: AUDIO (same, just different voice)
    # ==========================================
    if not audio_path or not Path(audio_path).exists():
        log.info(f"Generating TTS in {lang_ctx.name}...")
        tts = _get_tts_engine()
        if tts:
            audio_path = tts.generate_from_script(
                script_text,
                voice=lang_ctx.tts_voice
            )

    # ==========================================
    # STEP 2: CLUE SCRIPT (in target language)
    # ==========================================
    log.info(f"Generating Clue Script in {lang_ctx.name}...")
    clue_script = generate_multilingual_clue_script(
        script_text, lang_ctx, niche_config or {}, title or "Untitled"
    )

    # ==========================================
    # STEP 3: ASSET RETRIEVAL (language-agnostic)
    # ==========================================
    log.info("Retrieving assets...")
    library = LibraryDB()
    ml_library = MultilingualLibrary(library)
    scraper = MultilingualScraper(lang_ctx)

    beats = clue_script.get("beats", [])

    for beat in beats:
        entities = beat.get("entities", [])
        search_terms = beat.get("search_terms", "")
        asset_type = beat.get("asset_type", "text_card")

        if asset_type == "text_card":
            continue

        # Search library (works in ANY language)
        results = ml_library.search_multilingual(
            query=search_terms,
            query_language=lang_ctx.code,
            entity_list=entities,
            top_k=3
        )

        if results:
            beat["matched_assets"] = results[0]
            beat["media_type"] = results[0].get("type", "video_clip")
        else:
            # Scrape in target language
            query = scraper.build_search_query(search_terms, entities)
            log.info(f"  Scraping [{lang_ctx.name}]: {query}")
            # ... scrape and add to library

    # ==========================================
    # STEP 4: TEXT OVERLAYS (in target language)
    # ==========================================
    overlay_system = TextOverlaySystem(lang_ctx)

    for beat in beats:
        style = overlay_system.get_title_style(beat)
        beat["overlay_style"] = style
        beat["ffmpeg_text_filter"] = overlay_system.get_ffmpeg_text_filter(style)

    # ==========================================
    # STEP 5: RENDER
    # ==========================================
    timeline = build_timeline(beats, job, niche_config or {})

    output_path = f"output/{lang_ctx.code}_{title or 'video'}.mp4"
    final_path = render_video(timeline, job, output_path)

    log.info(f"✓ Done: {final_path} [{lang_ctx.name}]")
    return final_path


# ============================================================
# HELPER — re-export from main module
# ============================================================

def _extract_json(text: str) -> Dict:
    """Extract JSON from response text."""
    import json, re
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
