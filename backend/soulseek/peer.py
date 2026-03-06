"""Peer connection — handles messaging with a single Soulseek user."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from backend.soulseek.protocol.stream import MessageStream
from backend.soulseek.protocol.peer_messages import (
    build_queue_upload, build_place_in_queue_request,
    build_transfer_response, build_peer_init, build_pierce_firewall,
    parse_peer_message,
)

log = logging.getLogger(__name__)


class PeerConnection:
    """A single peer-to-peer connection with a Soulseek user."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        username: str,
        on_message: Callable[[dict, "PeerConnection"], Awaitable[None]] | None = None,
        on_close: Callable[["PeerConnection"], Awaitable[None]] | None = None,
    ):
        self.username = username
        self.on_message = on_message
        self.on_close = on_close
        self._stream = MessageStream(reader, writer)
        self._read_task: asyncio.Task | None = None

    def start_reading(self) -> None:
        self._read_task = asyncio.create_task(self._read_loop())

    @classmethod
    async def connect_direct(
        cls,
        host: str,
        port: int,
        username: str,
        on_message: Callable[[dict, "PeerConnection"], Awaitable[None]] | None = None,
        on_close: Callable[["PeerConnection"], Awaitable[None]] | None = None,
        timeout: float = 10.0,
    ) -> PeerConnection:
        """Connect to a peer directly by IP:port."""
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        return cls(reader, writer, username, on_message, on_close)

    async def send_peer_init(self, our_username: str, conn_type: str, token: bytes) -> None:
        self._stream.write_message(build_peer_init(our_username, conn_type, token))
        await self._stream.drain()

    async def send_pierce_firewall(self, token: bytes) -> None:
        self._stream.write_message(build_pierce_firewall(token))
        await self._stream.drain()

    async def send_queue_upload(self, filename: str) -> None:
        self._stream.write_message(build_queue_upload(filename))
        await self._stream.drain()

    async def send_place_in_queue_request(self, filename: str) -> None:
        self._stream.write_message(build_place_in_queue_request(filename))
        await self._stream.drain()

    async def send_transfer_response(self, token: bytes, allowed: bool, reason: str = "") -> None:
        self._stream.write_message(build_transfer_response(token, allowed, reason))
        await self._stream.drain()

    async def send_raw(self, data: bytes) -> None:
        """Send a pre-built message (already has length prefix)."""
        self._stream.writer.write(data)
        await self._stream.drain()

    async def _read_loop(self) -> None:
        try:
            while True:
                payload = await self._stream.read_message()
                if payload is None:
                    break
                try:
                    msg = parse_peer_message(payload)
                    if msg and self.on_message:
                        await self.on_message(msg, self)
                except Exception as e:
                    log.error(f"[peer:{self.username}] Error parsing message: {e}")
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.debug(f"[peer:{self.username}] Read loop ended: {e}")
        finally:
            if self.on_close:
                await self.on_close(self)

    def destroy(self) -> None:
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
        if self._stream:
            self._stream.close()
