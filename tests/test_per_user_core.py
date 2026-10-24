"""Multi-user P2, core paths: plays, skips, ratings, stars, playlists, bookmarks, the play
queue, users and Shuffle Mix are kept apart per caller on /rest and /api.

Two users: `admin` (the owner) and `bob` (role user). Requests go through the real app, as in
tests/test_auth.py; anonymous grace-mode calls act as the owner.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_per_user_core.py
"""
import hashlib
import uuid
from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.auth import lockout
from backend.auth.passwords import hash_password
from backend.auth.resolve import reset_grace_log
from backend.config import get_settings
from backend.database import async_session
from backend.main import app
from backend.middleware.rate_limit import RateLimiter
from backend.models.album import Album
from backend.models.artist import Artist
from backend.models.play_history import PlayHistory
from backend.models.playlist import Playlist
from backend.models.track import Track
from backend.models.user import User
from backend.models.user_track_stats import UserTrackStats
from backend.subsonic import annotation

pytestmark = pytest.mark.asyncio

PASSWORD = "correct horse"
KEYS = {"admin": "adminkey0123456789", "bob": "bobkey0123456789"}

app.user_middleware = [m for m in app.user_middleware if m.cls is not RateLimiter]
app.middleware_stack = None


@pytest_asyncio.fixture
async def env(db_ready, monkeypatch):
    lockout.reset_all()
    reset_grace_log()
    monkeypatch.setattr(get_settings().auth, "enforce", False)
    annotation._now_playing.clear()
    annotation._skip_watch.clear()
    ids = {}
    async with async_session() as db:
        for i, (name, role) in enumerate((("admin", "admin"), ("bob", "user"))):
            user = User(id=str(uuid.uuid4()), username=name, password_hash=hash_password(PASSWORD),
                        subsonic_api_key=KEYS[name], role=role, display_name=name.title(),
                        created_at=datetime(2026, 1, 1 + i))
            db.add(user)
            ids[name] = user.id
        db.add(Artist(id="ar1", name="Artist One"))
        db.add(Album(id="al1", title="Album One", artist_id="ar1"))
        db.add(Album(id="al2", title="Album Two", artist_id="ar1"))
        db.add(Album(id="al3", title="Album Three", artist_id="ar1"))
        for n, album in ((1, "al1"), (2, "al2"), (3, "al3")):
            db.add(Track(id=f"t{n}", title=f"Song {n}", artist_id="ar1", album_id=album,
                         file_path=f"/m/{n}.mp3", duration_seconds=200, play_count=0))
        await db.commit()
    yield ids
    annotation._now_playing.clear()
    annotation._skip_watch.clear()
    lockout.reset_all()


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("10.0.0.50", 5555)),
                             base_url="http://testserver")


def auth(who: str | None, **extra) -> dict:
    """Subsonic params for a user (None = anonymous), plus extra params."""
    params = {"c": "test", "v": "1.16.1", "f": "json"}
    if who:
        salt = "s4lt"
        params.update(u=who, s=salt, t=hashlib.md5((KEYS[who] + salt).encode()).hexdigest())
    params.update(extra)
    return params


async def rest(c, endpoint: str, who: str | None, **extra) -> dict:
    r = await c.get(f"/rest/{endpoint}", params=auth(who, **extra))
    return r.json()["subsonic-response"]


async def song(c, username, track_id="t1") -> dict:
    return (await rest(c, "getSong", username, id=track_id))["song"]


# --- plays, skips, ratings ---------------------------------------------------------------

