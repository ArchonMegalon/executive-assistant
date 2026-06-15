from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.api.routes import public_memorial_conversation_support as support

router = APIRouter(tags=["public-memorial-conversation"])


@router.get("/memorials/{slug}/chat")
async def public_memorial_chat_help(slug: str) -> JSONResponse:
    return await support.public_memorial_chat_help(slug=slug)


@router.get("/memorials/{slug}/personal-memory")
async def public_memorial_personal_memory_status(slug: str, request: Request) -> JSONResponse:
    return await support.public_memorial_personal_memory_status(slug=slug, request=request)


@router.delete("/memorials/{slug}/personal-memory")
async def public_memorial_personal_memory_forget(slug: str, request: Request) -> JSONResponse:
    return await support.public_memorial_personal_memory_forget(slug=slug, request=request)


@router.post("/memorials/{slug}/chat")
async def public_memorial_chat(slug: str, request: Request) -> JSONResponse:
    return await support.public_memorial_chat(slug=slug, request=request)


@router.post("/memorials/{slug}/speech-transcribe")
async def public_memorial_speech_transcribe(slug: str, request: Request) -> JSONResponse:
    return await support.public_memorial_speech_transcribe(slug=slug, request=request)


@router.get("/memorials/{slug}/speech-synthesize")
async def public_memorial_speech_synthesize_help(slug: str) -> JSONResponse:
    return await support.public_memorial_speech_synthesize_help(slug=slug)


@router.post("/memorials/{slug}/speech-synthesize")
async def public_memorial_speech_synthesize(slug: str, request: Request) -> Response:
    return await support.public_memorial_speech_synthesize(slug=slug, request=request)


@router.post("/memorials/{slug}/conversation-turn")
async def public_memorial_conversation_turn(slug: str, request: Request) -> JSONResponse:
    return await support.public_memorial_conversation_turn(slug=slug, request=request)
