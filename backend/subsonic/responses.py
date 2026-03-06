"""Subsonic/OpenSubsonic XML and JSON response builder."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

from fastapi.responses import Response


SUBSONIC_API_VERSION = "1.16.1"
XMLNS = "http://subsonic.org/restapi"


def _format_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def subsonic_response(data: dict, request_format: str = "json", status: str = "ok") -> Response:
    """Build a Subsonic API response in JSON or XML format."""
    if request_format == "xml":
        return _xml_response(data, status)
    return _json_response(data, status)


def _json_response(data: dict, status: str) -> Response:
    import json
    envelope = {
        "subsonic-response": {
            "status": status,
            "version": SUBSONIC_API_VERSION,
            "type": "zonik",
            "serverVersion": "0.1.0",
            "openSubsonic": True,
            **data,
        }
    }
    return Response(
        content=json.dumps(envelope),
        media_type="application/json",
    )


def error_response(code: int, message: str, request_format: str = "json") -> Response:
    return subsonic_response(
        {"error": {"code": code, "message": message}},
        request_format,
        status="failed",
    )


def _xml_response(data: dict, status: str) -> Response:
    root = ET.Element("subsonic-response", {
        "xmlns": XMLNS,
        "status": status,
        "version": SUBSONIC_API_VERSION,
        "type": "zonik",
        "serverVersion": "0.1.0",
        "openSubsonic": "true",
    })
    _dict_to_xml(root, data)
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
    return Response(content=xml_str, media_type="application/xml")


def _dict_to_xml(parent: ET.Element, data: dict):
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, dict):
            child = ET.SubElement(parent, key)
            for k, v in value.items():
                if isinstance(v, (list,)):
                    for item in v:
                        if isinstance(item, dict):
                            sub = ET.SubElement(child, _singular(k))
                            for ik, iv in item.items():
                                if iv is not None:
                                    sub.set(str(ik), str(iv))
                        else:
                            sub = ET.SubElement(child, _singular(k))
                            sub.text = str(item)
                elif isinstance(v, dict):
                    sub = ET.SubElement(child, k)
                    _dict_to_xml(sub, v)
                elif v is not None:
                    child.set(str(k), str(v))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    child = ET.SubElement(parent, _singular(key))
                    for k, v in item.items():
                        if v is not None:
                            child.set(str(k), str(v))


def _singular(name: str) -> str:
    """Simple pluralization reversal."""
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def format_track(track, starred: bool = False) -> dict:
    """Format a track for Subsonic API responses."""
    from backend.models.track import Track
    data = {
        "id": track.id,
        "parent": track.album_id or track.artist_id or "1",
        "isDir": False,
        "title": track.title,
        "album": track.album.title if track.album else "",
        "artist": track.artist.name if track.artist else "",
        "track": track.track_number,
        "year": track.year,
        "genre": track.genre,
        "coverArt": track.id if (track.cover_art_path or (track.album and track.album.cover_art_path)) else None,
        "size": track.file_size,
        "contentType": track.mime_type or "audio/mpeg",
        "suffix": track.suffix,
        "duration": int(track.duration_seconds) if track.duration_seconds else 0,
        "bitRate": (track.bitrate // 1000) if track.bitrate else None,
        "path": track.file_path,
        "isVideo": False,
        "discNumber": track.disc_number,
        "type": "music",
        "albumId": track.album_id,
        "artistId": track.artist_id,
        "playCount": track.play_count,
        "userRating": track.rating,
        "created": _format_dt(track.created_at),
    }
    if starred:
        data["starred"] = _format_dt(datetime.utcnow())
    if track.musicbrainz_id:
        data["musicBrainzId"] = track.musicbrainz_id
    # OpenSubsonic extensions
    if track.analysis:
        data["bpm"] = int(round(track.analysis.bpm))
    if track.replay_gain_track is not None:
        data["replayGain"] = {
            "trackGain": track.replay_gain_track,
            "albumGain": track.replay_gain_album,
        }
    if track.play_count and track.last_played_at:
        data["played"] = _format_dt(track.last_played_at)

    # Remove None values
    return {k: v for k, v in data.items() if v is not None}


def format_album(album, tracks=None, starred: bool = False) -> dict:
    data = {
        "id": album.id,
        "name": album.title,
        "artist": album.artist.name if album.artist else None,
        "artistId": album.artist_id,
        "coverArt": album.id if album.cover_art_path else None,
        "songCount": album.track_count or 0,
        "duration": 0,
        "year": album.year,
        "genre": album.genre,
        "created": _format_dt(album.created_at),
    }
    if starred:
        data["starred"] = _format_dt(datetime.utcnow())
    if tracks:
        data["duration"] = sum(int(t.duration_seconds or 0) for t in tracks)
        data["song"] = [format_track(t) for t in tracks]
    return {k: v for k, v in data.items() if v is not None}


def format_artist(artist, albums=None, starred: bool = False) -> dict:
    data = {
        "id": artist.id,
        "name": artist.name,
        "coverArt": artist.id if artist.image_url else None,
        "albumCount": len(albums) if albums else 0,
    }
    if starred:
        data["starred"] = _format_dt(datetime.utcnow())
    if artist.musicbrainz_id:
        data["musicBrainzId"] = artist.musicbrainz_id
    if albums:
        data["album"] = [format_album(a) for a in albums]
    return {k: v for k, v in data.items() if v is not None}
