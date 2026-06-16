from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.api.routes import public_memorials as shared
from app.domain.memorial.turns import MemorialTurnRequest
from app.services.memorial_turn_service import build_public_memorial_turn, transcribe_public_memorial_audio


async def public_memorial_speech_transcribe(slug: str, request: Request) -> JSONResponse:
    shared._load_memorial(slug)
    shared._enforce_public_memorial_rate_limit("speech_transcribe", request=request)
    content_length = shared._content_length_or_zero(request)
    if content_length > shared._MAX_SPEECH_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="audio_too_large")
    payload = await request.body()
    content_type = str(request.headers.get("content-type") or "application/octet-stream")
    result = transcribe_public_memorial_audio(shared=shared, payload=payload, content_type=content_type).as_public_payload()
    transcript_text = shared._text(result.get("transcript_original_text") or result.get("transcript_text"))
    shared._log_memorial_timing(
        "speech_transcribe",
        slug=slug,
        content_type=content_type,
        audio_bytes=len(payload),
        transcript_chars=len(transcript_text if transcript_text else shared._text(result.get("transcript_text"))),
        status=shared._text(result.get("transcription_status")),
        transcriber=shared._text(result.get("transcriber")),
    )
    return JSONResponse(result)


async def public_memorial_speech_synthesize_help(slug: str) -> JSONResponse:
    shared._load_memorial(slug)
    return JSONResponse(
        {
            "detail": "Use POST with JSON to synthesize memorial speech.",
            "method": "POST",
            "content_type": "application/json",
            "endpoint": f"/memorials/{slug}/speech-synthesize",
            "example_body": {"text": "Rechtlich ist es so, dass man die Dinge sauber unterscheiden muss."},
            "page": f"/memorials/{slug}",
        }
    )


async def public_memorial_speech_synthesize(slug: str, request: Request) -> Response:
    memorial = shared._load_memorial(slug)
    shared._require_voice_consent(shared._payload_with_slug(slug, memorial), "synthesize")
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid_json")
    unexpected_fields = set(body.keys()) - shared._PUBLIC_TTS_ALLOWED_BODY_FIELDS
    if unexpected_fields:
        return shared._public_memorial_error_response(400, "unsupported_public_tts_fields")
    base_config = shared._load_voice_config(slug)
    merged_config = dict(base_config)
    merged_config["lang"] = shared._memorial_fixed_conversation_language()
    personal_memory_context = shared._extract_personal_memory_request_context(request=request, body=body)
    shared._enforce_public_memorial_rate_limit("speech_synthesize", request=request, context=personal_memory_context)
    voice_ab_variant = shared._voice_ab_variant_from_request(request=request, body=body)
    if voice_ab_variant in {"a", "b"}:
        merged_config.update(shared._voice_ab_variant_choice(slug=slug, variant_id=voice_ab_variant, context=personal_memory_context))
    merged_config = shared._apply_memorial_spoken_tts_clarity_policy(merged_config)
    tts_options = shared._tts_plugin_options(
        payload=merged_config,
        voice_profile_ready=bool(base_config.get("voice_profile_ready")),
    )
    selected_plugin, selected_option = shared._resolve_server_tts_plugin(payload=merged_config, options=tts_options)
    if not bool(selected_option.get("tts_plugin_enabled")):
        raise HTTPException(status_code=409, detail="tts_plugin_not_ready")
    text = shared._normalize_tts_text(body.get("text"))
    if not text:
        raise HTTPException(status_code=400, detail="tts_text_missing")
    force_regenerate = bool(body.get("force_regenerate_audio"))
    direct_contact_opening = shared._is_memorial_direct_contact_opening_text(text)
    audio, content_type = shared._render_memorial_tts_audio(
        slug=slug,
        text=text,
        merged_config=merged_config,
        base_config=base_config,
        selected_plugin=selected_plugin,
        selected_option=selected_option,
        lead_in_ms=(
            shared._MEMORIAL_CONTACT_TTS_LEAD_IN_MS
            if direct_contact_opening
            else (
                shared._MEMORIAL_FAST_TTS_LEAD_IN_MS
                if selected_plugin == shared.PIPER_FAST_TTS_PLUGIN_ID
                else shared._MEMORIAL_TTS_LEAD_IN_MS
            )
        ),
        tail_silence_ms=(
            shared._MEMORIAL_CONTACT_TTS_TAIL_SILENCE_MS
            if direct_contact_opening
            else shared._MEMORIAL_TTS_TAIL_SILENCE_MS
        ),
        force_regenerate=force_regenerate,
    )
    shared._register_memorial_known_audio_transcript(
        payload=audio,
        transcript_text=text,
        transcriber="memorial_tts_provenance_cache",
    )
    return Response(content=audio, media_type=content_type, headers={"Cache-Control": "no-store"})


