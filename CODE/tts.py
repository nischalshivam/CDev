#!/usr/bin/env python3
"""
TTS Module for ProClip Engine
Uses Microsoft Edge TTS (edge-tts) for high-quality, free narration generation.
"""

import os
import re
import asyncio
import logging
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, List

log = logging.getLogger("ProClip.tts")

# ============================================================
# VOICE CONFIGURATION
# ============================================================

# Recommended voices for documentary narration (English)
VOICE_PRESETS = {
    "documentary_male": {
        "voice": "en-US-GuyNeural",
        "description": "Deep, authoritative male voice — perfect for defence documentaries",
    },
    "documentary_female": {
        "voice": "en-US-JennyNeural",
        "description": "Clear, professional female voice",
    },
    "australian_male": {
        "voice": "en-AU-WilliamNeural",
        "description": "Australian male voice — great for Australian defence topics",
    },
    "british_male": {
        "voice": "en-GB-RyanNeural",
        "description": "British male voice — formal and authoritative",
    },
    "american_male": {
        "voice": "en-US-ChristopherNeural",
        "description": "American male voice — energetic and engaging",
    },
}

DEFAULT_VOICE = VOICE_PRESETS["documentary_male"]["voice"]

# ============================================================
# TTS ENGINE
# ============================================================

class TTSEngine:
    """
    Text-to-Speech engine using Microsoft Edge TTS.
    Generates narration audio from script text.
    """

    def __init__(self, output_dir: str = "audio", voice: str = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.voice = voice or DEFAULT_VOICE

    def generate_from_script(
        self,
        script_text: str,
        output_name: str = None,
        voice: str = None,
        rate: str = "+0%",  # Speed adjustment: "+0%", "+10%", "-5%"
        pitch: str = "+0Hz",  # Pitch adjustment
    ) -> Path:
        """
        Generate narration audio from script text.

        Args:
            script_text: Full narration script
            output_name: Output filename (without extension)
            voice: Voice ID (e.g., "en-US-GuyNeural")
            rate: Speed adjustment percentage
            pitch: Pitch adjustment in Hz

        Returns:
            Path to generated MP3 file
        """
        voice = voice or self.voice

        # Generate filename
        if not output_name:
            output_name = f"tts_{hash(script_text[:100]) % 10000:04d}"

        output_path = self.output_dir / f"{output_name}.mp3"

        # Skip if already exists
        if output_path.exists() and output_path.stat().st_size > 5000:
            log.info(f"TTS already exists: {output_path.name}")
            return output_path

        log.info(f"Generating TTS: {output_name} ({len(script_text)} chars)")
        log.info(f"  Voice: {voice}")

        # Clean script text (remove markdown, extra whitespace)
        clean_text = self._clean_script_text(script_text)

        # Generate using edge-tts
        mp3_path = self._generate_with_edge_tts(
            clean_text, output_path, voice, rate, pitch
        )

        return mp3_path

    def generate_from_beats(
        self,
        beats: List[Dict],
        output_prefix: str = "narration",
        voice: str = None
    ) -> List[Dict]:
        """
        Generate narration audio for each beat separately.
        Useful for precise timing control.

        Args:
            beats: List of beat dicts with 'narration_verbatim' key
            output_prefix: Prefix for output files
            voice: Voice ID

        Returns:
            List of dicts with 'beat', 'audio_path', 'duration' keys
        """
        voice = voice or self.voice
        results = []

        for i, beat in enumerate(beats):
            text = beat.get("narration_verbatim", "")
            if not text or len(text.strip()) < 10:
                continue

            audio_name = f"{output_prefix}_{i:03d}"
            audio_path = self.generate_from_script(
                text, output_name=audio_name, voice=voice
            )

            # Get audio duration
            duration = self._get_audio_duration(audio_path)

            results.append({
                "beat_index": i,
                "beat": beat,
                "audio_path": str(audio_path),
                "duration": duration
            })

            log.info(f"  Beat {i+1}: {duration:.1f}s")

        return results

    def _clean_script_text(self, text: str) -> str:
        """Clean script text for TTS (remove markdown, fix punctuation)."""

        # Remove markdown formatting
        text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)  # *bold* **bold**
        text = re.sub(r'#{1,6}\s+', '', text)  # Headers
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # Links
        text = re.sub(r'```[\s\S]*?```', '', text)  # Code blocks
        text = re.sub(r'`[^`]+`', '', text)  # Inline code

        # Remove stage directions in brackets
        text = re.sub(r'\[([^\]]+)\]', '', text)

        # Fix spacing
        text = re.sub(r'\n+', ' ', text)  # Newlines to spaces
        text = re.sub(r'\s{2,}', ' ', text)  # Multiple spaces to single

        # Fix punctuation for TTS (pause after periods)
        text = text.replace('. ', '. ... ')
        text = text.replace('! ', '! ... ')
        text = text.replace('? ', '? ... ')
        text = text.replace(': ', ': ... ')

        # Remove leading/trailing whitespace
        text = text.strip()

        # Limit length (edge-tts has a max of ~8000 chars per request)
        if len(text) > 7500:
            log.warning(f"Text too long ({len(text)} chars), truncating to 7500")
            text = text[:7500]

        return text

    def _generate_with_edge_tts(
        self,
        text: str,
        output_path: Path,
        voice: str,
        rate: str,
        pitch: str
    ) -> Path:
        """Generate audio using edge-tts CLI."""
        import re

        try:
            # Use edge-tts CLI
            cmd = [
                "edge-tts",
                "--voice", voice,
                "--text", text,
                "--write-media", str(output_path),
                "--rate", rate,
                "--pitch", pitch,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                encoding="utf-8",
                errors="replace"
            )

            if result.returncode != 0:
                log.error(f"edge-tts failed: {result.stderr}")
                raise RuntimeError(f"TTS generation failed: {result.stderr[:200]}")

            if not output_path.exists() or output_path.stat().st_size < 1000:
                raise RuntimeError("TTS output file is empty or missing")

            log.info(f"  Generated: {output_path.name} ({output_path.stat().st_size / 1024:.1f} KB)")
            return output_path

        except FileNotFoundError:
            log.error("edge-tts not found. Install with: pip install edge-tts")
            raise
        except subprocess.TimeoutExpired:
            log.error("TTS generation timed out")
            raise

    def _get_audio_duration(self, audio_path: Path) -> float:
        """Get audio duration in seconds using ffprobe."""

        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path)
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return float(result.stdout.strip())
        except Exception:
            # Estimate from file size (rough: 16KB per second for MP3)
            return audio_path.stat().st_size / 16000

    def list_available_voices(self) -> List[Dict]:
        """List all available Edge TTS voices."""

        try:
            result = subprocess.run(
                ["edge-tts", "--list-voices"],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace"
            )

            voices = []
            for line in result.stdout.strip().split('\n'):
                if line.startswith("Name:"):
                    voice_id = line.split("Name:")[1].strip()
                    voices.append({"id": voice_id, "name": voice_id})

            return voices

        except Exception as e:
            log.error(f"Failed to list voices: {e}")
            return []

    def get_preset_voices(self) -> Dict[str, str]:
        """Get recommended voice presets for documentary use."""
        return {k: v["voice"] for k, v in VOICE_PRESETS.items()}


