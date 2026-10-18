"""Native search ranking: the duration gate and the query-variant merge.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_search_ranking.py
"""
import asyncio
from types import SimpleNamespace

import pytest

from backend.soulseek.protocol.types import FileAttribute, FileInfo, SearchResult
from backend.soulseek.search import (
    build_query_variants, merge_search_results, pick_best_results_native, search_multi_strategy_native,
)


MB = 1024 * 1024


def result(user, filename, duration=None, size=30 * MB):
    attrs = {FileAttribute.DURATION: duration} if duration is not None else {}
    return SearchResult(username=user, token="00", files=[FileInfo(filename, size, attrs)],
                        slots_free=True, avg_speed=0, queue_length=0)


@pytest.mark.asyncio
async def test_duration_gate_rejects_wrong_length_keeps_unknown():
    results = [
        result("right", "Artist\\Album\\01 - Jingle Bells.flac", duration=181),
        result("wrong", "Artist\\Lo-Fi EP\\03 - Jingle Bells.flac", duration=240),
        result("unknown", "Artist\\Album\\Jingle Bells.flac"),
    ]
    picked = await pick_best_results_native(results, "Artist", "Jingle Bells", target_duration=180)
    users = [c["username"] for c in picked]
    assert "wrong" not in users
    assert set(users) == {"right", "unknown"}
    assert users[0] == "right"  # matching duration earns the bonus


@pytest.mark.asyncio
async def test_duration_gate_tolerance_is_three_seconds():
    results = [
        result("plus3", "A\\Song.flac", duration=183),
        result("minus4", "B\\Song.flac", duration=176),
    ]
    picked = await pick_best_results_native(results, "Artist", "Song", target_duration=180)
    assert [c["username"] for c in picked] == ["plus3"]


@pytest.mark.asyncio
async def test_no_target_duration_keeps_everything():
    results = [result("a", "A\\Song.flac", duration=100), result("b", "B\\Song.flac", duration=300)]
    picked = await pick_best_results_native(results, "Artist", "Song")
    assert {c["username"] for c in picked} == {"a", "b"}


# --- query variants: run concurrently, merge, rank once -------------------------

def test_merge_dedupes_files_by_user_and_filename():
    a1 = result("alice", "A\\Song.flac")
    a2 = result("alice", "A\\Song.flac")          # same file from a second query
    a3 = result("alice", "A\\Song (Live).flac")    # another file, same peer
    b1 = result("bob", "A\\Song.flac")             # same name, other peer: kept
    merged = merge_search_results([[a1, b1], [a2, a3]])
    by_user = {sr.username: [f.filename for f in sr.files] for sr in merged}
    assert by_user == {"alice": ["A\\Song.flac", "A\\Song (Live).flac"], "bob": ["A\\Song.flac"]}


def test_query_variants_are_distinct_and_capped():
    qs = build_query_variants("The Artist feat. Someone", "Song Title (Remastered 2011)")
    assert len(qs) == len(set(qs)) and 1 <= len(qs) <= 4


ARTIST, TRACK = "The Artist feat. Someone", "Song Title (Remastered 2011)"


@pytest.mark.asyncio
async def test_first_variant_alone_when_it_finds_candidates():
    asked = []

    async def search(q):
        asked.append(q)
        return [result("alice", "X\\Song Title.flac")]

    client = SimpleNamespace(search=search, reputation=None)
    stats, events = {}, []

    async def on_event(ev):
        events.append(ev)

    picked = await search_multi_strategy_native(client, ARTIST, TRACK, stats=stats, on_event=on_event)
    assert asked == build_query_variants(ARTIST, TRACK)[:1]
    assert [c["username"] for c in picked] == ["alice"]
    # funnel stats
    assert len(stats["queries"]) == 1
    assert stats["queries"][0] == {"q": asked[0], "kind": "variant", "peers": 1, "files": 1}
    assert stats["files_seen"] > 0 and stats["peers_seen"] == 1
    assert stats["kept"] == len(picked)
    assert stats["album_query"] is None
    assert stats["strict"] is True and stats["wanted_duration"] is None
    assert set(stats["rejected"]) == {"size", "ext", "quality", "title", "duration", "score", "artist_path"}
    assert stats["candidates"][0]["score"] > 0
    assert stats["candidates"][0]["extension"] == "flac"
    assert stats["candidates"][0]["queue_length"] == 0
    assert picked[0]["score"] == stats["candidates"][0]["score"]
    # events alternate start/end
    assert [e["event"] for e in events] == ["query_start", "query_end"]
    n = len(build_query_variants(ARTIST, TRACK))
    assert events[0] == {"event": "query_start", "i": 1, "n": n, "q": asked[0], "kind": "variant"}
    assert events[1]["peers"] == 1 and events[1]["files"] == 1


