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

# Letters NFKD can't decompose to ASCII (stroke / ligature / eth / thorn). Fold
# them explicitly so an accented title still matches an uploader's ASCII filename
# (e.g. "Tøyen" vs "Toyen", "Mötley Crüe" works via NFKD but "Mø" needs this).
_TRANSLIT = str.maketrans({
    "ø": "o", "Ø": "o", "ł": "l", "Ł": "l", "đ": "d", "Đ": "d",
    "þ": "th", "Þ": "th", "ð": "d", "Ð": "d", "æ": "ae", "Æ": "ae",
    "œ": "oe", "Œ": "oe", "ß": "ss",
})


def normalize_text(text: str) -> str:
    """Normalize text for matching - strip accents, replace separators, lowercase."""
    text = text.translate(_TRANSLIT)
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


# Stopwords + noise tokens dropped before requiring a title match. Keeping these
# would let a different song match just by sharing "the" / "remix" / etc.
TITLE_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with",
    "feat", "ft", "prod", "remix", "edit", "version", "remaster", "remastered",
    "mix", "radio", "original", "official", "explicit", "clean", "bonus", "track",
    "single", "ep", "lp",
}


def title_matches(track_title: str, filename: str) -> bool:
    """Hard gate: does this candidate file actually look like the target title?

    Word-boundary match (NOT substring — so "faith" won't match "faithless") on
    the significant, non-stopword, non-numeric words of the title against the
    candidate's *basename*. Titles of 1-2 significant words must match in full;
    longer titles need >= ~80%. This stops the downloader picking a high-quality
    file of a completely different song that merely outscores the correct file on
    format / peer-quality points. Recall is intentionally traded for precision —
    on this single-user box a missed upgrade is far cheaper than a wrong one.
    """
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", base)  # drop extension
    hay = set(normalize_text(base).split())
    if not hay:
        return False
    title_words = normalize_text(strip_track_extras(track_title)).split()
    sig = [w for w in title_words if w not in TITLE_STOPWORDS and not w.isdigit()]
    if not sig:
        # Title was all stopwords / numbers — fall back so we don't reject everything.
        sig = [w for w in title_words if not w.isdigit()] or title_words
    if not sig:
        return False
    matched = sum(1 for w in sig if w in hay)
    if len(sig) <= 2:
        return matched == len(sig)
    return matched >= max(2, round(len(sig) * 0.8))


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

        # HARD GATE: the candidate filename must actually contain the target title.
        if not title_matches(track, filename):
            continue

        score = 0
        # Fuzzy artist match (check full path)
        if words_match(artist, full_path):
            score += 12
        # Track match strength (gate already passed; grade full vs extras-stripped)
        if words_match(track, filename):
            score += 15
        else:
            score += 10

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
            if resp.status_code not in (200, 201):
                log.warning(f"slskd search failed: {resp.status_code} {resp.text[:200]}")
                return []

            search_data = resp.json()
            search_id = search_data.get("id")
            if not search_id:
                return []

            # Poll for completion
            for _ in range(timeout // 2):
                await asyncio.sleep(2)
                resp = await client.get(
                    f"{self.base_url}/api/v0/searches/{search_id}",
                    headers=self._headers(),
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                state = data.get("state", "")
                if "Completed" in state or "TimedOut" in state:
                    break

            # Fetch results from responses sub-endpoint
            all_files = []
            resp = await client.get(
                f"{self.base_url}/api/v0/searches/{search_id}/responses",
                headers=self._headers(),
            )
            if resp.status_code == 200:
                responses = resp.json()
                for response in responses:
                    username = response.get("username", "")
                    for file in response.get("files", []):
                        file["username"] = username
                        all_files.append(file)

            # Clean up search
            try:
                await client.delete(
                    f"{self.base_url}/api/v0/searches/{search_id}",
                    headers=self._headers(),
                )
            except Exception as e:
                log.debug("Failed to clean up slskd search %s: %s", search_id, e)

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
        base_url=settings.soulseek.slskd_url.rstrip("/"),
        api_key=settings.soulseek.slskd_api_key,
    )


# --- Multi-strategy search ---

def _use_native() -> bool:
    """Check if native Soulseek client is running."""
    from backend.soulseek import get_client
    client = get_client()
    return client is not None and client.logged_in


async def search_multi_strategy(artist: str, track: str) -> list[dict]:
    """Try multiple search strategies, return best candidates.
    Routes to native client or slskd based on config.
    """
    if _use_native():
        from backend.soulseek import get_client
        from backend.soulseek.search import search_multi_strategy_native
        return await search_multi_strategy_native(get_client(), artist, track)

    # Legacy slskd path
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
    """Search for a track and download the best result, with candidate fallback.
    Routes to native client or slskd based on config.
    """
    if _use_native():
        from backend.soulseek import get_client
        from backend.soulseek.search import search_and_download_native
        return await search_and_download_native(get_client(), artist, track)

    # Native client is unavailable in this process (not logged in, or this is the
    # worker which runs no client). The legacy slskd fallback is DECOMMISSIONED, so
    # fail clearly instead of hammering a dead slskd host with an opaque
    # "All connection attempts failed". Downloads should be delegated to the web
    # process (see backend.api.download.enqueue_download), which owns the client.
    log.warning(
        f"[download] No native Soulseek client for '{artist} - {track}' "
        f"(logged_in=False); slskd fallback is decommissioned"
    )
    return {
        "status": "error",
        "message": "Soulseek native client not available (not logged in); "
                   "slskd fallback is decommissioned",
    }
