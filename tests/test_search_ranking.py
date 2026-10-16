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
    picked = await search_multi_strategy_native(client, ARTIST, TRACK)
    assert asked == build_query_variants(ARTIST, TRACK)[:1]
    assert [c["username"] for c in picked] == ["alice"]


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
    picked = await search_multi_strategy_native(client, ARTIST, TRACK)
    assert asked[0] == variants[0] and sorted(asked[1:]) == sorted(variants[1:])
    assert peak == len(variants) - 1  # every fallback in flight at once
    users = [c["username"] for c in picked]
    assert len(users) == len(set(users))
    assert "shared" in users and "nobody-useful" not in users


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
