from __future__ import annotations

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse, Response

from app.api.routes import public_memorials as shared

router = APIRouter(tags=["public-memorial-runtime"])


@router.post("/memorials/{slug}/voice-preview/session")
async def public_memorial_voice_preview_session(
    slug: str,
    request: Request,
) -> JSONResponse:
    return await shared.public_memorial_voice_preview_session(
        slug=slug,
        request=request,
    )


@router.delete("/memorials/{slug}/voice-preview/session")
async def public_memorial_voice_preview_session_delete(
    slug: str,
    request: Request,
) -> JSONResponse:
    return await shared.public_memorial_voice_preview_session_delete(
        slug=slug,
        request=request,
    )


@router.post("/memorials/{slug}/warmup")
async def public_memorial_warmup(slug: str, request: Request) -> JSONResponse:
    return await shared.public_memorial_warmup(slug=slug, request=request)


@router.get("/memorials/{slug}/warmup-status")
def public_memorial_warmup_status(slug: str, request: Request) -> JSONResponse:
    return shared.public_memorial_warmup_status(slug=slug, request=request)


@router.get("/memorials/{slug}/readiness")
def public_memorial_readiness(slug: str, request: Request) -> JSONResponse:
    return shared.public_memorial_readiness(slug=slug, request=request)


@router.get("/memorials/{slug}/video-meeting/status")
def public_memorial_video_meeting_status(slug: str) -> JSONResponse:
    return shared.public_memorial_video_meeting_status(slug=slug)


@router.post("/memorials/{slug}/video-meeting/session")
async def public_memorial_video_meeting_session(slug: str, request: Request) -> JSONResponse:
    return await shared.public_memorial_video_meeting_session(slug=slug, request=request)


@router.post("/memorials/{slug}/video-meeting/provider-callback")
async def public_memorial_video_meeting_provider_callback(slug: str, request: Request) -> JSONResponse:
    return await shared.public_memorial_video_meeting_provider_callback(slug=slug, request=request)


@router.post("/memorials/{slug}/playback-telemetry")
async def public_memorial_playback_telemetry(slug: str, request: Request) -> JSONResponse:
    return await shared.public_memorial_playback_telemetry(slug=slug, request=request)


@router.post("/memorials/{slug}/realtime/webrtc")
async def public_memorial_realtime_webrtc(slug: str, request: Request) -> Response:
    return await shared.public_memorial_realtime_webrtc(slug=slug, request=request)


@router.websocket("/memorials/{slug}/realtime")
async def public_memorial_realtime(slug: str, websocket: WebSocket) -> None:
    await shared.public_memorial_realtime(slug=slug, websocket=websocket)
