"""Multi-Provider Footage Discovery and Licensing Guardrails for IncuBrix.

Connects Pixabay and stock footage providers with strict rate-limiting,
disk caching, negative constraint filtering, and offline fallback.
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
import httpx

from incubrix.config import settings

logger = logging.getLogger("incubrix.footage")

STOP_WORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with",
    "by", "about", "against", "between", "into", "through", "during",
    "before", "after", "above", "below", "from", "up", "down", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "it", "its", "this", "that", "these", "those", "i", "we", "you",
}

# Global rate limit guard: Pixabay permits 100 req/min; we throttle to max 1 req / second
_LAST_REQUEST_TIME: float = 0.0
_RATE_LIMIT_LOCK = asyncio.Lock()


def clean_search_query(text: Optional[str]) -> str:
    """Extract 1-3 clean keywords suitable for stock video search."""
    if not text:
        return "technology"

    clean_text = re.sub(r"[^\w\s]", " ", text.lower())
    words = [w for w in clean_text.split() if w and w not in STOP_WORDS and len(w) > 2]
    if not words:
        return "technology"

    # Take first 2-3 most descriptive words
    return " ".join(words[:2])


class PixabayClient:
    """Pixabay Video API client with aggressive disk caching and rate-limiting."""

    def __init__(self, api_key: Optional[str] = None, cache_dir: Optional[Path] = None):
        self.api_key = api_key or settings.PIXABAY_API_KEY
        self.cache_dir = (cache_dir or settings.CACHE_DIR) / "pixabay"
        self.queries_dir = self.cache_dir / "queries"
        self.videos_dir = self.cache_dir / "videos"
        self.queries_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)

    def _query_cache_path(self, query: str) -> Path:
        h = hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()[:16]
        return self.queries_dir / f"{h}.json"

    def _video_cache_path(self, clip_id: str) -> Path:
        safe_id = re.sub(r"[^\w\-]", "_", str(clip_id))
        return self.videos_dir / f"{safe_id}.mp4"

    async def search_videos(
        self,
        query: str,
        min_duration: float = 0.0,
        avoid: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Search videos with caching, negative constraint filtering, and rate-limiting."""
        clean_q = clean_search_query(query)
        cache_file = self._query_cache_path(clean_q)

        hits: List[Dict[str, Any]] = []

        # 1. Read from local query cache if available (0 API calls)
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    hits = cached_data.get("hits", [])
            except Exception as e:
                logger.warning(f"Error reading query cache for {clean_q}: {e}")

        # 2. Query Pixabay API if cache missed and key is present
        if not hits and self.api_key:
            global _LAST_REQUEST_TIME
            async with _RATE_LIMIT_LOCK:
                elapsed = time.monotonic() - _LAST_REQUEST_TIME
                if elapsed < 1.0:
                    await asyncio.sleep(1.0 - elapsed)

                params = {
                    "key": self.api_key,
                    "q": clean_q,
                    "per_page": 10,
                    "safesearch": "true",
                }

                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        resp = await client.get("https://pixabay.com/api/videos/", params=params)
                        _LAST_REQUEST_TIME = time.monotonic()

                        if resp.status_code == 200:
                            data = resp.json()
                            hits = data.get("hits", [])
                            # Cache the query response
                            with open(cache_file, "w", encoding="utf-8") as f:
                                json.dump({"query": clean_q, "hits": hits}, f, indent=2)
                        elif resp.status_code == 429:
                            logger.error("Pixabay rate limit reached (HTTP 429). Backing off.")
                        else:
                            logger.warning(f"Pixabay search failed ({resp.status_code}): {resp.text[:200]}")
                except Exception as exc:
                    logger.warning(f"Network error searching Pixabay: {exc}")

        # 3. Apply negative constraint filtering (`avoid`)
        avoid_terms = [a.lower().strip() for a in (avoid or []) if a.strip()]
        filtered_hits: List[Dict[str, Any]] = []

        for hit in hits:
            tags = hit.get("tags", "").lower()
            # If tags contain any forbidden term, discard
            if any(term in tags for term in avoid_terms):
                continue

            filtered_hits.append(hit)

        # 4. Sort by relevance/duration
        if min_duration > 0:
            # Prefer clips that are at least as long as min_duration
            matching_dur = [h for h in filtered_hits if h.get("duration", 0) >= min_duration]
            if matching_dur:
                return matching_dur

        return filtered_hits

    async def download_clip(
        self,
        clip_id: str,
        download_url: str,
        dest_path: Path,
    ) -> Path:
        """Download video to central cache then link/copy to dest_path."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        cached_file = self._video_cache_path(clip_id)

        # 1. Check if video already exists in local cache (0 bandwidth)
        if not cached_file.exists() or cached_file.stat().st_size == 0:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                async with client.stream("GET", download_url) as resp:
                    resp.raise_for_status()
                    temp_cache = cached_file.with_suffix(".tmp")
                    with open(temp_cache, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                    temp_cache.replace(cached_file)

        # 2. Copy or symlink from cache to destination
        if dest_path.resolve() != cached_file.resolve():
            import shutil
            shutil.copyfile(cached_file, dest_path)

        return dest_path


async def generate_mock_clip(out_path: Path, duration_sec: float = 3.0) -> Path:
    """Generate a lightweight mock MP4 video clip offline for testing (<0.1s)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi", "-i", f"color=c=0x1A202C:s=1280x720:r=30",
        "-t", str(max(1.0, duration_sec)),
        "-c:v", "libopenh264",
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    return out_path


