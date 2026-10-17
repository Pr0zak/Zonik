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


@pytest.mark.asyncio
async def test_stale_read_loop_does_not_start_a_second_reconnect_chain():
    from backend.soulseek.server_conn import ServerConnection

    class FakeStream:
        def __init__(self): self.closed = False
        async def read_message(self): return None
        def close(self): self.closed = True

    conn = ServerConnection()
    conn._credentials = ("u", "p")
    scheduled = []
    conn._schedule_reconnect = lambda *a, **k: scheduled.append(1)
    old = FakeStream()
    conn._gen, conn._stream, conn._connected = 1, old, True
    # A newer connection exists by the time the old loop ends.
    conn._gen, conn._stream = 2, FakeStream()
    conn.logged_in = True
    await conn._read_loop(1, old)
    assert old.closed
    assert conn.logged_in and not scheduled
    # The current connection's loop ending does trigger exactly one reconnect.
    await conn._read_loop(2, conn._stream)
    assert not conn.logged_in and scheduled == [1]


@pytest.mark.asyncio
async def test_peer_stream_closed_when_peer_hangs_up():
    from backend.soulseek.peer import PeerConnection

    reader = asyncio.StreamReader(); reader.feed_eof()
    closed = []

    class W:
        def close(self): closed.append(1)
        def is_closing(self): return bool(closed)
        def write(self, d): pass
        async def drain(self): pass

    peer = PeerConnection(reader, W(), "someone")
    peer.start_reading()
    await asyncio.sleep(0.05)
    assert closed
