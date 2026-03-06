"""Soulseek protocol constants and data types."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class ServerMessageCode(IntEnum):
    LOGIN = 1
    SET_WAIT_PORT = 2
    GET_PEER_ADDRESS = 3
    WATCH_USER = 5
    GET_USER_STATUS = 7
    CONNECT_TO_PEER = 18
    FILE_SEARCH = 26
    SET_STATUS = 28
    SHARED_FOLDERS_FILES = 35
    GET_USER_STATS = 36
    ROOM_LIST = 64
    HAVE_NO_PARENTS = 71
    SEARCH_PARENT = 73
    POSSIBLE_PARENTS = 102
    CANT_CONNECT_TO_PEER = 1001


class PeerMessageCode(IntEnum):
    SHARED_FILE_LIST_REQUEST = 4
    SHARED_FILE_LIST_RESPONSE = 5
    FILE_SEARCH_RESPONSE = 9
    TRANSFER_REQUEST = 40
    TRANSFER_RESPONSE = 41
    QUEUE_UPLOAD = 43
    PLACE_IN_QUEUE_RESPONSE = 44
    UPLOAD_FAILED = 46
    UPLOAD_DENIED = 50
    PLACE_IN_QUEUE_REQUEST = 51


class PeerInitCode(IntEnum):
    PIERCE_FIREWALL = 0
    PEER_INIT = 1


class ConnectionType:
    PEER_TO_PEER = "P"
    FILE_TRANSFER = "F"
    DISTRIBUTED = "D"


class UserStatus(IntEnum):
    OFFLINE = 0
    AWAY = 1
    ONLINE = 2


class TransferDirection(IntEnum):
    DOWNLOAD = 0
    UPLOAD = 1


class FileAttribute(IntEnum):
    BITRATE = 0
    DURATION = 1
    VBR = 2
    ENCODER = 3
    SAMPLE_RATE = 4
    BIT_DEPTH = 5


class TransferState:
    REQUESTED = "requested"
    QUEUED = "queued"
    CONNECTED = "connected"
    TRANSFERRING = "transferring"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"


@dataclass
class FileInfo:
    filename: str
    size: int
    attrs: dict[int, int] = field(default_factory=dict)

    @property
    def bitrate(self) -> int:
        return self.attrs.get(FileAttribute.BITRATE, 0)

    @property
    def duration(self) -> int:
        return self.attrs.get(FileAttribute.DURATION, 0)


@dataclass
class SearchResult:
    username: str
    token: str
    files: list[FileInfo]
    slots_free: bool = False
    avg_speed: int = 0
    queue_length: int = 0


@dataclass
class PeerAddress:
    host: str
    port: int