@pytest.mark.asyncio
async def test_fallback_variants_run_concurrently_and_merge():
    variants = build_query_variants(ARTIST, TRACK)
    assert len(variants) >= 3
    running = 0
    peak = 0
    asked = []

    async def search(q):
        nonlocal running, peak
        asked.append(q)
        if q == variants[0]:
            return [result("nobody-useful", "X\\Other Song.flac")]  # fails the title gate
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        # each fallback finds a different peer; one peer shows up in every response
        return [result(f"peer{len(asked)}", "X\\Song Title.flac"), result("shared", "X\\Song Title.flac")]

    client = SimpleNamespace(search=search, reputation=None)
    stats, events = {}, []

    async def on_event(ev):
        events.append(ev)

    picked = await search_multi_strategy_native(client, ARTIST, TRACK, stats=stats, on_event=on_event)
    assert asked[0] == variants[0] and sorted(asked[1:]) == sorted(variants[1:])
    assert peak == len(variants) - 1  # every fallback in flight at once
    users = [c["username"] for c in picked]
    assert len(users) == len(set(users))
    assert "shared" in users and "nobody-useful" not in users
    # funnel stats cover every query, in query order
    assert len(stats["queries"]) == len(variants) >= 3
    assert [q["q"] for q in stats["queries"]] == variants
    assert stats["files_seen"] > 0
    assert stats["rejected"]["title"] >= 1  # nobody-useful's file
    assert stats["kept"] == len(picked)
    assert stats["candidates"][0]["score"] > 0
    assert [c["username"] for c in stats["candidates"]] == users[:5]
    # one start and one end per query; the first query finishes before the fallbacks start
    assert [e["event"] for e in events[:2]] == ["query_start", "query_end"]
    starts = [e for e in events if e["event"] == "query_start"]
    ends = [e for e in events if e["event"] == "query_end"]
    assert sorted(e["i"] for e in starts) == sorted(e["i"] for e in ends) == list(range(1, len(variants) + 1))
    for e in events:
        assert e["n"] == len(variants) and e["kind"] == "variant"
    for i in range(1, len(variants) + 1):
        si = next(k for k, e in enumerate(events) if e["event"] == "query_start" and e["i"] == i)
        ei = next(k for k, e in enumerate(events) if e["event"] == "query_end" and e["i"] == i)
        assert si < ei


@pytest.mark.asyncio
async def test_album_fallback_recorded_in_stats(monkeypatch):
    import backend.services.lastfm as lastfm

    async def fake_track_info(artist, track):
        return {"album": "Let Love In"}

    monkeypatch.setattr(lastfm, "get_track_info", fake_track_info)

    async def search(q):
        if "Let Love In" in q:
            return [result("alice", "Nick Cave\\Let Love In (1994)\\05 - Red Right Hand.flac")]
        if q == "Nick Cave Red Right Hand":
            raise RuntimeError("search timed out")
        return []

    client = SimpleNamespace(search=search, reputation=None)
    stats, events = {}, []

    async def on_event(ev):
        events.append(ev)

    picked = await search_multi_strategy_native(client, "Nick Cave & The Bad Seeds", "Red Right Hand",
                                                stats=stats, on_event=on_event)
    assert [c["username"] for c in picked] == ["alice"]
    assert stats["album_query"] == "Nick Cave Let Love In"
    album = [q for q in stats["queries"] if q["kind"] == "album"]
    assert album == [{"q": "Nick Cave Let Love In", "kind": "album", "peers": 1, "files": 1}]
    # a failed query is kept in the list with its error
    failed = [q for q in stats["queries"] if "error" in q]
    assert failed and failed[0]["q"] == "Nick Cave Red Right Hand" and "timed out" in failed[0]["error"]
    n_variants = len(build_query_variants("Nick Cave & The Bad Seeds", "Red Right Hand"))
    assert len(stats["queries"]) == n_variants + 1
    album_events = [e for e in events if e["kind"] == "album"]
    assert [e["event"] for e in album_events] == ["query_start", "query_end"]
    assert album_events[0]["i"] == album_events[0]["n"] == n_variants + 1
    assert stats["candidates"][0]["username"] == "alice"


