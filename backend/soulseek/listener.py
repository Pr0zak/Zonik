"""Inbound peer listener — accepts incoming peer connections on a TCP port."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from backend.soulseek.protocol.peer_messages import parse_peer_init_message

log = logging.getLogger(__name__)


class PeerListener:
    """TCP server that accepts inbound peer connections (pierce firewall / peer init)."""

    def __init__(
        self,
        port: int = 2234,
        on_connection: Callable[[dict, asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]] | None = None,
    ):
        self.port = port
        self.on_connection = on_connection
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, "0.0.0.0", self.port
        )
        log.info(f"[listener] Listening on port {self.port}")

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            # Read the first message (peer init or pierce firewall)
            header = await asyncio.wait_for(reader.readexactly(4), timeout=10)
            import struct
            length = struct.unpack("<I", header)[0]
            if length > 1024:  # Sanity check
                writer.close()
                return

            payload = await asyncio.wait_for(reader.readexactly(length), timeout=10)
            data = header + payload  # Re-assemble with length prefix for parser

            msg = parse_peer_init_message(data)
            if msg and self.on_connection:
                await self.on_connection(msg, reader, writer)
            else:
                writer.close()
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, OSError) as e:
            log.info(f"[listener] Inbound connection error: {e}")
            try:
                writer.close()
            except Exception:
                pass
        except Exception as e:
            log.error(f"[listener] Unexpected error handling inbound: {e}")
            try:
                writer.close()
            except Exception:
                pass

    def destroy(self) -> None:
        if self._server:
            self._server.close()
            self._server = None
