"""ServerConnection reports when an outage began and whether it is reconnecting."""
import asyncio

import pytest

from backend.soulseek.server_conn import ServerConnection


class FakeStream:
    def __init__(self):
        self.closed = False
        self.sent = []
        self.on_drain = None

    async def read_message(self):
        return None

    def write_message(self, data):
        self.sent.append(data)

    async def drain(self):
        if self.on_drain:
            cb, self.on_drain = self.on_drain, None
            await cb()

    def close(self):
        self.closed = True


def _conn():
    conn = ServerConnection()
    conn._credentials = ("u", "p")
    conn._had_session = True  # reconnects only follow a session that had logged in
    return conn


@pytest.mark.asyncio
async def test_current_read_loop_ending_marks_outage_and_reconnecting():
    conn = _conn()
    gate = asyncio.Event()

    async def never_reconnects():
        await gate.wait()  # stands in for the real loop's backoff sleep

    conn._reconnect_loop = never_reconnects
    stream = FakeStream()
    conn._gen, conn._stream, conn._connected, conn.logged_in = 1, stream, True, True
    assert conn.disconnected_since is None and not conn.reconnecting

    await conn._read_loop(1, stream)
    try:
        assert not conn.logged_in
        first = conn.disconnected_since
        assert isinstance(first, float) and first > 0
        assert conn.reconnecting
        # A second drop during the same outage keeps the original start time.
        conn._drop_stream()
        assert conn.disconnected_since == first
    finally:
        conn._reconnect_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await conn._reconnect_task
    assert not conn.reconnecting


@pytest.mark.asyncio
async def test_stale_read_loop_leaves_disconnected_since_unset():
    conn = _conn()
    scheduled = []
    conn._schedule_reconnect = lambda *a, **k: scheduled.append(1)
    old = FakeStream()
    conn._gen, conn._stream, conn._connected = 1, old, True
    conn._gen, conn._stream = 2, FakeStream()  # a newer connection exists
    conn.logged_in = True

    await conn._read_loop(1, old)
    assert conn.disconnected_since is None
    assert conn.logged_in and not scheduled and not conn.reconnecting


def test_drop_stream_marks_outage():
    conn = _conn()
    conn._stream, conn._connected, conn.logged_in = FakeStream(), True, True
    conn._drop_stream()
    assert conn.disconnected_since is not None and not conn.logged_in


@pytest.mark.asyncio
async def test_login_clears_disconnected_since():
    conn = _conn()
    conn.disconnected_since = 1234.0
    stream = FakeStream()
    conn._stream, conn._connected = stream, True

    async def answer_login():
        await conn.on_message({"kind": "login", "success": True})

    stream.on_drain = answer_login
    try:
        result = await conn.login("u", "p", timeout=1.0)
        assert result["success"]
        assert conn.logged_in
        assert conn.disconnected_since is None
        assert conn.connected_since is not None
        assert not conn.reconnecting
    finally:
        conn.destroy()
