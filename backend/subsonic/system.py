"""Subsonic system endpoints: ping, getLicense, getOpenSubsonicExtensions."""
from __future__ import annotations

from fastapi import APIRouter, Request

from backend.subsonic.responses import subsonic_response

router = APIRouter()


def _get_format(request: Request) -> str:
    return request.query_params.get("f", "json")


@router.get("/ping")
@router.get("/ping.view")
async def ping(request: Request):
    return subsonic_response({}, _get_format(request))


@router.get("/getLicense")
@router.get("/getLicense.view")
async def get_license(request: Request):
    return subsonic_response({
        "license": {
            "valid": "true",
            "email": "zonik@localhost",
        }
    }, _get_format(request))


@router.get("/getOpenSubsonicExtensions")
@router.get("/getOpenSubsonicExtensions.view")
async def get_open_subsonic_extensions(request: Request):
    return subsonic_response({
        "openSubsonicExtensions": [
            {"name": "songLyrics", "versions": [1]},
            {"name": "transcodeOffset", "versions": [1]},
            {"name": "formPost", "versions": [1]},
            {"name": "mediaType", "versions": [1]},
        ]
    }, _get_format(request))
