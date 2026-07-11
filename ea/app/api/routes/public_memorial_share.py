from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.routes.public_memorial_surface_support import (
    _load_memorial,
    _public_memorial_archive_registry,
)
from app.services.memorial_share_packet import (
    MemorialSharePacketError,
    build_memorial_share_packet,
)


router = APIRouter(tags=["public-memorial-share"])

_MAX_REQUEST_BYTES = 24_000
_RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow",
}


def _error(code: str, *, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        {"detail": str(code or "memorial_share_packet_invalid")},
        status_code=status_code,
        headers=_RESPONSE_HEADERS,
    )


async def _bounded_json_object(request: Request) -> dict[str, object]:
    raw_length = str(request.headers.get("content-length") or "").strip()
    if raw_length:
        try:
            if int(raw_length) > _MAX_REQUEST_BYTES:
                raise MemorialSharePacketError("memorial_share_request_too_large")
        except ValueError as exc:
            raise MemorialSharePacketError(
                "memorial_share_content_length_invalid"
            ) from exc
    payload_bytes = await request.body()
    if len(payload_bytes) > _MAX_REQUEST_BYTES:
        raise MemorialSharePacketError("memorial_share_request_too_large")
    try:
        payload = json.loads(payload_bytes or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MemorialSharePacketError("memorial_share_request_invalid_json") from exc
    if not isinstance(payload, dict):
        raise MemorialSharePacketError("memorial_share_request_invalid")
    return payload


def _list_value(payload: dict[str, object], key: str) -> list[object] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise MemorialSharePacketError(f"memorial_share_{key}_invalid")
    return list(value)


@router.post("/memorials/{slug}/share-drafts")
async def public_memorial_share_drafts(slug: str, request: Request) -> JSONResponse:
    try:
        body = await _bounded_json_object(request)
        memorial = _load_memorial(slug)
        archive_registry = _public_memorial_archive_registry(slug)
        packet = build_memorial_share_packet(
            slug=slug,
            public_origin=body.get("public_origin"),
            memorial=memorial,
            archive_registry=archive_registry,
            channels=_list_value(body, "channels"),
            include_archive=body.get("include_archive") is True,
            include_audio=body.get("include_audio") is True,
            archive_ids=_list_value(body, "archive_ids"),
            audio_relpaths=_list_value(body, "audio_relpaths"),
        )
        return JSONResponse(packet, headers=_RESPONSE_HEADERS)
    except MemorialSharePacketError as exc:
        return _error(exc.code)
    except HTTPException as exc:
        return _error(str(exc.detail), status_code=exc.status_code)
