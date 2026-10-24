"""Multi-user P2, analytics side: taste profiles, recommendations, Live, dashboard, Music Map
listening layers, AI context and the per-user scheduler loop are each user's own, and an
anonymous grace-mode caller falls back to the owner.

Two accounts: `admin` (the owner, created first) and `bob` (a regular user).

Run: uv run --with pytest --with pytest-asyncio --with numpy pytest tests/test_per_user_analytics.py
"""
from datetime import datetime, timedelta

import httpx
import numpy as np
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
from backend.models.artist import Artist
from backend.models.embedding import TrackEmbedding
from backend.models.favorite import Favorite
from backend.models.recommendation import Recommendation
from backend.models.taste_profile import TasteProfile
from backend.models.track import Track
from backend.models.user import User
from backend.services.user_data import record_play, record_skip

pytestmark = pytest.mark.asyncio

app.user_middleware = [m for m in app.user_middleware if m.cls is not RateLimiter]
app.middleware_stack = None

ADMIN_KEY = "a" * 32
BOB_KEY = "b" * 32


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("10.0.0.50", 5555)),
                             base_url="http://testserver")


def as_admin() -> dict:
    return {"apiKey": ADMIN_KEY}


def as_bob() -> dict:
    return {"apiKey": BOB_KEY}


@pytest_asyncio.fixture
async def world(db_ready, monkeypatch):
    """admin (owner) and bob, six tracks by two artists. admin played t0-t2 (artist A),
    bob played t3-t5 (artist B) and skipped t0; each favorited one of their own."""
    lockout.reset_all()
    reset_grace_log()
    monkeypatch.setattr(get_settings().auth, "enforce", False)
    from backend.api import library_dashboard
    from backend.services.ai import insights as ai_insights
    library_dashboard._dashboard_cache = None
    ai_insights._insights_cache.clear()

    now = datetime.utcnow()
    async with async_session() as db:
        admin = User(id="u-admin", username="admin", password_hash=hash_password("x"),
                     subsonic_api_key=ADMIN_KEY, role="admin", created_at=now - timedelta(days=10))
        bob = User(id="u-bob", username="bob", password_hash=hash_password("x"),
                   subsonic_api_key=BOB_KEY, role="user", created_at=now - timedelta(days=5))
        db.add_all([admin, bob])
        db.add_all([Artist(id="ar-a", name="Alpha"), Artist(id="ar-b", name="Bravo")])
        for n in range(6):
            db.add(Track(id=f"t{n}", title=f"Song {n}", artist_id="ar-a" if n < 3 else "ar-b",
                         genre="Rock" if n < 3 else "Jazz", file_path=f"/m/{n}.flac", format="flac"))
        await db.flush()
        tracks = {t.id: t for t in (await db.execute(select(Track))).scalars().all()}
        for n in range(3):
            for k in range(n + 1):
                await record_play(db, "u-admin", tracks[f"t{n}"], now - timedelta(hours=k + 1), "web")
        for n in range(3, 6):
            for k in range(2):
                await record_play(db, "u-bob", tracks[f"t{n}"], now - timedelta(hours=k + 1), "ZonikApp")
        await record_skip(db, "u-bob", tracks["t0"], now - timedelta(minutes=30))
        db.add(Favorite(id="f1", user_id="u-admin", track_id="t0", starred_at=now))
        db.add(Favorite(id="f2", user_id="u-bob", track_id="t3", starred_at=now))
        await db.commit()
    yield
    lockout.reset_all()


# --- Live ---------------------------------------------------------------------------------

async def test_live_history_is_the_callers(world):
    async with client() as c:
        mine = (await c.get("/api/live/history", params=as_bob())).json()
        assert {r["track_id"] for r in mine} == {"t3", "t4", "t5"}
        assert {r["username"] for r in mine} == {"bob"}
        assert all(not r["starred"] or r["track_id"] == "t3" for r in mine)

        admin = (await c.get("/api/live/history", params=as_admin())).json()
        assert {r["track_id"] for r in admin} == {"t0", "t1", "t2"}

        # Anonymous grace-mode caller = the owner.
        anon = (await c.get("/api/live/history")).json()
        assert {r["track_id"] for r in anon} == {"t0", "t1", "t2"}

        # all_users: admins see everyone, a regular user still only themselves.
        everyone = (await c.get("/api/live/history", params={**as_admin(), "all_users": "true"})).json()
        assert {r["username"] for r in everyone} == {"admin", "bob"}
        bob_all = (await c.get("/api/live/history", params={**as_bob(), "all_users": "true"})).json()
        assert {r["username"] for r in bob_all} == {"bob"}


