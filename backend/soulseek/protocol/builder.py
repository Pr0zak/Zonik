"""Binary message encoder for Soulseek protocol."""
from __future__ import annotations

import struct


class MessageBuilder:
    """Builds length-prefixed Soulseek protocol messages."""

    __slots__ = ("_parts",)

    def __init__(self):
        self._parts: list[bytes] = []

    def uint8(self, value: int) -> MessageBuilder:
        self._parts.append(struct.pack("<B", value))
        return self

    def uint32(self, value: int) -> MessageBuilder:
        self._parts.append(struct.pack("<I", value))
        return self

    def uint64(self, value: int) -> MessageBuilder:
        self._parts.append(struct.pack("<Q", value))
        return self

    def string(self, value: str) -> MessageBuilder:
        encoded = value.encode("utf-8")
        self._parts.append(struct.pack("<I", len(encoded)))
        self._parts.append(encoded)
        return self

    def raw(self, data: bytes) -> MessageBuilder:
        self._parts.append(data)
        return self

    def build(self) -> bytes:
        """Build the message with 4-byte length prefix."""
        payload = b"".join(self._parts)
        return struct.pack("<I", len(payload)) + payload

    def build_no_prefix(self) -> bytes:
        """Build message without length prefix (for pierce firewall on transfer conn)."""
        return b"".join(self._parts)