async def test_scrobbles_are_per_user(env):
    async with client() as c:
        for _ in range(2):
            await rest(c, "scrobble", "bob", id="t1", submission="true")
        await rest(c, "scrobble", "admin", id="t1", submission="true")
        assert (await song(c, "bob"))["playCount"] == 2
        assert (await song(c, "admin"))["playCount"] == 1
        assert (await song(c, None))["playCount"] == 1  # anonymous = the owner
        assert "played" in await song(c, "bob")
        assert (await song(c, "bob", "t2"))["playCount"] == 0 and "played" not in await song(c, "bob", "t2")
        # the web player's /api play counts for the caller
        r = await c.post("/api/tracks/t1/play", params=auth("bob"))
        assert r.json()["play_count"] == 3 and r.json()["total_play_count"] == 4
    async with async_session() as db:
        assert (await db.get(Track, "t1")).play_count == 4  # library-wide total
        rows = (await db.execute(select(PlayHistory.user_id, PlayHistory.source))).all()
        assert sorted(r[0] for r in rows) == sorted([env["bob"]] * 3 + [env["admin"]])
        assert {r[1] for r in rows} == {"test", "web"}


async def test_skips_are_per_user(env):
    async with client() as c:
        await rest(c, "scrobble", "bob", id="t1", submission="false")
        await rest(c, "scrobble", "bob", id="t2", submission="false")  # t1 skipped
        # admin's watch is separate: their first now-playing infers nothing
        await rest(c, "scrobble", "admin", id="t2", submission="false")
    async with async_session() as db:
        bob = await db.get(UserTrackStats, (env["bob"], "t1"))
        assert bob.skip_count == 1
        assert await db.get(UserTrackStats, (env["admin"], "t1")) is None
        assert (await db.get(Track, "t1")).skip_count == 1


async def test_ratings_are_per_user_and_only_admins_mirror(env):
    async with client() as c:
        await rest(c, "setRating", "bob", id="t1", rating="4")
        assert (await song(c, "bob"))["userRating"] == 4
        assert "userRating" not in await song(c, "admin")
        async with async_session() as db:
            assert (await db.get(Track, "t1")).rating is None  # a user's rating stays personal

        await rest(c, "setRating", "admin", id="t1", rating="1")  # the deletion flag
        async with async_session() as db:
            assert (await db.get(Track, "t1")).rating == 1
        assert (await song(c, "bob"))["userRating"] == 4

        r = await c.put("/api/tracks/t2/rating", params={**auth("bob"), "rating": 5})
        assert r.json() == {"ok": True, "rating": 5}
        r = await c.get("/api/tracks/t2", params=auth("bob"))
        assert r.json()["user_rating"] == 5
        listing = (await c.get("/api/tracks")).json()["tracks"]  # anonymous = owner
        t2 = next(t for t in listing if t["id"] == "t2")
        assert t2["rating"] is None and t2["user_rating"] is None
        # anonymous /api rating acts as the owner (admin) and so mirrors
        await c.put("/api/tracks/t3/rating", params={"rating": 3})
        async with async_session() as db:
            assert (await db.get(Track, "t3")).rating == 3
            assert (await db.get(UserTrackStats, (env["admin"], "t3"))).rating == 3


# --- stars ----------------------------------------------------------------------------------

async def test_stars_are_per_user(env):
    async with client() as c:
        await rest(c, "star", "bob", id="t1", albumId="al2")
        bob = (await rest(c, "getStarred2", "bob"))["starred2"]
        assert [s["id"] for s in bob["song"]] == ["t1"] and [a["id"] for a in bob["album"]] == ["al2"]
        admin = (await rest(c, "getStarred2", "admin"))["starred2"]
        assert admin["song"] == [] and admin["album"] == []
        assert "starred" in await song(c, "bob") and "starred" not in await song(c, "admin")
        assert (await rest(c, "getStarred", "bob"))["starred"]["song"][0]["id"] == "t1"
        starred_albums = (await rest(c, "getAlbumList2", "bob", type="starred"))["albumList2"]["album"]
        assert [a["id"] for a in starred_albums] == ["al2"] and "starred" in starred_albums[0]
        assert (await rest(c, "getAlbumList2", "admin", type="starred"))["albumList2"]["album"] == []

        # /api/favorites: always the caller; a user_id param no longer picks someone else
        await c.post("/api/favorites/star", json={"track_id": "t3"}, params=auth("bob"))
        assert sorted((await c.get("/api/favorites/ids", params=auth("bob"))).json()["track_ids"]) == ["t1", "t3"]
        anon = (await c.get("/api/favorites/ids", params={"user_id": "bob"})).json()
        assert anon["track_ids"] == []
        await c.post("/api/favorites/star", json={"track_id": "t2"})  # anonymous = owner
        assert (await c.get("/api/favorites", params=auth("admin"))).json()["total"] == 1
        assert (await c.get("/api/favorites", params=auth("bob"))).json()["total"] == 3  # t1, al2, t3

        await rest(c, "unstar", "admin", id="t1")  # admin can't unstar bob's
        assert len((await rest(c, "getStarred2", "bob"))["starred2"]["song"]) == 2