async def test_now_playing_admin_sees_all_user_sees_own(world):
    from backend.subsonic.annotation import _now_playing
    now = datetime.utcnow()
    _now_playing.clear()
    _now_playing["admin"] = {"track_id": "t0", "playerId": "web", "started_at": now}
    _now_playing["bob"] = {"track_id": "t3", "playerId": "ZonikApp", "started_at": now}
    try:
        async with client() as c:
            admin = (await c.get("/api/live/now-playing", params=as_admin())).json()
            assert {(r["username"], r["track_id"]) for r in admin} == {("admin", "t0"), ("bob", "t3")}
            bob = (await c.get("/api/live/now-playing", params=as_bob())).json()
            assert [(r["username"], r["track_id"]) for r in bob] == [("bob", "t3")]
            assert bob[0]["starred"] is True  # bob's own star on t3

            trail = (await c.get("/api/map/trail", params=as_bob())).json()
            assert [p["track_id"] for p in trail["now_playing"]] == ["t3"]
    finally:
        _now_playing.clear()


async def test_skips_are_per_user(world):
    async with client() as c:
        bob = (await c.get("/api/live/skips", params=as_bob())).json()
        assert [(r["track_id"], r["skip_count"]) for r in bob] == [("t0", 1)]
        assert (await c.get("/api/live/skips", params=as_admin())).json() == []

        summary = (await c.get("/api/live/skips/summary", params=as_bob())).json()
        assert summary["tracks_with_skips"] == 1 and summary["active_skips"] == 1
        assert (await c.get("/api/live/skips/summary", params=as_admin())).json()["active_skips"] == 0


async def test_reset_skips_only_touches_the_caller(world):
    async with client() as c:
        # admin has no skips of t0: bob's skip and the global total survive.
        assert (await c.post("/api/live/skips/t0/reset", params=as_admin())).json() == {"ok": True}
    async with async_session() as db:
        from backend.services.user_data import stats_for
        assert (await db.get(Track, "t0")).skip_count == 1
        assert (await stats_for(db, "u-bob", ["t0"]))["t0"].skip_count == 1


# --- Dashboard / stats --------------------------------------------------------------------

async def test_play_history_stats_per_caller(world):
    async with client() as c:
        bob = (await c.get("/api/library/stats/play-history", params={**as_bob(), "period": "7d"})).json()
        admin = (await c.get("/api/library/stats/play-history", params={**as_admin(), "period": "7d"})).json()
        everyone = (await c.get("/api/library/stats/play-history",
                                params={**as_admin(), "period": "7d", "all_users": "true"})).json()
    assert bob["total_plays"] == 6 and {a["name"] for a in bob["top_artists"]} == {"Bravo"}
    assert admin["total_plays"] == 6 and {a["name"] for a in admin["top_artists"]} == {"Alpha"}
    assert everyone["total_plays"] == 12


async def test_dashboard_favorites_and_most_played_per_caller(world):
    async with client() as c:
        bob = (await c.get("/api/library/stats/dashboard", params=as_bob())).json()
        admin = (await c.get("/api/library/stats/dashboard", params=as_admin())).json()  # cached library part
        assert bob["favorites"]["recent"] == [{"title": "Song 3", "artist": "Bravo"}]
        assert admin["favorites"]["recent"] == [{"title": "Song 0", "artist": "Alpha"}]
        assert admin["quality"] == bob["quality"]

        detailed = (await c.get("/api/library/stats/detailed", params=as_bob())).json()
        assert detailed["favorites"] == 1
        assert {m["title"] for m in detailed["most_played"]} == {"Song 3", "Song 4", "Song 5"}


async def test_shuffle_counts_are_the_callers(world):
    async with client() as c:
        bob = (await c.get("/api/config/shuffle", params=as_bob())).json()
        admin = (await c.get("/api/config/shuffle", params=as_admin())).json()
    assert bob["library"]["never_played"] == 3 and admin["library"]["never_played"] == 3
    assert bob["library"]["tracks"] == 6