# ============================================================
# AUDIO UTILITIES
# ============================================================

class AudioUtils:
    """Utility functions for audio processing."""

    @staticmethod
    def get_duration(audio_path: str) -> float:
        """Get audio file duration in seconds."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return float(result.stdout.strip())
        except Exception:
            return 0.0

    @staticmethod
    def get_sample_rate(audio_path: str) -> int:
        """Get audio sample rate."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=sample_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return int(result.stdout.strip().split('\n')[0])
        except Exception:
            return 44100

    @staticmethod
    def normalize_audio(input_path: str, output_path: str, target_level: float = -20.0):
        """Normalize audio to target dB level."""
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-af", f"loudnorm=I={target_level}:TP=-1.5:LRA=11",
            "-ar", "44100", "-ac", "2",
            output_path
        ]
        subprocess.run(cmd, capture_output=True)
        return output_path

    @staticmethod
    def concatenate_audio(files: List[str], output_path: str) -> str:
        """Concatenate multiple audio files into one."""

        if len(files) == 1:
            shutil.copy(files[0], output_path)
            return output_path

        # Create file list for ffmpeg
        list_file = Path(output_path).parent / "concat_list.txt"
        with open(list_file, 'w') as f:
            for audio_file in files:
                f.write(f"file '{os.path.abspath(audio_file)}'\n")

        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            output_path
        ]

        subprocess.run(cmd, capture_output=True)
        list_file.unlink()

        return output_path