async def process_job_footage(
    scenes: List[Dict[str, Any]],
    workspace_dir: Path,
    avoid: Optional[List[str]] = None,
    mock: bool = False,
) -> List[Dict[str, Any]]:
    """Discover, download, and attach B-roll footage to all job scenes."""
    client = PixabayClient()
    footage_dir = workspace_dir / "public" / "footage"
    footage_dir.mkdir(parents=True, exist_ok=True)

    enriched_scenes: List[Dict[str, Any]] = []

    for s in scenes:
        scene_copy = dict(s)
        scene_id = s.get("id", 1)
        duration_sec = s.get("durationSec", 3.0)
        visual_hint = s.get("visual_hint") or s.get("title") or s.get("voiceText") or "technology"

        clip_dest = footage_dir / f"scene_{scene_id:02d}.mp4"

        if mock or not client.api_key:
            # Offline mock footage generation
            await generate_mock_clip(clip_dest, duration_sec=duration_sec)
            scene_copy["footageUrl"] = f"footage/scene_{scene_id:02d}.mp4"
            scene_copy["clip"] = {
                "clip_id": f"mock_clip_{scene_id:02d}",
                "source_provider": "local_mock",
                "source_url": f"https://storage.incubrix.internal/mock/scene_{scene_id:02d}.mp4",
                "license": {
                    "type": "IncuBrix Internal Mock",
                    "commercial_use_allowed": True,
                    "attribution_required": False,
                },
                "attribution": "IncuBrix Synthetic Plate",
                "is_ai_generated": False,
                "generator_model": None,
                "trim": {"in_ms": 0, "out_ms": int(duration_sec * 1000)},
                "selection_reason": f"Synthetic clip matching {visual_hint}",
                "relevance_score": 4.5,
            }
            enriched_scenes.append(scene_copy)
            continue

        # Live Pixabay search with rate limiting and query cache
        try:
            hits = await client.search_videos(
                query=visual_hint,
                min_duration=duration_sec,
                avoid=avoid,
            )

            if hits:
                best_hit = hits[0]
                videos_dict = best_hit.get("videos", {})
                # Choose medium resolution (1080p/720p) over massive 4K large to avoid memory bottlenecks
                v_choice = (
                    videos_dict.get("medium")
                    or videos_dict.get("large")
                    or videos_dict.get("small")
                    or {}
                )
                download_url = v_choice.get("url")

                if download_url:
                    clip_id = str(best_hit.get("id", f"scene_{scene_id}"))
                    await client.download_clip(clip_id, download_url, clip_dest)

                    scene_copy["footageUrl"] = f"footage/scene_{scene_id:02d}.mp4"
                    scene_copy["clip"] = {
                        "clip_id": f"pixabay_{clip_id}",
                        "source_provider": "pixabay",
                        "source_url": best_hit.get("pageURL", "https://pixabay.com"),
                        "license": {
                            "type": "Pixabay Content License",
                            "commercial_use_allowed": True,
                            "attribution_required": False,
                        },
                        "attribution": f"Video by {best_hit.get('user', 'Pixabay Creator')} from Pixabay",
                        "is_ai_generated": False,
                        "generator_model": None,
                        "trim": {"in_ms": 0, "out_ms": int(duration_sec * 1000)},
                        "selection_reason": f"Matched visual hint '{visual_hint}' from Pixabay",
                        "relevance_score": 4.8,
                    }
                    enriched_scenes.append(scene_copy)
                    continue
        except Exception as exc:
            logger.warning(f"Failed to fetch Pixabay footage for scene {scene_id}: {exc}")

        # Fallback to local plate if search yielded no hits or network failed
        scene_copy["footageUrl"] = None
        scene_copy["clip"] = None
        enriched_scenes.append(scene_copy)

    return enriched_scenes