@pytest.mark.asyncio
async def test_on_event_exception_does_not_break_search():
    async def search(q):
        return [result("alice", "X\\Song Title.flac")]

    async def on_event(ev):
        raise RuntimeError("boom")

    client = SimpleNamespace(search=search, reputation=None)
    stats = {}
    picked = await search_multi_strategy_native(client, ARTIST, TRACK, stats=stats, on_event=on_event)
    assert [c["username"] for c in picked] == ["alice"]
    assert len(stats["queries"]) == 1


@pytest.mark.asyncio
async def test_pick_best_stats_count_size_ext_and_artist_path():
    results = [
        result("small", "A\\Song.flac", size=1),            # below min size
        result("doc", "A\\Song.pdf"),                       # not audio
        result("other", "A\\Different.flac"),               # title gate
        result("ok", "Artist\\Song.flac"),
    ]
    stats = {}
    picked = await pick_best_results_native(results, "Artist", "Song", stats=stats)
    assert [c["username"] for c in picked] == ["ok"]
    assert stats["peers_seen"] == 4 and stats["files_seen"] == 4
    assert stats["rejected"]["size"] == 1
    assert stats["rejected"]["ext"] == 1
    assert stats["rejected"]["title"] == 1
    assert stats["kept"] == 1

    # one-word title: a candidate whose path does not name the artist is dropped and counted
    async def search(q):
        return [result("named", "Rihanna\\Disturbia.flac"), result("unnamed", "Misc\\Disturbia.flac")]

    client = SimpleNamespace(search=search, reputation=None)
    stats = {}
    picked = await search_multi_strategy_native(client, "Rihanna", "Disturbia", stats=stats)
    assert [c["username"] for c in picked] == ["named"]
    assert stats["rejected"]["artist_path"] == 1
    assert stats["kept"] == len(picked)


# --- per-peer slot ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_peer_slot_serialises_one_peer_and_prunes():
    from backend.soulseek.client import SoulseekClient
    fake = SimpleNamespace(_peer_slots={})
    order = []

    async def job(name, user):
        async with SoulseekClient.peer_slot(fake, user):
            order.append(f"{name}+")
            await asyncio.sleep(0.02)
            order.append(f"{name}-")

    await asyncio.gather(job("a", "peer"), job("b", "peer"), job("c", "other"))
    ia, ib = order.index("a+"), order.index("b+")
    first, second = ("a", "b") if ia < ib else ("b", "a")
    assert order.index(f"{first}-") < order.index(f"{second}+")  # never overlapped on "peer"
    assert order.index("c+") < order.index(f"{second}+")  # the other peer didn't wait
    assert fake._peer_slots == {}  # idle entries pruned


@pytest.mark.asyncio
async def test_peer_slot_timeout_raises_peer_busy_and_cleans_up():
    from backend.soulseek.client import PeerBusy, SoulseekClient
    fake = SimpleNamespace(_peer_slots={})
    held = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with SoulseekClient.peer_slot(fake, "peer"):
            held.set()
            await release.wait()

    h = asyncio.create_task(holder())
    await held.wait()
    with pytest.raises(PeerBusy):
        async with SoulseekClient.peer_slot(fake, "peer", timeout=0.02):
            pass
    release.set()
    await h
    assert fake._peer_slots == {}
    # the slot is free again afterwards
    async with SoulseekClient.peer_slot(fake, "peer", timeout=0.02):
        pass


def test_clean_artist_name_strips_bands_and_suffixes():
    from backend.services.soulseek import clean_artist_name
    assert clean_artist_name("Nick Cave & The Bad Seeds") == "Nick Cave"
    assert clean_artist_name("Nick Cave and the Bad Seeds") == "Nick Cave"
    assert clean_artist_name("Tom Petty and the Heartbreakers") == "Tom Petty"
    assert clean_artist_name("Florence + The Machine") == "Florence"
    assert clean_artist_name("Bob Marley & The Wailers") == "Bob Marley"
    assert clean_artist_name("Bill Haley & His Comets") == "Bill Haley"
    assert clean_artist_name("Calvin Harris feat. Rihanna") == "Calvin Harris"
    assert clean_artist_name("David Bowie (UK)") == "David Bowie"
    assert clean_artist_name("Daft Punk / Pharrell Williams") == "Daft Punk"
    assert clean_artist_name("AC/DC") == "AC/DC"


