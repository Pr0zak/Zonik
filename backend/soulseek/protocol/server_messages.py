"""Server message encoding/decoding for Soulseek protocol."""
from __future__ import annotations

import hashlib

from backend.soulseek.protocol.builder import MessageBuilder
from backend.soulseek.protocol.parser import MessageParser
from backend.soulseek.protocol.types import (
    ServerMessageCode, ConnectionType, PeerAddress,
)


# --- Encoders (client → server) ---

def build_login(username: str, password: str) -> bytes:
    md5_hash = hashlib.md5((username + password).encode()).hexdigest()
    return (
        MessageBuilder()
        .uint32(ServerMessageCode.LOGIN)
        .string(username)
        .string(password)
        .uint32(160)  # version
        .string(md5_hash)
        .uint32(17)  # minor version
        .build()
    )


def build_set_wait_port(port: int) -> bytes:
    return MessageBuilder().uint32(ServerMessageCode.SET_WAIT_PORT).uint32(port).build()


def build_get_peer_address(username: str) -> bytes:
    return MessageBuilder().uint32(ServerMessageCode.GET_PEER_ADDRESS).string(username).build()


def build_file_search(token: bytes, query: str) -> bytes:
    return (
        MessageBuilder()
        .uint32(ServerMessageCode.FILE_SEARCH)
        .raw(token)
        .string(query)
        .build()
    )


def build_set_status(status: int) -> bytes:
    return MessageBuilder().uint32(ServerMessageCode.SET_STATUS).uint32(status).build()


def build_shared_folders_files(dirs: int, files: int) -> bytes:
    return (
        MessageBuilder()
        .uint32(ServerMessageCode.SHARED_FOLDERS_FILES)
        .uint32(dirs)
        .uint32(files)
        .build()
    )


def build_have_no_parents(have_no_parents: bool) -> bytes:
    return (
        MessageBuilder()
        .uint32(ServerMessageCode.HAVE_NO_PARENTS)
        .uint32(1 if have_no_parents else 0)
        .build()
    )


def build_connect_to_peer(token: bytes, username: str, conn_type: str) -> bytes:
    return (
        MessageBuilder()
        .uint32(ServerMessageCode.CONNECT_TO_PEER)
        .raw(token)
        .string(username)
        .string(conn_type)
        .build()
    )


def build_cant_connect_to_peer(token: bytes, username: str) -> bytes:
    return (
        MessageBuilder()
        .uint32(ServerMessageCode.CANT_CONNECT_TO_PEER)
        .raw(token)
        .string(username)
        .build()
    )


# --- Decoders (server → client) ---

def parse_server_message(data: bytes) -> dict | None:
    """Parse a server message payload (without length prefix). Returns typed dict or None."""
    msg = MessageParser(data)
    code = msg.uint32()

    if code == ServerMessageCode.LOGIN:
        success = msg.uint8()
        if success == 1:
            greet = msg.string()
            return {"kind": "login", "success": True, "greet": greet}
        else:
            reason = msg.string()
            return {"kind": "login", "success": False, "reason": reason}

    elif code == ServerMessageCode.GET_PEER_ADDRESS:
        username = msg.string()
        ip_bytes = [msg.uint8() for _ in range(4)]
        host = f"{ip_bytes[3]}.{ip_bytes[2]}.{ip_bytes[1]}.{ip_bytes[0]}"
        port = msg.uint32()
        return {"kind": "get_peer_address", "username": username, "host": host, "port": port}

    elif code == ServerMessageCode.GET_USER_STATUS:
        username = msg.string()
        status = msg.uint32()
        return {"kind": "get_user_status", "username": username, "status": status}

    elif code == ServerMessageCode.CONNECT_TO_PEER:
        username = msg.string()
        conn_type = msg.string()
        ip_bytes = [msg.uint8() for _ in range(4)]
        host = f"{ip_bytes[3]}.{ip_bytes[2]}.{ip_bytes[1]}.{ip_bytes[0]}"
        port = msg.uint32()
        token = msg.raw(4)
        return {
            "kind": "connect_to_peer",
            "username": username,
            "type": conn_type,
            "host": host,
            "port": port,
            "token": token,
        }

    elif code == ServerMessageCode.GET_USER_STATS:
        username = msg.string()
        avg_speed = msg.uint32()
        upload_num = msg.uint32()
        msg.uint32()  # unknown
        files = msg.uint32()
        dirs = msg.uint32()
        return {
            "kind": "get_user_stats",
            "username": username,
            "avg_speed": avg_speed,
            "upload_num": upload_num,
            "files": files,
            "dirs": dirs,
        }

    elif code == ServerMessageCode.ROOM_LIST:
        num = msg.uint32()
        names = [msg.string() for _ in range(num)]
        users = [msg.uint32() for _ in range(num)]
        return {
            "kind": "room_list",
            "rooms": [{"name": n, "users": u} for n, u in zip(names, users)],
        }

    elif code == ServerMessageCode.POSSIBLE_PARENTS:
        num = msg.uint32()
        parents = []
        for _ in range(num):
            username = msg.string()
            ip_bytes = [msg.uint8() for _ in range(4)]
            host = f"{ip_bytes[3]}.{ip_bytes[2]}.{ip_bytes[1]}.{ip_bytes[0]}"
            port = msg.uint32()
            parents.append({"username": username, "host": host, "port": port})
        return {"kind": "possible_parents", "parents": parents}

    return None