async def test_library_version_follows_the_callers_own_changes(env):
    async with client() as c:
        async def version(user):
            return (await rest(c, "getLibraryVersion", user))["libraryVersion"]["version"]
        bob0, admin0 = await version("bob"), await version("admin")
        await rest(c, "star", "bob", id="t1")
        assert await version("bob") != bob0
        assert await version("admin") == admin0
        await rest(c, "setRating", "admin", id="t2", rating="3")
        assert await version("admin") != admin0


# --- album lists and Shuffle Mix --------------------------------------------------------------

async def test_recent_and_frequent_albums_are_per_user(env):
    async with client() as c:
        for _ in range(3):
            await rest(c, "scrobble", "bob", id="t2")
        await rest(c, "scrobble", "bob", id="t1")
        await rest(c, "scrobble", "admin", id="t3")
        frequent = (await rest(c, "getAlbumList2", "bob", type="frequent"))["albumList2"]["album"]
        assert [a["id"] for a in frequent] == ["al2", "al1"]
        recent = (await rest(c, "getAlbumList2", "admin", type="recent"))["albumList2"]["album"]
        assert [a["id"] for a in recent] == ["al3"]


async def test_shuffle_cooldown_uses_the_callers_plays(env, monkeypatch):
    monkeypatch.setattr(get_settings().subsonic, "shuffle_cooldown_days", 30)
    async with client() as c:
        await rest(c, "scrobble", "bob", id="t2")
        await rest(c, "scrobble", "bob", id="t3")
        await rest(c, "scrobble", "admin", id="t1")
        for _ in range(5):
            mix = (await rest(c, "getRandomSongs", "bob", size="1"))["randomSongs"]["song"]
            assert [s["id"] for s in mix] == ["t1"]
            mix = (await rest(c, "getRandomSongs", "admin", size="1"))["randomSongs"]["song"]
            assert mix[0]["id"] in ("t2", "t3") and mix[0]["playCount"] == 0


async def test_unplayed_quota_uses_the_callers_plays(env, monkeypatch):
    monkeypatch.setattr(get_settings().subsonic, "shuffle_unplayed_percent", 100)
    monkeypatch.setattr(get_settings().subsonic, "shuffle_cooldown_days", 0)
    async with client() as c:
        await rest(c, "scrobble", "admin", id="t1")
        await rest(c, "scrobble", "admin", id="t2")
        for _ in range(5):
            mix = (await rest(c, "getRandomSongs", "admin", size="1"))["randomSongs"]["song"]
            assert [s["id"] for s in mix] == ["t3"]


# --- playlists ----------------------------------------------------------------------------------

