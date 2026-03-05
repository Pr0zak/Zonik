"""Peer message encoding/decoding for Soulseek protocol."""
from __future__ import annotations

import zlib

from backend.soulseek.protocol.builder import MessageBuilder
from backend.soulseek.protocol.parser import MessageParser
from backend.soulseek.protocol.types import (
    PeerMessageCode, PeerInitCode, TransferDirection,
    FileAttribute, FileInfo, SearchResult,
)

MAX_DECOMPRESS_SIZE = 10 * 1024 * 1024  # 10 MB


# --- Encoders (client → peer) ---

def build_pierce_firewall(token: bytes) -> bytes:
    """Build pierce firewall message (peer init, code 0)."""
    return MessageBuilder().uint8(PeerInitCode.PIERCE_FIREWALL).raw(token).build()


def build_peer_init(username: str, conn_type: str, token: bytes) -> bytes:
    """Build peer init message (code 1)."""
    return (
        MessageBuilder()
        .uint8(PeerInitCode.PEER_INIT)
        .string(username)
        .string(conn_type)
        .raw(token)
        .build()
    )


def build_queue_upload(filename: str) -> bytes:
    return MessageBuilder().uint32(PeerMessageCode.QUEUE_UPLOAD).string(filename).build()


def build_place_in_queue_request(filename: str) -> bytes:
    return MessageBuilder().uint32(PeerMessageCode.PLACE_IN_QUEUE_REQUEST).string(filename).build()


def build_transfer_response(token: bytes, allowed: bool, reason: str = "") -> bytes:
    b = MessageBuilder().uint32(PeerMessageCode.TRANSFER_RESPONSE).raw(token)
    if allowed:
        b.uint8(1)
    else:
        b.uint8(0).string(reason)
    return b.build()


def build_pierce_firewall_raw(token: bytes) -> bytes:
    """Build pierce firewall for file transfer connection (no length prefix wrapping)."""
    return MessageBuilder().uint8(PeerInitCode.PIERCE_FIREWALL).raw(token).build()


# --- Decoders ---

def parse_peer_init_message(data: bytes) -> dict | None:
    """Parse a peer init message (pierce firewall or peer init)."""
    msg = MessageParser(data)
    # Peer init messages have their own length prefix
    size = msg.uint32()
    if size <= 0:
        return None

    code = msg.uint8()
    if code == PeerInitCode.PIERCE_FIREWALL:
        token = msg.raw(4)
        return {"kind": "pierce_firewall", "token": token}
    elif code == PeerInitCode.PEER_INIT:
        username = msg.string()
        conn_type = msg.string()
        token = msg.raw(4)
        return {"kind": "peer_init", "username": username, "type": conn_type, "token": token}
    return None


def parse_peer_message(data: bytes) -> dict | None:
    """Parse a peer message payload (without length prefix)."""
    msg = MessageParser(data)
    code = msg.uint32()

    if code == PeerMessageCode.SHARED_FILE_LIST_REQUEST:
        return {"kind": "shared_file_list_request"}

    elif code == PeerMessageCode.FILE_SEARCH_RESPONSE:
        return _parse_file_search_response(msg)

    elif code == PeerMessageCode.TRANSFER_REQUEST:
        direction = msg.uint32()
        token = msg.raw(4)
        filename = msg.string()
        if direction == TransferDirection.UPLOAD:
            size = msg.uint64()
            return {"kind": "transfer_request", "direction": direction, "token": token, "filename": filename, "size": size}
        return {"kind": "transfer_request", "direction": direction, "token": token, "filename": filename}

    elif code == PeerMessageCode.TRANSFER_RESPONSE:
        token = msg.raw(4)
        allowed = msg.uint8()
        if allowed == 0:
            reason = msg.string()
            return {"kind": "transfer_response", "token": token, "allowed": False, "reason": reason}
        return {"kind": "transfer_response", "token": token, "allowed": True}

    elif code == PeerMessageCode.PLACE_IN_QUEUE_RESPONSE:
        filename = msg.string()
        place = msg.uint32()
        return {"kind": "place_in_queue_response", "filename": filename, "place": place}

    elif code == PeerMessageCode.UPLOAD_FAILED:
        filename = msg.string()
        return {"kind": "upload_failed", "filename": filename}

    elif code == PeerMessageCode.UPLOAD_DENIED:
        filename = msg.string()
        reason = msg.string()
        return {"kind": "upload_denied", "filename": filename, "reason": reason}

    return None


def _parse_file_search_response(msg: MessageParser) -> dict:
    """Parse zlib-compressed file search response."""
    compressed = msg.remaining()
    decompressed = zlib.decompress(compressed, bufsize=MAX_DECOMPRESS_SIZE)
    inner = MessageParser(decompressed)

    username = inner.string()
    token = inner.raw(4)
    num_results = inner.uint32()

    files: list[FileInfo] = []
    for _ in range(num_results):
        inner.uint8()  # code
        filename = inner.string()
        size = inner.uint64()
        inner.string()  # extension
        num_attrs = inner.uint32()
        attrs = {}
        for _ in range(num_attrs):
            attr_type = inner.uint32()
            attr_value = inner.uint32()
            attrs[attr_type] = attr_value
        files.append(FileInfo(filename=filename, size=size, attrs=attrs))

    slots_free = inner.uint8() > 0
    avg_speed = inner.uint32()
    queue_length = inner.uint32()

    return {
        "kind": "file_search_response",
        "username": username,
        "token": token,
        "files": files,
        "slots_free": slots_free,
        "avg_speed": avg_speed,
        "queue_length": queue_length,
    }