# --- Music Map listening layers -----------------------------------------------------------

async def test_map_listening_layers_per_caller(world):
    async with client() as c:
        for who, total in ((as_bob(), 6), (as_admin(), 6)):
            assert (await c.get("/api/map/streak-calendar", params=who)).json()["total"] == total
            assert (await c.get("/api/map/listening-clock", params=who)).json()["total"] == total
        river = (await c.get("/api/map/taste-river", params=as_bob())).json()
        assert river["total"] == 6
        rot = (await c.get("/api/map/rotation", params=as_bob())).json()
        assert {t["track_id"] for t in rot["tracks"]} == {"t3", "t4", "t5"}
        assert all(t["total_plays"] == 2 for t in rot["tracks"])
        trail = (await c.get("/api/map/trail", params={**as_admin(), "hours": 24})).json()
        assert {p["track_id"] for p in trail["plays"]} == {"t0", "t1", "t2"}

        tl = (await c.get("/api/map/track/t0/listening", params=as_bob())).json()
        assert tl["play_count"] == 0 and tl["skip_count"] == 1 and sum(tl["monthly"]) == 0
        tl = (await c.get("/api/map/track/t0/listening", params=as_admin())).json()
        assert tl["play_count"] == 1 and tl["skip_count"] == 0


async def test_neglected_gems_and_dismissals_per_user(world):
    rng = np.random.default_rng(1)
    async with async_session() as db:
        for n in range(6):
            db.add(TrackEmbedding(track_id=f"t{n}", embedding=rng.random(512, dtype=np.float32).tobytes()))
        await db.commit()
    async with client() as c:
        bob = (await c.get("/api/map/neglected-gems", params=as_bob())).json()
        assert {g["track_id"] for g in bob["gems"]} == {"t0", "t1", "t2"}  # never played by bob
        admin = (await c.get("/api/map/neglected-gems", params=as_admin())).json()
        assert {g["track_id"] for g in admin["gems"]} == {"t3", "t4", "t5"}

        r = await c.post("/api/map/gems/dismiss", params=as_bob(), json={"track_id": "t1"})
        assert r.json() == {"ok": True}
        bob = (await c.get("/api/map/neglected-gems", params=as_bob())).json()
        assert {g["track_id"] for g in bob["gems"]} == {"t0", "t2"}
        # bob's dismissal is his: t1 was never a gem for admin, and admin's gems are unchanged.
        admin = (await c.get("/api/map/neglected-gems", params=as_admin())).json()
        assert {g["track_id"] for g in admin["gems"]} == {"t3", "t4", "t5"}


async def test_soundscape_heat_is_the_callers(world):
    from backend.services.soundscape import _ensure_table
    async with async_session() as db:
        await _ensure_table(db)
        from sqlalchemy import text
        for n in range(6):
            await db.execute(text(
                "INSERT INTO track_projection (track_id, x, y, model_version, computed_at) "
                "VALUES (:t, 0, 0, 'm', 'now')"), {"t": f"t{n}"})
        await db.commit()
    async with client() as c:
        data = (await c.get("/api/map/soundscape", params=as_bob())).json()
    plays = dict(zip(data["ids"], data["play_count"]))
    assert plays == {"t0": 0, "t1": 0, "t2": 0, "t3": 2, "t4": 2, "t5": 2}
    assert dict(zip(data["ids"], data["skip_count"]))["t0"] == 1


# --- Taste profile + recommendations ------------------------------------------------------

async def test_taste_profiles_are_per_user(world):
    from backend.services.recommender import build_taste_profile
    async with async_session() as db:
        bob = await build_taste_profile(db, "u-bob")
        admin = await build_taste_profile(db)  # None = owner
        tps = {tp.id: tp for tp in (await db.execute(select(TasteProfile))).scalars().all()}
    assert set(tps) == {"u-admin", "u-bob"}
    assert [a["name"] for a in bob["top_artists"]] == ["Bravo"]
    assert [a["name"] for a in admin["top_artists"]] == ["Alpha"]
    assert bob["favorite_artists"] == ["Bravo"] and admin["favorite_artists"] == ["Alpha"]
    assert tps["u-bob"].favorite_count == 1


