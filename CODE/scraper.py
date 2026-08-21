#!/usr/bin/env python3
"""
Web Scraper Module for ProClip Engine
Sources: Pexels API, Wikimedia Commons, YouTube thumbnails
"""

import os
import re
import requests
import time
import logging
from pathlib import Path
from urllib.parse import quote, urlencode
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict

log = logging.getLogger("ProClip.scraper")

# ============================================================
# CONFIGURATION
# ============================================================

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"
PEXELS_API_URL = "https://api.pexels.com/v1"

# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class ScrapedAsset:
    """Represents a single scraped media asset."""
    id: str
    type: str  # "video" | "image"
    file_path: str
    source_type: str  # "pexels" | "wikimedia" | "youtube_thumb"
    source_url: str
    download_url: str
    topic: str
    description: str = ""
    entities: List[str] = None
    tags: List[str] = None
    width: int = 0
    height: int = 0
    duration: float = 0.0  # for videos
    license: str = ""
    thumbnail_url: str = ""
    photographer: str = ""
    created_at: str = ""

    def __post_init__(self):
        if self.entities is None:
            self.entities = []
        if self.tags is None:
            self.tags = []

# ============================================================
# SCRAPER ENGINE
# ============================================================

class ScraperEngine:
    """
    Handles web scraping for free media assets.
    Primary sources: Pexels API, Wikimedia Commons.
    """

    def __init__(self, output_dir: str = "DOWNLOADS/scraped"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ProClip Documentary Engine/1.0 (educational use)"
        })

    # ============================================================
    # MAIN SCRAPE METHOD
    # ============================================================

    def scrape_for_topic(
        self,
        topic: str,
        entities: List[str] = None,
        count: int = 10,
        asset_type: str = "both"  # "video", "image", or "both"
    ) -> List[ScrapedAsset]:
        """
        Main entry point: scrape media for a topic.

        Args:
            topic: Main topic (e.g., "armored vehicle", "military exercise")
            entities: Related entities for better search
            count: Number of assets to find
            asset_type: "video", "image", or "both"

        Returns:
            List of ScrapedAsset objects
        """
        entities = entities or []
        assets = []

        # Build search queries
        queries = self._build_queries(topic, entities)

        # Scrape from multiple sources
        if asset_type in ("video", "both") and PEXELS_API_KEY:
            for query in queries:
                video_assets = self._scrape_pexels_videos(query, count=count // len(queries) + 1)
                assets.extend(video_assets)
                time.sleep(0.5)  # Rate limiting
                if len(assets) >= count:
                    break

        if asset_type in ("image", "both"):
            for query in queries:
                # Try Pexels images first (if API key available)
                if PEXELS_API_KEY:
                    img_assets = self._scrape_pexels_images(query, count=count // len(queries) + 1)
                    assets.extend(img_assets)
                    time.sleep(0.5)

                # Always try Wikimedia (free, no API key needed)
                wiki_assets = self._scrape_wikimedia(query, count=count // len(queries) + 1)
                assets.extend(wiki_assets)
                time.sleep(0.3)

                if len(assets) >= count:
                    break

        # Download all assets
        downloaded = []
        for asset in assets[:count]:
            try:
                local_path = self._download_asset(asset)
                if local_path:
                    asset.file_path = str(local_path)
                    downloaded.append(asset)
                    log.info(f"  Downloaded: {asset.type} - {asset.topic[:40]}")
            except Exception as e:
                log.warning(f"  Download failed: {e}")

        return downloaded

    def _build_queries(self, topic: str, entities: List[str]) -> List[str]:
        """Build effective search queries from topic + entities."""
        queries = []

        # Main topic query
        queries.append(topic)

        # Entity-augmented queries
        for entity in entities[:3]:
            queries.append(f"{topic} {entity}")

        # Niche-specific additions
        queries.append(f"{topic} high quality")
        queries.append(f"{topic} footage")

        return queries[:5]  # Limit queries

    # ============================================================
    # PEXELS VIDEO SCRAPER
    # ============================================================

    def _scrape_pexels_videos(self, query: str, count: int = 5) -> List[ScrapedAsset]:
        """Search Pexels for free stock videos."""
        if not PEXELS_API_KEY:
            return []

        assets = []
        try:
            url = f"{PEXELS_API_URL}/search"
            params = {
                "query": query,
                "per_page": min(count, 15),
                "orientation": "landscape"
            }
            headers = {"Authorization": PEXELS_API_KEY}

            response = self.session.get(url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()

            for i, video in enumerate(data.get("videos", [])):
                # Get best quality file
                files = video.get("video_files", [])
                if not files:
                    continue

                # Prefer HD or higher
                best_file = max(files, key=lambda f: f.get("width", 0))

                asset_id = f"PEX_VID_{video.get('id', i)}_{int(time.time())}"

                assets.append(ScrapedAsset(
                    id=asset_id,
                    type="video",
                    file_path="",
                    source_type="pexels",
                    source_url=video.get("url", ""),
                    download_url=best_file.get("link", ""),
                    topic=query,
                    description=video.get("url", ""),
                    tags=[t for t in video.get("tags", [])],
                    width=best_file.get("width", 0),
                    height=best_file.get("height", 0),
                    duration=best_file.get("duration", 0),
                    thumbnail_url=video.get("image", ""),
                    photographer=video.get("user", {}).get("name", ""),
                    created_at=video.get("created_at", "")
                ))

        except Exception as e:
            log.warning(f"Pexels video search failed for '{query}': {e}")

        return assets

    # ============================================================
    # PEXELS IMAGE SCRAPER
    # ============================================================

    def _scrape_pexels_images(self, query: str, count: int = 5) -> List[ScrapedAsset]:
        """Search Pexels for free stock photos."""
        if not PEXELS_API_KEY:
            return []

        assets = []
        try:
            url = f"{PEXELS_API_URL}/search"
            params = {
                "query": query,
                "per_page": min(count, 15),
                "orientation": "landscape"
            }
            headers = {"Authorization": PEXELS_API_KEY}

            response = self.session.get(url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()

            for i, photo in enumerate(data.get("photos", [])):
                # Get large size
                src = photo.get("src", {})
                download_url = src.get("large", src.get("original", ""))
                thumb_url = src.get("medium", src.get("small", ""))

                asset_id = f"PEX_IMG_{photo.get('id', i)}_{int(time.time())}"

                assets.append(ScrapedAsset(
                    id=asset_id,
                    type="image",
                    file_path="",
                    source_type="pexels",
                    source_url=photo.get("url", ""),
                    download_url=download_url,
                    topic=query,
                    description=photo.get("alt", ""),
                    tags=[t for t in photo.get("tags", [])],
                    width=photo.get("width", 0),
                    height=photo.get("height", 0),
                    thumbnail_url=thumb_url,
                    photographer=photo.get("photographer", ""),
                    created_at=photo.get("created_at", "")
                ))

        except Exception as e:
            log.warning(f"Pexels image search failed for '{query}': {e}")

        return assets

    # ============================================================
    # WIKIMEDIA COMMONS SCRAPER
    # ============================================================

    def _scrape_wikimedia(self, query: str, count: int = 5) -> List[ScrapedAsset]:
        """Search Wikimedia Commons for free images."""
        assets = []

        try:
            # Step 1: Search for files
            search_params = {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrnamespace": "6",  # File namespace
                "gsrsearch": f"intitle:{quote(query)} filetype:jpg|png|svg",
                "gsrlimit": count * 2,
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": "1920"
            }

            response = self.session.get(WIKIMEDIA_API_URL, params=search_params, timeout=15)
            response.raise_for_status()
            data = response.json()

            pages = data.get("query", {}).get("pages", {})

            for page_id, page in pages.items():
                if "imageinfo" not in page:
                    continue

                info = page["imageinfo"][0]
                ext_meta = {m.get("name", ""): m.get("*", "")
                           for m in info.get("extmetadata", {}).values()}

                # Filter: only images, prefer larger ones
                mime = info.get("mime", "")
                if mime not in ("image/jpeg", "image/png", "image/webp"):
                    continue

                # Get best available URL
                thumb_url = info.get("thumburl", info.get("url", ""))

                # Extract license
                license_info = ext_meta.get("LicenseShortName", ext_meta.get("License", ""))
                if not license_info:
                    license_info = ext_meta.get("Attribution", "CC")

                asset_id = f"WIKI_{page.get('pageid', page_id)}_{int(time.time())}"

                assets.append(ScrapedAsset(
                    id=asset_id,
                    type="image",
                    file_path="",
                    source_type="wikimedia",
                    source_url=info.get("descriptionurl", ""),
                    download_url=info.get("url", ""),
                    topic=query,
                    description=page.get("extract", "")[:200],
                    entities=[],
                    tags=[],
                    width=info.get("thumbwidth", info.get("width", 0)),
                    height=info.get("thumbheight", info.get("height", 0)),
                    thumbnail_url=thumb_url,
                    license=license_info,
                    created_at=ext_meta.get("DateTime", "")
                ))

                if len(assets) >= count:
                    break

        except Exception as e:
            log.warning(f"Wikimedia search failed for '{query}': {e}")

        return assets

    # ============================================================
    # YOUTUBE THUMBNAIL SCRAPER
    # ============================================================

    def get_youtube_thumbnail(
        self,
        video_id: str,
        quality: str = "maxresdefault"
    ) -> Optional[ScrapedAsset]:
        """
        Get a YouTube video thumbnail (free to use).

        Quality options:
        - maxresdefault: 1280x720 (best)
        - sddefault: 640x480
        - hqdefault: 480x360
        - mqdefault: 320x180
        """
        url = f"https://i.ytimg.com/{quality}/{video_id}.jpg"

        try:
            response = self.session.head(url, timeout=10)
            if response.status_code == 200:
                return ScrapedAsset(
                    id=f"YT_THUMB_{video_id}",
                    type="image",
                    file_path="",
                    source_type="youtube_thumb",
                    source_url=f"https://youtube.com/watch?v={video_id}",
                    download_url=url,
                    topic="",
                    thumbnail_url=url,
                    width=1280 if quality == "maxresdefault" else 640,
                    height=720 if quality == "maxresdefault" else 480
                )
        except Exception as e:
            log.warning(f"YouTube thumbnail fetch failed for {video_id}: {e}")

        return None

    # ============================================================
    # ASSET DOWNLOAD
    # ============================================================

    def _download_asset(self, asset: ScrapedAsset) -> Optional[Path]:
        """Download asset to local storage."""
        if not asset.download_url:
            return None

        # Determine file extension
        url_path = asset.download_url.split("?")[0]
        ext = Path(url_path).suffix or (".mp4" if asset.type == "video" else ".jpg")

        # Create filename
        safe_id = re.sub(r'[^\w\-]', '_', asset.id)[:30]
        filename = f"{safe_id}{ext}"
        filepath = self.output_dir / filename

        # Skip if already downloaded
        if filepath.exists() and filepath.stat().st_size > 1000:
            log.debug(f"  Already exists: {filename}")
            return filepath

        # Download
        try:
            response = self.session.get(
                asset.download_url,
                timeout=60,
                stream=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible)"}
            )
            response.raise_for_status()

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            log.info(f"  Downloaded: {filename} ({filepath.stat().st_size / 1024:.1f} KB)")
            return filepath

        except Exception as e:
            log.warning(f"  Download failed for {asset.id}: {e}")
            if filepath.exists():
                filepath.unlink()
            return None

    # ============================================================
    # TOPIC ANALYSIS (for better search queries)
    # ============================================================

    def analyze_topic(self, narration_text: str) -> Dict:
        """
        Analyze narration to extract topics and entities for targeted scraping.
        Returns dict with 'topic', 'entities', 'asset_type' recommendations.
        """
        # Simple keyword extraction (can be enhanced with NLP)
        text_lower = narration_text.lower()

        # Military/defence keywords
        military_vehicles = ["tank", "armored", "apc", "ifv", "helicopter", "jet",
                            "fighter", "aircraft", "warship", "submarine", "drone"]
        military_actions = ["exercise", "deployment", "operation", "patrol",
                           "demonstration", "test", "launch"]
        locations = ["map", "australia", "germany", "united states", "ukraine",
                    "middle east", "pacific", "ocean", "forest", "desert"]

        entities = []
        asset_type = "both"

        # Check for vehicle mentions
        for v in military_vehicles:
            if v in text_lower:
                entities.append(v)

        # Check for locations
        for loc in locations:
            if loc in text_lower:
                entities.append(loc)

        # Determine primary topic
        if any(w in text_lower for w in ["demonstrate", "show", "capability"]):
            topic = " ".join(entities[:2]) if entities else "military equipment"
        elif any(w in text_lower for w in ["exercise", "training", "drill"]):
            topic = "military exercise"
            asset_type = "video"
        elif any(w in text_lower for w in ["map", "located", "country"]):
            topic = "map"
            asset_type = "image"
        elif any(w in text_lower for w in ["born", "history", "founded"]):
            topic = " ".join(entities[:2]) if entities else "history"
            asset_type = "image"
        else:
            topic = " ".join(entities[:2]) if entities else "military"

        return {
            "topic": topic,
            "entities": entities,
            "asset_type": asset_type,
            "needs_scraping": True
        }

    # ============================================================
    # BATCH OPERATIONS
    # ============================================================

    def scrape_for_beats(
        self,
        beats: List[Dict],
        assets_per_beat: int = 2
    ) -> List[ScrapedAsset]:
        """
        Scrape assets for multiple narration beats.

        Args:
            beats: List of beat dicts with 'narration_verbatim' key
            assets_per_beat: Max assets to fetch per beat

        Returns:
            Combined list of all scraped assets
        """
        all_assets = []
        seen_urls = set()

        for i, beat in enumerate(beats):
            narration = beat.get("narration_verbatim", "")
            if not narration:
                continue

            log.info(f"Scraping assets for beat {i+1}/{len(beats)}: {narration[:50]}...")

            # Analyze narration
            analysis = self.analyze_topic(narration)

            # Scrape
            assets = self.scrape_for_topic(
                topic=analysis["topic"],
                entities=analysis["entities"],
                count=assets_per_beat,
                asset_type=analysis["asset_type"]
            )

            # Deduplicate
            new_assets = []
            for a in assets:
                if a.download_url not in seen_urls:
                    seen_urls.add(a.download_url)
                    new_assets.append(a)

            all_assets.extend(new_assets)
            log.info(f"  Found {len(new_assets)} new assets")

        return all_assets


# ============================================================
# SCRAPER-CATALOGER INTEGRATION
# ============================================================

class ScraperCataloger:
    """
    Combines scraping + cataloging into one workflow.
    Scrapes assets, then auto-catalogs them with Gemini.
    """

    def __init__(self, scraper: ScraperEngine = None):
        self.scraper = scraper or ScraperEngine()

    def get_assets_for_script(
        self,
        beats: List[Dict],
        library_search_fn = None
    ) -> List[ScrapedAsset]:
        """
        Get assets for all beats, checking library first.

        Args:
            beats: List of beat dicts
            library_search_fn: Callable to search existing library

        Returns:
            List of assets ready for use (from library or freshly scraped)
        """
        from CODE.demandscout_core import Beat

        all_assets = []
        needs_scraping = []

        # Step 1: Check library for each beat
        for beat_data in beats:
            narration = beat_data.get("narration_verbatim", "")
            entities = beat_data.get("entities", [])

            # Search library first
            if library_search_fn:
                library_hits = library_search_fn(narration, entities, count=3)
                if library_hits:
                    all_assets.extend(library_hits)
                    continue

            # Nothing in library — needs scraping
            needs_scraping.append(beat_data)

        # Step 2: Scrape for missing beats
        if needs_scraping:
            log.info(f"Library coverage: {len(all_assets)} hits, "
                    f"scraping for {len(needs_scraping)} beats")

            scraped = self.scraper.scrape_for_beats(needs_scraping)
            all_assets.extend(scraped)

        return all_assets
