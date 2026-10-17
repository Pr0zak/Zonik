"""The client spaces out searches sent to the Soulseek server."""
import asyncio

import pytest

from backend.soulseek.client import SoulseekClient


@pytest.mark.asyncio
async def test_searches_are_spaced_and_capped(monkeypatch):
    from backend import config
    cfg = config.get_settings().soulseek
    monkeypatch.setattr(cfg, "search_min_interval_s", 0.05, raising=False)
    monkeypatch.setattr(cfg, "searches_per_minute", 3, raising=False)
    client = SoulseekClient.__new__(SoulseekClient)
    loop = asyncio.get_running_loop()
    times = []

    async def one():
        await client._pace_search()
        times.append(loop.time())

    # Three go out spaced by the minimum gap; a fourth would wait ~60 s for the cap.
    await asyncio.gather(one(), one(), one())
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(g >= 0.045 for g in gaps)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(one(), 0.5)


def test_reconnect_backs_off_once_logins_go_unanswered():
    from backend.soulseek.server_conn import ServerConnection
    assert [ServerConnection.reconnect_delay(n) for n in range(8)] == [1, 2, 4, 60, 120, 240, 480, 900]
    assert ServerConnection.reconnect_delay(20) == 900
