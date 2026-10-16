"""Native search ranking: the duration gate and the query-variant merge.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_search_ranking.py
"""
import pytest

from backend.soulseek.protocol.types import FileAttribute, FileInfo, SearchResult
from backend.soulseek.search import pick_best_results_native

pytestmark = pytest.mark.asyncio

MB = 1024 * 1024


def result(user, filename, duration=None, size=30 * MB):
    attrs = {FileAttribute.DURATION: duration} if duration is not None else {}
    return SearchResult(username=user, token="00", files=[FileInfo(filename, size, attrs)],
                        slots_free=True, avg_speed=0, queue_length=0)


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


async def test_duration_gate_tolerance_is_three_seconds():
    results = [
        result("plus3", "A\\Song.flac", duration=183),
        result("minus4", "B\\Song.flac", duration=176),
    ]
    picked = await pick_best_results_native(results, "Artist", "Song", target_duration=180)
    assert [c["username"] for c in picked] == ["plus3"]


async def test_no_target_duration_keeps_everything():
    results = [result("a", "A\\Song.flac", duration=100), result("b", "B\\Song.flac", duration=300)]
    picked = await pick_best_results_native(results, "Artist", "Song")
    assert {c["username"] for c in picked} == {"a", "b"}