async def test_api_playlists_ownership(env):
    async with client() as c:
        mine = (await c.post("/api/playlists", json={"name": "Admin private", "track_ids": ["t1"]},
                             params=auth("admin"))).json()["id"]
        shared = (await c.post("/api/playlists", json={"name": "Admin shared", "is_public": True},
                               params=auth("admin"))).json()["id"]
        bobs = (await c.post("/api/playlists", json={"name": "Bob's"}, params=auth("bob"))).json()["id"]

        bob_list = {p["id"]: p for p in (await c.get("/api/playlists", params=auth("bob"))).json()}
        assert set(bob_list) == {shared, bobs}
        assert bob_list[shared]["owner"] == {"id": env["admin"], "username": "admin", "display_name": "Admin"}
        assert bob_list[shared]["is_public"] is True and bob_list[shared]["can_edit"] is False
        assert bob_list[bobs]["can_edit"] is True and bob_list[bobs]["is_public"] is False

        assert (await c.get(f"/api/playlists/{mine}", params=auth("bob"))).status_code == 404
        detail = (await c.get(f"/api/playlists/{shared}", params=auth("bob"))).json()
        assert detail["can_edit"] is False and detail["owner"]["username"] == "admin"
        assert (await c.put(f"/api/playlists/{shared}", json={"name": "x"}, params=auth("bob"))).status_code == 403
        assert (await c.delete(f"/api/playlists/{shared}", params=auth("bob"))).status_code == 403
        r = await c.put(f"/api/playlists/{bobs}", json={"is_public": True}, params=auth("bob"))
        assert r.status_code == 200

        # anonymous = the owner (admin): own + public, and admins may change anyone's
        anon = {p["id"] for p in (await c.get("/api/playlists")).json()}
        assert anon == {mine, shared, bobs}
        assert (await c.put(f"/api/playlists/{bobs}", json={"name": "Renamed"})).status_code == 200
        assert (await c.delete("/api/playlists/does-not-exist")).json() == {"ok": True}

        r = await c.post("/api/playlists/generate", json={"name": "Smart", "rule": "recent"}, params=auth("bob"))
        assert r.status_code == 200
    async with async_session() as db:
        owners = {p.name: p.user_id for p in (await db.execute(select(Playlist))).scalars().all()}
        assert owners["Smart"] == env["bob"] and owners["Renamed"] == env["bob"]
        assert owners["Admin private"] == env["admin"]


async def test_smart_top_played_uses_the_callers_plays(env):
    async with client() as c:
        await rest(c, "scrobble", "bob", id="t3")
        await rest(c, "scrobble", "admin", id="t1")
        r = (await c.post("/api/playlists/generate", json={"name": "Top", "rule": "top_played"},
                          params=auth("bob"))).json()
        detail = (await c.get(f"/api/playlists/{r['id']}", params=auth("bob"))).json()
        assert [t["id"] for t in detail["tracks"]] == ["t3"]


async def test_subsonic_playlists_ownership(env):
    async with client() as c:
        await rest(c, "createPlaylist", "admin", name="Admin private", songId="t1")
        await rest(c, "createPlaylist", "bob", name="Bob list", songId="t2")
        async with async_session() as db:
            ids = {p.name: p.id for p in (await db.execute(select(Playlist))).scalars().all()}
        admin_private, bob_list = ids["Admin private"], ids["Bob list"]

        listing = (await rest(c, "getPlaylists", "bob"))["playlists"]["playlist"]
        assert [(p["name"], p["owner"], p["public"]) for p in listing] == [("Bob list", "bob", "false")]
        assert (await rest(c, "getPlaylist", "bob", id=admin_private))["error"]["code"] == 70
        assert (await rest(c, "deletePlaylist", "bob", id=admin_private))["error"]["code"] == 70

        await rest(c, "updatePlaylist", "admin", playlistId=admin_private, public="true")
        listing = (await rest(c, "getPlaylists", "bob"))["playlists"]["playlist"]
        assert {(p["name"], p["owner"], p["public"]) for p in listing} == {
            ("Bob list", "bob", "false"), ("Admin private", "admin", "true")}
        got = (await rest(c, "getPlaylist", "bob", id=admin_private))["playlist"]
        assert got["owner"] == "admin" and got["entry"][0]["id"] == "t1"
        r = await rest(c, "updatePlaylist", "bob", playlistId=admin_private, name="mine now")
        assert r["error"]["code"] == 50
        assert (await rest(c, "deletePlaylist", "bob", id=admin_private))["error"]["code"] == 50
        assert (await rest(c, "createPlaylist", "bob", playlistId=admin_private, songId="t3"))["error"]["code"] == 50

        await rest(c, "updatePlaylist", "bob", playlistId=bob_list, songIdToAdd="t3")
        got = (await rest(c, "getPlaylist", "bob", id=bob_list))["playlist"]
        assert [e["id"] for e in got["entry"]] == ["t2", "t3"]
        # admins may change anyone's
        assert (await rest(c, "deletePlaylist", "admin", id=bob_list))["status"] == "ok"
    async with async_session() as db:
        assert await db.get(Playlist, bob_list) is None


