#!/usr/bin/env python3
"""
Renderer Module for ProClip Engine
Composes final video using FFmpeg with style pack theming.
"""

import os
import json
import subprocess
import logging
import shutil
import math
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

log = logging.getLogger("ProClip.renderer")

# ============================================================
# CONFIGURATION
# ============================================================

STANDARD_RESOLUTIONS = {
    "1080p": {"width": 1920, "height": 1080, "fps": 30, "bitrate": "8M"},
    "720p": {"width": 1280, "height": 720, "fps": 30, "bitrate": "5M"},
    "4k": {"width": 3840, "height": 2160, "fps": 30, "bitrate": "20M"},
}

# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class TimelineItem:
    """A single item in the render timeline."""
    file_path: str
    item_type: str  # "video" | "image" | "text_card" | "lower_third"
    start_time: float
    duration: float
    narration_start: float = 0.0
    narration_end: float = 0.0
    entities: List[str] = field(default_factory=list)
    motion: str = "static"  # "static" | "push_in" | "pan_left" | "pan_right"
    transition_in: str = "cut"  # "cut" | "dissolve" | "fade"
    transition_out: str = "cut"
    text_overlay: str = ""
    text_position: str = "center"  # "center" | "bottom" | "top"
    position_x: float = 0.5  # 0-1, normalized
    position_y: float = 0.5

@dataclass
class RenderJob:
    """Complete render configuration for one video."""
    job_id: str
    title: str
    output_path: str
    resolution: str = "1080p"
    fps: int = 30
    timeline: List[TimelineItem] = field(default_factory=list)
    audio_path: str = ""
    audio_offset: float = 0.0
    style_pack: str = "PACKS/style/clean_doc"
    niche_pack: str = "PACKS/defence.yaml"

# ============================================================
# RENDERER ENGINE
# ============================================================