async def _add_rec(db, rid, user_id, status="pending", score=0.8, artist="X", track="Y"):
    db.add(Recommendation(id=rid, user_id=user_id, artist=artist, track=track, source="similar_track",
                          score=score, status=status, created_at=datetime.utcnow()))


async def test_recommendations_list_stats_feedback_are_per_user(world):
    async with async_session() as db:
        await _add_rec(db, "r-admin", "u-admin", artist="A1", track="T1")
        await _add_rec(db, "r-bob", "u-bob", artist="B1", track="T1")
        await _add_rec(db, "r-bob-dl", "u-bob", status="downloaded", artist="B2", track="T2")
        await db.commit()
    async with client() as c:
        bob = (await c.get("/api/recommendations", params=as_bob())).json()
        assert [r["id"] for r in bob["items"]] == ["r-bob"]
        admin = (await c.get("/api/recommendations", params=as_admin())).json()
        assert [r["id"] for r in admin["items"]] == ["r-admin"]
        anon = (await c.get("/api/recommendations")).json()
        assert [r["id"] for r in anon["items"]] == ["r-admin"]

        stats = (await c.get("/api/recommendations/stats", params=as_bob())).json()
        assert stats["total"] == 2 and stats["downloaded"] == 1 and stats["pending"] == 1

        radar = (await c.get("/api/discovery/weekly-radar", params=as_bob())).json()
        assert [t["id"] for t in radar["tracks"]] == ["r-bob"]

        # Feedback on someone else's recommendation: admins may, the rec is not bob's to touch.
        r = await c.post("/api/recommendations/feedback", params=as_admin(),
                         json={"recommendation_id": "r-bob", "action": "thumbs_up"})
        assert r.json() == {"ok": True}


async def test_refresh_replaces_only_that_users_pending(world, monkeypatch):
    monkeypatch.setattr(get_settings().lastfm, "api_key", "")  # no candidates: refresh only clears
    from backend.services.recommender import refresh_recommendations
    async with async_session() as db:
        await _add_rec(db, "r-admin", "u-admin")
        await _add_rec(db, "r-bob", "u-bob")
        await _add_rec(db, "r-bob-acc", "u-bob", status="accepted")
        await db.commit()
        result = await refresh_recommendations(db, user_id="u-bob")
        assert result["user_id"] == "u-bob"
        left = {r.id for r in (await db.execute(select(Recommendation))).scalars().all()}
    assert left == {"r-admin", "r-bob-acc"}


async def test_feedback_multipliers_are_per_user(world):
    from backend.services.recommender import _get_feedback_multipliers
    async with async_session() as db:
        db.add(Recommendation(id="r1", user_id="u-bob", artist="Hated", track="x", source="tag",
                              feedback="thumbs_down", status="rejected"))
        await db.commit()
        assert await _get_feedback_multipliers(db, "u-bob") == {"hated": 0.5}
        assert await _get_feedback_multipliers(db, "u-admin") == {}


# --- Scheduler ----------------------------------------------------------------------------

async def _plays(user_id: str, n: int, days_ago: int):
    from backend.models.play_history import PlayHistory
    async with async_session() as db:
        for k in range(n):
            db.add(PlayHistory(track_id="t0", user_id=user_id, source="web",
                               played_at=datetime.utcnow() - timedelta(days=days_ago, minutes=k)))
        await db.commit()


async def test_scheduler_refreshes_active_users_and_always_the_owner(world):
    from backend.workers import scheduler
    async with async_session() as db:
        db.add_all([
            User(id="u-carol", username="carol", password_hash="x", role="user"),
            User(id="u-dave", username="dave", password_hash="x", role="user"),
            User(id="u-erin", username="erin", password_hash="x", role="user", disabled=True),
        ])
        await db.commit()
    await _plays("u-bob", 20, 1)      # 26 plays, recent: in
    await _plays("u-carol", 30, 60)   # enough plays but idle for two months: out
    await _plays("u-erin", 30, 1)     # disabled: out
    # admin has only 6 plays, but the owner is always refreshed; dave has none.
    async with async_session() as db:
        ids = await scheduler._recommendation_user_ids(db, {})
        assert ids == ["u-admin", "u-bob"]
        assert await scheduler._recommendation_user_ids(db, {"idle_days": 0}) == ["u-admin", "u-bob", "u-carol"]
        assert await scheduler._recommendation_user_ids(db, {"min_plays": 100}) == ["u-admin"]

        seen = []

        async def fake_refresh(db, on_progress=None, user_id=None):
            seen.append(user_id)
            await on_progress(1, 5, "Sourcing")
            return {"candidates_sourced": 10, "recommendations_saved": 4, "top_score": 0.5 + len(seen) / 10,
                    "clap_validated": 0, "clap_previews_scored": 1}

        progress = []

        async def on_progress(cur, total, desc=""):
            progress.append(desc)

        out = await scheduler._run_recommendation_refresh(db, fake_refresh, on_progress, {})
    assert seen == ["u-admin", "u-bob"]
    assert out["recommendations_saved"] == 8 and out["candidates_sourced"] == 20
    assert out["top_score"] == 0.7
    assert set(out["users"]) == {"admin", "bob"}
    assert out["skipped_users"] == ["carol", "dave"]
    assert progress == ["admin: Sourcing", "bob: Sourcing"]


