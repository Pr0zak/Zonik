"""Lidarr API wrapper for search, add album, monitor."""
from __future__ import annotations

import logging

import httpx

from backend.config import get_settings

log = logging.getLogger(__name__)


class LidarrClient:
    def __init__(self):
        settings = get_settings()
        self.base_url = settings.lidarr.url.rstrip("/")
        self.api_key = settings.lidarr.api_key
        self.root_folder = settings.lidarr.root_folder

    def _headers(self) -> dict:
        return {"X-Api-Key": self.api_key, "Content-Type": "application/json"}

    async def search_artist(self, term: str) -> list[dict]:
        """Search for an artist in Lidarr."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/artist/lookup",
                params={"term": term},
                headers=self._headers(),
            )
            if resp.status_code != 200:
                return []
            return resp.json()

    async def search_album(self, term: str) -> list[dict]:
        """Search for an album in Lidarr."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/album/lookup",
                params={"term": term},
                headers=self._headers(),
            )
            if resp.status_code != 200:
                return []
            return resp.json()

    async def get_artists(self) -> list[dict]:
        """Get all artists in Lidarr."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/artist",
                headers=self._headers(),
            )
            if resp.status_code != 200:
                return []
            return resp.json()

    async def get_artist_names(self) -> set[str]:
        """Get set of all artist names currently in Lidarr (lowercased)."""
        artists = await self.get_artists()
        return {a.get("artistName", "").lower() for a in artists}

    async def add_artist(self, foreign_artist_id: str, artist_name: str, monitor: str = "none") -> dict:
        """Add an artist to Lidarr."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/artist",
                headers=self._headers(),
                json={
                    "foreignArtistId": foreign_artist_id,
                    "artistName": artist_name,
                    "qualityProfileId": 1,
                    "metadataProfileId": 1,
                    "rootFolderPath": self.root_folder,
                    "monitored": True,
                    "monitorNewItems": monitor,
                    "addOptions": {"monitor": monitor, "searchForMissingAlbums": monitor != "none"},
                },
            )
            if resp.status_code in (200, 201):
                return resp.json()
            log.warning(f"Lidarr add artist failed: {resp.status_code} {resp.text[:200]}")
            return {"error": resp.text[:200]}

    async def add_album(self, foreign_album_id: str, artist_data: dict) -> dict:
        """Add a specific album to Lidarr via the artist endpoint."""
        async with httpx.AsyncClient(timeout=30) as client:
            # First ensure the artist exists
            artist_id = artist_data.get("foreignArtistId", "")
            artist_name = artist_data.get("artistName", "")

            # Check if artist is already in Lidarr
            existing = await self.get_artists()
            artist_exists = any(a.get("foreignArtistId") == artist_id for a in existing)

            if not artist_exists:
                # Add artist with no monitoring first
                await self.add_artist(artist_id, artist_name, monitor="none")

            # Now add/monitor the specific album
            resp = await client.get(
                f"{self.base_url}/api/v1/album/lookup",
                params={"term": f"lidarr:{foreign_album_id}"},
                headers=self._headers(),
            )
            if resp.status_code == 200:
                albums = resp.json()
                if albums:
                    album = albums[0]
                    album["monitored"] = True
                    resp = await client.put(
                        f"{self.base_url}/api/v1/album/{album['id']}",
                        headers=self._headers(),
                        json=album,
                    )
                    if resp.status_code == 200:
                        # Trigger search for this album
                        await client.post(
                            f"{self.base_url}/api/v1/command",
                            headers=self._headers(),
                            json={"name": "AlbumSearch", "albumIds": [album["id"]]},
                        )
                        return {"ok": True, "album": album.get("title", "")}

            return {"error": "Album not found"}

    async def search_missing(self) -> dict:
        """Trigger a search for all missing albums."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/command",
                headers=self._headers(),
                json={"name": "MissingAlbumSearch"},
            )
            if resp.status_code in (200, 201):
                return {"ok": True}
            return {"error": resp.text[:200]}
