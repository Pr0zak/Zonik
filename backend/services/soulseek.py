"""Soulseek download service via slskd API with multi-strategy search."""
from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass

import httpx

from backend.config import get_settings

log = logging.getLogger(__name__)

PREFERRED_EXTENSIONS = [".flac", ".wav", ".alac", ".mp3", ".m4a", ".ogg", ".opus"]
MIN_FILE_SIZE = 3 * 1024 * 1024  # 3MB


# --- Text matching utilities (ported from web-ui.py) ---

def normalize_text(text: str) -> str:
    """Normalize text for matching - strip accents, replace separators, lowercase."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    normalized = re.sub(r"[._\-\(\)\[\]]", " ", ascii_text)
    normalized = re.sub(r"[^\w\s]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return normalized


def words_match(needle: str, haystack: str) -> bool:
    """Check if most words in needle appear in haystack (fuzzy word-level match)."""
    needle_words = normalize_text(needle).split()
    haystack_norm = normalize_text(haystack)
    if not needle_words:
        return False
    matched = sum(1 for w in needle_words if w in haystack_norm)
    return matched >= max(1, len(needle_words) * 0.7)


def strip_track_extras(title: str) -> str:
    """Remove feat., remix, parenthetical info from track name for search."""
    t = re.sub(r"\s*[\(\[](?:feat\.|ft\.|prod\.|with |from ).*?[\)\]]", "", title, flags=re.IGNORECASE)
    t = re.sub(r"\s*[\(\[].*?(?:remix|mix|version|edit|remaster).*?[\)\]]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*(?:feat\.|ft\.).*$", "", t, flags=re.IGNORECASE)
    return t.strip()


def clean_track_name(raw: str) -> str:
    """Clean YouTube/video metadata from track names."""
    cleaned = raw
    for p in [
        r"\s*\(Official[^)]*\)", r"\s*\[Official[^]]*\]", r"\s*\(Lyric[^)]*\)",
        r"\s*\(Audio\)", r"\s*\[Ultra Records\]", r"\s*\(from\s*[^)]*\)",
        r'\s*from\s*\("[^"]*"\)', r"\s*-\s*Official\s+(Music\s+)?Video",
        r"\s*\(Live[^)]*\)", r"\s*\(\d{4}\s+Remastered\)",
    ]:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def clean_artist_name(artist: str) -> str:
    """Take first artist if multiple."""
    for sep in [" / ", " & ", ", ", " x ", " X "]:
        if sep in artist:
            return artist.split(sep)[0].strip()
    return artist


# --- Quality scoring ---

def pick_best_results(results: list[dict], artist: str, track: str) -> list[dict]:
    """Pick the best downloads from Soulseek search results with fuzzy matching."""
    settings = get_settings()
    min_size = settings.soulseek.min_file_size_mb * 1024 * 1024

    scored = []
    for r in results:
        filename = r.get("filename") or ""
        filepath = r.get("path") or ""
        full_path = filepath + "/" + filename
        size = r.get("size", 0)

        if size < min_size:
            continue

        ext = ""
        for e in PREFERRED_EXTENSIONS:
            if filename.lower().endswith(e):
                ext = e
                break
        if not ext:
            continue

        score = 0
        # Fuzzy artist match (check full path)
        if words_match(artist, full_path):
            score += 10
        # Fuzzy track match (check filename)
        if words_match(track, filename):
            score += 10
        elif words_match(strip_track_extras(track), filename):
            score += 8

        # Format scoring
        if ext == ".flac":
            score += 20
        elif ext in (".wav", ".alac"):
            score += 18
        elif ext == ".mp3":
            score += 5
        elif ext in (".m4a", ".ogg", ".opus"):
            score += 3

        # Size scoring
        if size > 30 * 1024 * 1024:
            score += 8
        elif size > 15 * 1024 * 1024:
            score += 5
        elif size > 8 * 1024 * 1024:
            score += 3

        # Bitrate scoring
        bitrate = r.get("bitRate", 0) or r.get("bitrate", 0)
        if bitrate >= 320:
            score += 5
        elif bitrate >= 256:
            score += 3

        if score > 0:
            scored.append((score, r))

    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)

    # Deduplicate by user (one result per peer)
    seen_users: set[str] = set()
    candidates = []
    for _score, r in scored:
        user = r.get("username", "")
        if user not in seen_users:
            seen_users.add(user)
            candidates.append(r)
        if len(candidates) >= 5:
            break
    return candidates


# --- slskd API client ---

@dataclass
class SlskdClient:
    base_url: str
    api_key: str

    def _headers(self) -> dict:
        return {"X-API-Key": self.api_key, "Content-Type": "application/json"}

    async def search(self, query: str, timeout: int = 15) -> list[dict]:
        """Start a search and poll for results."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Start search
            resp = await client.post(
                f"{self.base_url}/api/v0/searches",
                headers=self._headers(),
                json={"searchText": query},
            )
            if resp.status_code != 201:
                log.warning(f"slskd search failed: {resp.status_code} {resp.text[:200]}")
                return []

            search_data = resp.json()
            search_id = search_data.get("id")
            if not search_id:
                return []

            # Poll for results
            all_files = []
            for _ in range(timeout // 2):
                await asyncio.sleep(2)
                resp = await client.get(
                    f"{self.base_url}/api/v0/searches/{search_id}",
                    headers=self._headers(),
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                responses = data.get("responses", [])
                for response in responses:
                    username = response.get("username", "")
                    for file in response.get("files", []):
                        file["username"] = username
                        all_files.append(file)

                state = data.get("state", "")
                if state in ("Completed", "TimedOut"):
                    break

            # Clean up search
            try:
                await client.delete(
                    f"{self.base_url}/api/v0/searches/{search_id}",
                    headers=self._headers(),
                )
            except Exception:
                pass

            return all_files

    async def download(self, username: str, filename: str) -> dict:
        """Initiate a download from a specific user."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/api/v0/transfers/downloads/{username}",
                headers=self._headers(),
                json=[{"filename": filename}],
            )
            if resp.status_code in (200, 201):
                return {"ok": True}
            log.warning(f"slskd download failed: {resp.status_code} {resp.text[:200]}")
            return {"error": resp.text[:200]}

    async def get_download_status(self, username: str, filename: str) -> dict | None:
        """Check download progress."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base_url}/api/v0/transfers/downloads/{username}",
                headers=self._headers(),
            )
            if resp.status_code != 200:
                return None
            transfers = resp.json()
            for t in transfers:
                for f in t.get("files", []):
                    if f.get("filename") == filename:
                        return f
        return None

    async def get_all_downloads(self) -> list[dict]:
        """Get all active downloads."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base_url}/api/v0/transfers/downloads",
                headers=self._headers(),
            )
            if resp.status_code != 200:
                return []
            return resp.json()


def get_slskd_client() -> SlskdClient:
    settings = get_settings()
    return SlskdClient(
        base_url=settings.soulseek.slskd_url,
        api_key=settings.soulseek.slskd_api_key,
    )


# --- Multi-strategy search ---

async def search_multi_strategy(artist: str, track: str) -> list[dict]:
    """Try multiple search strategies, return best candidates."""
    client = get_slskd_client()

    queries = [f"{artist} {track}"]
    cleaned_track = strip_track_extras(track)
    cleaned_artist = clean_artist_name(artist)
    q2 = f"{cleaned_artist} {cleaned_track}"
    if q2 != queries[0]:
        queries.append(q2)
    # Track-only (for Soulseek-blocked artists)
    if len(cleaned_track.split()) >= 2:
        queries.append(cleaned_track)
    # First word of artist + track
    first_artist = artist.split()[0] if artist.split() else artist
    if first_artist.lower() != cleaned_artist.lower():
        queries.append(f"{first_artist} {cleaned_track}")

    seen: set[str] = set()
    for q in queries:
        if q in seen:
            continue
        seen.add(q)
        log.info(f"Soulseek search strategy: '{q}'")
        results = await client.search(q)
        if results:
            candidates = pick_best_results(results, artist, track)
            if candidates:
                return candidates

    return []


async def search_and_download(artist: str, track: str) -> dict:
    """Search for a track and download the best result, with candidate fallback."""
    candidates = await search_multi_strategy(artist, track)
    if not candidates:
        return {"status": "not_found", "message": f"No results for {artist} - {track}"}

    client = get_slskd_client()
    last_error = "Download failed"

    for i, candidate in enumerate(candidates):
        username = candidate.get("username", "")
        filename = candidate.get("filename", "")

        log.info(f"Download attempt {i+1}/{len(candidates)}: {username} - {filename}")
        result = await client.download(username, filename)
        if result.get("ok"):
            return {
                "status": "downloading",
                "username": username,
                "filename": filename,
                "size": candidate.get("size", 0),
                "attempt": i + 1,
            }
        last_error = result.get("error", "Download failed")
        log.warning(f"Download attempt {i+1} failed ({username}): {last_error}")

    return {"status": "failed", "message": f"All {len(candidates)} candidates failed: {last_error}"}
