"""Length-prefixed TCP message framing for Soulseek protocol."""
from __future__ import annotations

import asyncio
import struct
import logging

log = logging.getLogger(__name__)


class MessageStream:
    """Reads length-prefixed messages from an asyncio StreamReader.

    Soulseek messages are: [4-byte LE length][payload of that length]
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer

    async def read_message(self) -> bytes | None:
        """Read one complete message. Returns None on EOF."""
        try:
            header = await self.reader.readexactly(4)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            return None

        length = struct.unpack("<I", header)[0]
        if length > 50 * 1024 * 1024:  # 50MB sanity limit
            log.warning(f"[stream] Message too large: {length} bytes, dropping")
            return None

        try:
            payload = await self.reader.readexactly(length)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            return None

        return payload

    def write_message(self, data: bytes) -> None:
        """Write a pre-built message (already has length prefix from builder.build())."""
        self.writer.write(data)

    async def drain(self) -> None:
        await self.writer.drain()

    def close(self) -> None:
        try:
            self.writer.close()
        except Exception:
            pass

    async def wait_closed(self) -> None:
        try:
            await self.writer.wait_closed()
        except Exception:
            pass