def test_search_relevance_matches():
    from backend.services.soulseek import search_relevance_matches
    # Track title match
    assert search_relevance_matches("Nick Cave", "Red Right Hand", "05 - Red Right Hand.flac")
    # Multi-word freeform search where track is not separated
    assert search_relevance_matches("Nick Cave Red Right Hand", "", "Let Love In/05 - Red Right Hand.flac")
    assert search_relevance_matches("The Edgar Winter Group Frankenstein", "", "Edgar Winter/06 - Frankenstein.flac")
    assert search_relevance_matches("Frankenstein", "", "06 - Frankenstein.flac")
    # Irrelevant files should not match
    assert not search_relevance_matches("Nick Cave Red Right Hand", "", "Britney Spears/Toxic.flac")
    assert not search_relevance_matches("Nick Cave Red Right Hand", "", "Various Artists/The Right Stuff.flac")


def test_query_variants_with_album():
    qs = build_query_variants("Nick Cave & The Bad Seeds", "Red Right Hand", album="Let Love In")
    assert len(qs) == len(set(qs)) and 1 <= len(qs) <= 5
    assert "Nick Cave Let Love In" in qs


@pytest.mark.asyncio
async def test_fallback_album_search_when_track_fails():
    asked = []

    async def search(q):
        asked.append(q)
        # All track queries return nothing / irrelevant songs
        if "Let Love In" in q:
            return [result("alice", "Nick Cave & The Bad Seeds\\Let Love In (1994)\\05 - Red Right Hand.flac")]
        return []

    client = SimpleNamespace(search=search, reputation=None)
    picked = await search_multi_strategy_native(
        client, "Nick Cave & The Bad Seeds", "Red Right Hand", album="Let Love In"
    )
    assert any("Let Love In" in q for q in asked)
    assert len(picked) == 1
    assert picked[0]["username"] == "alice"


def test_title_matches_three_word_precision():
    from backend.services.soulseek import title_matches
    # Full match should pass
    assert title_matches("Red Right Hand", "05 - Red Right Hand.flac")
    assert title_matches("Red Right Hand", "Nick Cave & The Bad Seeds - Let Love In/05 - Red Right Hand.flac")
    # Missing one of the 3 significant words should fail
    assert not title_matches("Red Right Hand", "03 - Right Hand Man.flac")
    assert not title_matches("Red Right Hand", "01 - Darker Lord's Right Hand.flac")


@pytest.mark.asyncio
async def test_search_soulseek_endpoint_fallback(monkeypatch):
    from backend.api.download import search_soulseek, SearchRequest
    from unittest.mock import AsyncMock

    asked_queries = []

    async def fake_search(query, timeout=25, max_responses=100):
        asked_queries.append(query)
        if query.lower() == "red right hand":
            # Primary search produces 0 results (Soulseek token quirk)
            return []
        if "right hand" in query.lower() or "let love in" in query.lower():
            return [
                SearchResult(
                    username="peer1",
                    token="t",
                    files=[FileInfo(filename="Nick Cave & The Bad Seeds\\05 - Red Right Hand.flac", size=45 * MB)],
                    slots_free=True,
                    avg_speed=5000000,
                    queue_length=0,
                )
            ]
        return []

    mock_rep = AsyncMock()
    mock_rep.get_score_adjustment.return_value = 0

    fake_client = SimpleNamespace(
        logged_in=True,
        search=fake_search,
        reputation=mock_rep,
    )
    monkeypatch.setattr("backend.soulseek.get_client", lambda: fake_client)
    monkeypatch.setattr("backend.api.download.is_blacklisted", AsyncMock(return_value=None))
    monkeypatch.setattr("backend.api.download.find_in_library", AsyncMock(return_value=None))

    # Freeform search for "red right hand"
    mock_db = AsyncMock()
    res = await search_soulseek(SearchRequest(query="red right hand", timeout=5), db=mock_db)
    assert res["count"] >= 1
    assert any("Red Right Hand" in r["filename"] for r in res["results"])
    assert any(q != "red right hand" for q in asked_queries)