# --- bookmarks, play queue, users, now playing ------------------------------------------------

async def test_bookmarks_and_play_queue_are_the_callers(env):
    async with client() as c:
        await rest(c, "createBookmark", "bob", id="t1", position="1000")
        await rest(c, "savePlayQueue", "bob", id="t2", current="t2", position="5")
        # anonymous with u=bob but no credentials acts as the owner, not as bob
        await rest(c, "savePlayQueue", None, u="bob", id="t3", current="t3")
        bob_q = (await rest(c, "getPlayQueue", "bob"))["playQueue"]
        assert bob_q["current"] == "t2" and bob_q["username"] == "bob"
        admin_q = (await rest(c, "getPlayQueue", "admin"))["playQueue"]
        assert admin_q["current"] == "t3" and admin_q["username"] == "admin"
        assert [b["entry"]["id"] for b in (await rest(c, "getBookmarks", "bob"))["bookmarks"]["bookmark"]] == ["t1"]
        assert (await rest(c, "getBookmarks", "admin"))["bookmarks"].get("bookmark", []) == []
        await rest(c, "deleteBookmark", "admin", id="t1")  # not admin's to delete
        assert len((await rest(c, "getBookmarks", "bob"))["bookmarks"]["bookmark"]) == 1


async def test_get_user_and_users(env):
    async with client() as c:
        me = (await rest(c, "getUser", "bob"))["user"]
        assert me["username"] == "bob" and me["adminRole"] == "false"
        assert (await rest(c, "getUser", "bob", username="admin"))["error"]["code"] == 50
        assert (await rest(c, "getUser", "admin", username="bob"))["user"]["username"] == "bob"
        assert (await rest(c, "getUser", "admin", username="nobody"))["error"]["code"] == 70
        assert (await rest(c, "getUser", "admin"))["user"]["adminRole"] == "true"
        assert (await rest(c, "getUsers", "bob"))["error"]["code"] == 50
        users = (await rest(c, "getUsers", "admin"))["users"]["user"]
        assert [u["username"] for u in users] == ["admin", "bob"]


async def test_now_playing_admins_see_all_users_see_their_own(env):
    async with client() as c:
        await rest(c, "scrobble", "bob", id="t1", submission="false")
        await rest(c, "scrobble", "admin", id="t2", submission="false")
        bob = (await rest(c, "getNowPlaying", "bob"))["nowPlaying"]["entry"]
        assert [(e["username"], e["id"]) for e in bob] == [("bob", "t1")]
        admin = (await rest(c, "getNowPlaying", "admin"))["nowPlaying"]["entry"]
        assert {(e["username"], e["id"]) for e in admin} == {("bob", "t1"), ("admin", "t2")}
    assert annotation._now_playing["bob"]["user_id"] == env["bob"]


async def test_search_and_album_carry_the_callers_counts(env):
    async with client() as c:
        await rest(c, "scrobble", "bob", id="t1")
        await rest(c, "star", "bob", artistId="ar1")
        res = (await rest(c, "search3", "bob", query="Song"))["searchResult3"]
        assert {s["id"]: s["playCount"] for s in res["song"]} == {"t1": 1, "t2": 0, "t3": 0}
        assert (await rest(c, "search3", "admin", query="Song"))["searchResult3"]["song"][0]["playCount"] == 0
        album = (await rest(c, "getAlbum", "bob", id="al1"))["album"]
        assert album["song"][0]["playCount"] == 1
        artist = (await rest(c, "getArtist", "bob", id="ar1"))["artist"]
        assert "starred" in artist
        assert "starred" not in (await rest(c, "getArtist", "admin", id="ar1"))["artist"]
