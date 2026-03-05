"""Binary message decoder for Soulseek protocol."""
from __future__ import annotations

import struct


class MessageParser:
    """Parses length-prefixed Soulseek protocol messages."""

    __slots__ = ("data", "pos")

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def uint8(self) -> int:
        if self.pos + 1 > len(self.data):
            raise BufferError("Cannot read uint8: buffer underflow")
        val = struct.unpack_from("<B", self.data, self.pos)[0]
        self.pos += 1
        return val

    def uint32(self) -> int:
        if self.pos + 4 > len(self.data):
            raise BufferError("Cannot read uint32: buffer underflow")
        val = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return val

    def uint64(self) -> int:
        if self.pos + 8 > len(self.data):
            raise BufferError("Cannot read uint64: buffer underflow")
        val = struct.unpack_from("<Q", self.data, self.pos)[0]
        self.pos += 8
        return val

    def string(self) -> str:
        length = self.uint32()
        if self.pos + length > len(self.data):
            raise BufferError("Cannot read string: buffer underflow")
        val = self.data[self.pos:self.pos + length].decode("utf-8", errors="replace")
        self.pos += length
        return val

    def raw(self, size: int) -> bytes:
        if self.pos + size > len(self.data):
            raise BufferError("Cannot read raw bytes: buffer underflow")
        val = self.data[self.pos:self.pos + size]
        self.pos += size
        return val

    def remaining(self) -> bytes:
        return self.data[self.pos:]

    def has_remaining(self) -> bool:
        return self.pos < len(self.data)