async def public_memorial_conversation_turn(slug: str, request: Request) -> JSONResponse:
    total_started = time.perf_counter()
    memorial = shared._load_memorial(slug)
    shared._require_voice_consent(shared._payload_with_slug(slug, memorial), "conversation_turn")
    content_length = shared._content_length_or_zero(request)
    if content_length > shared._MAX_SPEECH_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="audio_too_large")
    audio_payload = await request.body()
    content_type = str(request.headers.get("content-type") or "application/octet-stream")
    container = getattr(request.app.state, "container", None)
    memory_runtime = getattr(container, "memory_runtime", None)
    personal_memory_context = shared._extract_personal_memory_request_context(request=request)
    difficult_memory_mode = shared._extract_difficult_memory_mode(request=request)
    try:
        shared._enforce_public_memorial_rate_limit("conversation_turn", request=request, context=personal_memory_context)
        voice_ab_variant = shared._voice_ab_variant_from_request(request=request)
        prefer_fast_tts, _ = shared._prefer_fast_tts_for_conversation_turn(slug)
        response_payload = build_public_memorial_turn(
            shared=shared,
            request=MemorialTurnRequest(
                slug=slug,
                audio_payload=audio_payload,
                content_type=content_type,
                prefer_fast_tts=prefer_fast_tts,
                personal_memory_context=personal_memory_context,
                voice_ab_variant=voice_ab_variant,
                difficult_memory_mode=difficult_memory_mode,
            ),
            memory_runtime=memory_runtime,
        ).as_public_payload()
        response_payload["personal_memory"] = shared._personal_memory_public_status(
            slug=slug,
            context=personal_memory_context,
        )
        return JSONResponse(response_payload, headers={"Cache-Control": "no-store"})
    except HTTPException as exc:
        if shared._memorial_should_rescue_failed_voice_turn(exc.detail):
            response_payload = shared._build_memorial_rescue_contact_turn_payload(
                slug=slug,
                personal_memory_context=personal_memory_context,
                difficult_memory_mode=difficult_memory_mode,
                rescue_reason=shared._text(exc.detail, "conversation_turn_rescue"),
            )
            shared._log_memorial_timing(
                "conversation_turn_rescue",
                slug=slug,
                content_type=content_type,
                audio_bytes=len(audio_payload),
                detail=shared._text(exc.detail, "conversation_turn_rescue"),
                total_ms=(time.perf_counter() - total_started) * 1000.0,
                tts_plugin=shared._text(response_payload.get("tts_plugin")),
            )
            return JSONResponse(response_payload, headers={"Cache-Control": "no-store"})
        shared._log_memorial_timing(
            "conversation_turn_error",
            slug=slug,
            content_type=content_type,
            audio_bytes=len(audio_payload),
            detail=shared._text(exc.detail, "conversation_turn_failed"),
            total_ms=(time.perf_counter() - total_started) * 1000.0,
        )
        raise


async def stream_realtime_audio_chunks(
    *,
    turn_id: str,
    audio: bytes,
    audio_content_type: str,
    chunk_size: int,
    cancelled_turn_ids: set[str],
    send_json: Callable[[dict[str, object]], Awaitable[bool]],
    send_cancelled: Callable[[str], Awaitable[None]],
) -> bool:
    audio_base64 = base64.b64encode(audio).decode("ascii")
    if not audio_base64:
        return True
    total_parts = max(1, (len(audio_base64) + chunk_size - 1) // chunk_size)
    for index in range(total_parts):
        if turn_id in cancelled_turn_ids:
            await send_cancelled(turn_id)
            return False
        start = index * chunk_size
        end = start + chunk_size
        if not await send_json(
            {
                "type": "audio_chunk",
                "turn_id": turn_id,
                "content_type": audio_content_type,
                "part": index + 1,
                "total_parts": total_parts,
                "audio_base64": audio_base64[start:end],
            }
        ):
            return False
        await asyncio.sleep(shared._MEMORIAL_REALTIME_STREAM_YIELD_SECONDS)
    if turn_id in cancelled_turn_ids:
        await send_cancelled(turn_id)
        return False
    return await send_json(
        {
            "type": "audio_complete",
            "turn_id": turn_id,
            "content_type": audio_content_type,
            "total_parts": total_parts,
        }
    )