async def test_auto_download_recommendations_tags_origin_and_dedupes(world, monkeypatch):
    from backend.workers import scheduler
    async with async_session() as db:
        await _add_rec(db, "r-a", "u-admin", score=0.9, artist="Same", track="Song")
        await _add_rec(db, "r-b", "u-bob", score=0.8, artist="Same", track="Song")
        await _add_rec(db, "r-c", "u-bob", score=0.7, artist="Other", track="Tune")
        await db.commit()

    captured = []

    async def fake_missing(missing, source, batch_id=None):
        captured.extend(missing)
        return [{"artist": m["artist"], "track": m["track"], "ok": True, "error": None} for m in missing]

    monkeypatch.setattr(scheduler, "_auto_download_missing", fake_missing)
    async with async_session() as db:
        await scheduler._auto_download_recommendations(db, 0.5, max_downloads=1)
        statuses = {r.id: r.status for r in (await db.execute(select(Recommendation))).scalars().all()}
    # One slot: the shared track, highest-scoring rec's user as origin; both recs settle.
    assert [m["origin"] for m in captured] == ["recommendations:admin", "recommendations:bob"]
    assert statuses == {"r-a": "downloaded", "r-b": "downloaded", "r-c": "pending"}


async def test_scheduler_favorites_playlist_is_the_owners(world):
    from backend.models.playlist import Playlist, PlaylistTrack
    from backend.workers import scheduler
    async with async_session() as db:
        db.add(Playlist(id="p-bob", name="Favorites", user_id="u-bob"))
        await db.commit()
        await scheduler._run_favorites_playlist(db)
        pls = (await db.execute(select(Playlist).where(Playlist.name == "Favorites"))).scalars().all()
        owner_pl = next(p for p in pls if p.user_id == "u-admin")
        tracks = (await db.execute(
            select(PlaylistTrack.track_id).where(PlaylistTrack.playlist_id == owner_pl.id)
        )).scalars().all()
    assert {p.id for p in pls} >= {"p-bob"}  # bob's own "Favorites" untouched
    assert tracks == ["t0"]


# --- AI context ---------------------------------------------------------------------------

async def test_ai_insights_use_the_callers_week(world, monkeypatch):
    from backend.services.ai import insights as ai_insights
    prompts = []

    async def fake_claude(prompt, **_kw):
        prompts.append(prompt)
        return {"parsed": {"summary": "ok", "highlights": [], "trends": []}}

    monkeypatch.setattr(ai_insights, "call_claude", fake_claude)
    async with client() as c:
        bob = (await c.get("/api/library/stats/insights", params=as_bob())).json()
        admin = (await c.get("/api/library/stats/insights", params=as_admin())).json()
    assert bob["top_genre"] == "Jazz" and admin["top_genre"] == "Rock"
    assert "Song 3" in prompts[0] and "Song 0" not in prompts[0]


async def test_nl_search_play_counts_are_the_callers(world):
    from backend.services.ai.nl_search import search_with_filters
    async with async_session() as db:
        bob = await search_with_filters(db, {"sort_by": "play_count"}, limit=3, user_id="u-bob")
        admin = await search_with_filters(db, {"sort_by": "play_count"}, limit=1)
    assert {t["id"] for t in bob} == {"t3", "t4", "t5"} and all(t["play_count"] == 2 for t in bob)
    assert admin[0]["id"] == "t2" and admin[0]["play_count"] == 3