class RendererEngine:
    """
    Composes final video from timeline using FFmpeg.
    Supports: video clips, images (Ken Burns), text cards, lower thirds,
              audio narration, background music, transitions.
    """

    def __init__(self, style_pack_dir: str = "PACKS/style"):
        self.style_pack_dir = Path(style_pack_dir)
        self.resolution = STANDARD_RESOLUTIONS["1080p"]
        self.temp_dir = Path("DOWNLOADS/render_temp")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # MAIN RENDER METHOD
    # ============================================================

    def render(self, render_job: RenderJob) -> str:
        """
        Render complete video from timeline.

        Returns: path to output MP4 file
        """
        output = Path(render_job.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        self.resolution = STANDARD_RESOLUTIONS.get(
            render_job.resolution, STANDARD_RESOLUTIONS["1080p"]
        )

        log.info(f"Rendering: {render_job.title}")
        log.info(f"  Output: {output}")
        log.info(f"  Timeline items: {len(render_job.timeline)}")
        log.info(f"  Resolution: {self.resolution['width']}x{self.resolution['height']}")

        # Step 1: Build FFmpeg filter complex
        filter_complex, inputs = self._build_filter_complex(render_job)

        # Step 2: Run FFmpeg
        cmd = self._build_ffmpeg_command(
            render_job, filter_complex, inputs, output
        )

        log.info(f"  Running FFmpeg...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )

        if result.returncode != 0:
            log.error(f"FFmpeg error: {result.stderr[-500:]}")
            raise RuntimeError(f"FFmpeg render failed: {result.stderr[-200:]}")

        # Step 3: Verify output
        if output.exists() and output.stat().st_size > 10000:
            log.info(f"✓ Render complete: {output} ({output.stat().st_size / 1024 / 1024:.1f} MB)")
            return str(output)
        else:
            raise RuntimeError("FFmpeg completed but output file is missing or empty")

    # ============================================================
    # FFmpeg FILTER COMPLEX BUILDER
    # ============================================================

    def _build_filter_complex(self, job: RenderJob) -> Tuple[str, List]:
        """
        Build FFmpeg filter_complex string from timeline.
        This is the core rendering logic.
        """
        W = self.resolution["width"]
        H = self.resolution["height"]

        filters = []
        inputs = []
        input_idx = 0

        for item in job.timeline:
            idx = input_idx

            if item.item_type == "video":
                # Video clip: scale + trim + optional motion
                video_filter, audio_filter = self._video_filter(idx, item, W, H)
                filters.append(video_filter)
                if audio_filter:
                    filters.append(audio_filter)

            elif item.item_type == "image":
                # Image: Ken Burns + duration
                img_filter = self._image_filter(idx, item, W, H)
                filters.append(img_filter)

            elif item.item_type in ("text_card", "lower_third"):
                # Text overlay card
                text_filter = self._text_filter(idx, item, W, H)
                filters.append(text_filter)

            inputs.append(item.file_path)
            input_idx += 1

        # Audio mixing (if narration audio exists)
        if job.audio_path and Path(job.audio_path).exists():
            audio_idx = input_idx
            inputs.append(job.audio_path)
            audio_filter = self._audio_mix_filter(input_idx, job)
            filters.append(audio_filter)

        filter_complex = ";".join(filters) if filters else ""

        return filter_complex, inputs

    def _video_filter(self, idx: int, item: TimelineItem, W: int, H: int) -> Tuple[str, Optional[str]]:
        """Build filter for video clip."""

        # Scale to resolution, maintain aspect ratio (pad if needed)
        video_filter = (
            f"[{idx}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,"
            f"trim=start={item.start_time}:duration={item.duration},"
            f"setpts=PTS-STARTPTS"
        )

        # Add motion effects
        if item.motion == "push_in_slow":
            video_filter += f",zoompan=z='min(zoom+0.0005,1.1)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}"
        elif item.motion == "pan_left":
            video_filter += f",crop=iw:ih:iw*0.3*t/{item.duration}:0"

        # Label for concatenation
        video_filter += f",format=yuv420p[v{idx}]"

        # Audio: trim and fade
        audio_filter = None
        if item.narration_start > 0 or item.narration_end > 0:
            audio_filter = (
                f"[{idx}:a]atrim=start={item.narration_start}:"
                f"duration={item.duration},asetpts=PTS-STARTPTS[a{idx}]"
            )

        return video_filter, audio_filter

    def _image_filter(self, idx: int, item: TimelineItem, W: int, H: int) -> str:
        """Build filter for image with Ken Burns effect."""

        motion_filters = ""
        if item.motion == "push_in":
            # Slow zoom in over duration
            zoom_expr = f"1+0.05*on/{self.resolution['fps']}"
            motion_filters = (
                f"zoompan=z='{zoom_expr}':"
                f"x='iw/2-(iw/zoom/2)':"
                f"y='ih/2-(ih/zoom/2)':"
                f"d=1:s={W}x{H}:fps={self.resolution['fps']}"
            )
        elif item.motion == "pan_right":
            # Pan right over duration
            motion_filters = (
                f"zoompan=z='1.05':"
                f"x='max(iw*0.05 - iw*0.05*on/{int(item.duration * self.resolution['fps'])},0)':"
                f"y='ih/2-(ih*1.05/2)':"
                f"d=1:s={W}x{H}:fps={self.resolution['fps']}"
            )

        # Static with Ken Burns fallback
        if not motion_filters:
            motion_filters = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black"

        return (
            f"[{idx}:v]{motion_filters},"
            f"trim=duration={item.duration},"
            f"fps={self.resolution['fps']},"
            f"format=yuv420p[v{idx}]"
        )

    def _text_filter(self, idx: int, item: TimelineItem, W: int, H: int) -> str:
        """Build filter for text card with style pack theming."""

        # Load style pack config
        style = self._load_style_config()

        # Calculate text position
        if item.text_position == "center":
            x_expr = "(w-text_w)/2"
            y_expr = "(h-text_h)/2"
        elif item.text_position == "bottom":
            x_expr = "(w-text_w)/2"
            y_expr = f"h*0.85"
        elif item.text_position == "top":
            x_expr = "(w-text_w)/2"
            y_expr = f"h*0.1"
        else:
            x_expr = f"w*{item.position_x}"
            y_expr = f"h*{item.position_y}"

        text = item.text_overlay.replace("'", "\\'").replace(":", "\\:")

        return (
            f"color=c=black:s={W}x{H}:d={item.duration}:r={self.resolution['fps']}[base];"
            f"[base]drawtext=text='{text}':"
            f"fontcolor={style.get('text_color', 'white')}:"
            f"fontsize={style.get('text_size', 72)}:"
            f"fontfile={style.get('font_path', 'Arial')}:"
            f"x={x_expr}:y={y_expr}:"
            f"box=1:boxcolor=black@0.6:boxborderw=20[v{idx}]"
        )

    def _audio_mix_filter(self, audio_idx: int, job: RenderJob) -> str:
        """Build audio mixing filter (narration + optional background music)."""
        # Simple: just narration audio
        # Can be extended to add background music mixing
        return f"[{audio_idx}:a]asetpts=PTS-STARTPTS[aout]"

    def _build_ffmpeg_command(
        self,
        job: RenderJob,
        filter_complex: str,
        inputs: List[str],
        output: Path
    ) -> List[str]:
        """Build complete FFmpeg command."""

        # Build input args
        input_args = []
        for inp in inputs:
            input_args.extend(["-i", inp])

        # Build concat filter labels
        video_labels = "".join(f"[v{i}]" for i in range(len(job.timeline)))
        audio_labels = ""
        if job.audio_path and Path(job.audio_path).exists():
            audio_labels = "[aout]"

        cmd = [
            "ffmpeg", "-y"
        ] + input_args + [
            "-filter_complex", filter_complex,
            "-map", video_labels,
            "-map", audio_labels if audio_labels else "0:a?",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-b:v", self.resolution["bitrate"],
            "-maxrate", self.resolution["bitrate"],
            "-bufsize", "2M",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-ac", "2",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            "-r", str(self.resolution["fps"]),
            "-s", f"{self.resolution['width']}x{self.resolution['height']}",
            str(output)
        ]

        return cmd

    # ============================================================
    # STYLE PACK CONFIG
    # ============================================================

    def _load_style_config(self) -> Dict:
        """Load style pack configuration."""
        style_file = self.style_pack_dir / "clean_doc" / "style.yaml"
        if style_file.exists():
            try:
                import yaml
                with open(style_file) as f:
                    return yaml.safe_load(f).get("theme", {})
            except Exception:
                pass

        # Defaults
        return {
            "text_color": "white",
            "text_size": 72,
            "font_path": "Arial",
            "lower_third_color": "#1a5276",
            "transition_duration": 0.5,
        }

    # ============================================================
    # TIMELINE BUILDER
    # ============================================================

    def build_timeline_from_beats(
        self,
        beats: List[Dict],
        assets: List,
        style_pack: str = "clean_doc"
    ) -> List[TimelineItem]:
        """
        Convert script beats + matched assets into render timeline.

        Args:
            beats: List of beat dicts from script analysis
            assets: List of matched assets (ScrapedAsset or ClipEntry)
            style_pack: Style pack name

        Returns:
            List of TimelineItem objects for rendering
        """
        timeline = []
        current_time = 0.0

        for i, beat in enumerate(beats):
            narration = beat.get("narration_verbatim", "")
            narration_duration = beat.get("duration", 5.0)

            # Check if there's a matched asset
            matched = beat.get("matched_assets")
            media_type = beat.get("media_type", "text_card")

            if matched and matched.get("type") == "video":
                # Use video clip
                clip_path = matched.get("file_path") or matched.get("file")
                if clip_path and Path(clip_path).exists():
                    item = TimelineItem(
                        file_path=clip_path,
                        item_type="video",
                        start_time=current_time,
                        duration=narration_duration,
                        narration_start=current_time,
                        narration_end=current_time + narration_duration,
                        entities=matched.get("entities", []),
                        motion="push_in_slow" if matched.get("quality") == "high" else "static",
                        transition_in="cut",
                        transition_out="cut"
                    )
                    timeline.append(item)
                    current_time += narration_duration
                    continue

            elif matched and matched.get("type") == "image":
                # Use image with Ken Burns
                img_path = matched.get("file_path") or matched.get("file")
                if img_path and Path(img_path).exists():
                    item = TimelineItem(
                        file_path=img_path,
                        item_type="image",
                        start_time=current_time,
                        duration=narration_duration,
                        motion="push_in",
                        transition_in="dissolve",
                        transition_out="dissolve",
                        text_overlay=narration[:100] if len(narration) > 50 else "",
                        text_position="bottom"
                    )
                    timeline.append(item)
                    current_time += narration_duration
                    continue

            # Default: text card
            if narration:
                # Title card for first beat, text card for rest
                if i == 0:
                    text = narration[:60]
                    item_type = "text_card"
                    text_pos = "center"
                    duration = min(narration_duration, 5.0)
                else:
                    # Split long narration into text cards
                    text = narration[:120] + "..." if len(narration) > 120 else narration
                    item_type = "text_card"
                    text_pos = "bottom"
                    duration = narration_duration

                item = TimelineItem(
                    file_path="",
                    item_type=item_type,
                    start_time=current_time,
                    duration=duration,
                    text_overlay=text,
                    text_position=text_pos,
                    transition_in="fade" if i > 0 else "cut",
                    transition_out="fade"
                )
                timeline.append(item)
                current_time += duration

        return timeline

    # ============================================================
    # QUICK PREVIEW / PROXY RENDER
    # ============================================================

    def render_preview(
        self,
        render_job: RenderJob,
        preview_duration: float = 30.0
    ) -> str:
        """
        Render a quick preview (lower quality, shorter).
        Useful for checking before full render.
        """
        preview_job = RenderJob(
            job_id=f"{render_job.job_id}_preview",
            title=f"{render_job.title} (PREVIEW)",
            output_path=f"DOWNLOADS/preview_{render_job.job_id}.mp4",
            resolution="720p",
            fps=24,
            timeline=render_job.timeline[:10],  # First 10 items
            audio_path=render_job.audio_path,
            style_pack=render_job.style_pack
        )

        return self.render(preview_job)
