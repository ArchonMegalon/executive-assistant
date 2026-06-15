from __future__ import annotations

import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.api.routes import public_memorials as shared


async def public_memorial_chat_help(slug: str) -> JSONResponse:
    shared._load_memorial(slug)
    return JSONResponse(
        {
            "detail": "Use POST with JSON to chat with this memorial.",
            "method": "POST",
            "content_type": "application/json",
            "endpoint": f"/memorials/{slug}/chat",
            "example_body": {"question": "Wie hätte er Susanna schriftlich geschrieben?"},
            "page": f"/memorials/{slug}",
        }
    )


async def public_memorial_personal_memory_status(slug: str, request: Request) -> JSONResponse:
    shared._load_memorial(slug)
    context = shared._extract_personal_memory_request_context(request=request)
    return JSONResponse(shared._personal_memory_public_status(slug=slug, context=context))


async def public_memorial_personal_memory_forget(slug: str, request: Request) -> JSONResponse:
    shared._load_memorial(slug)
    context = shared._extract_personal_memory_request_context(request=request)
    scope = shared._text(context.get("scope"), "")
    if scope:
        store = shared._load_personal_memory_store(slug=slug, scope=scope)
        store["items"] = []
        store["frozen"] = False
        store["approved_voice_choice"] = ""
        shared._save_personal_memory_store(slug=slug, scope=scope, payload=store)
    return JSONResponse({"status": "forgotten", **shared._personal_memory_public_status(slug=slug, context=context)})


async def public_memorial_chat(slug: str, request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid_json")
    payload = shared._load_memorial(slug)
    private_profile = shared._load_private_profile(slug)
    selected_model, _, _ = shared._resolve_memorial_chat_model(payload, private_profile, shared._text(body.get("llm_model")))
    container = getattr(request.app.state, "container", None)
    memory_runtime = getattr(container, "memory_runtime", None)
    question_text = shared._text(body.get("question"))
    personal_memory_context = shared._extract_personal_memory_request_context(request=request, body=body)
    difficult_memory_mode = shared._extract_difficult_memory_mode(request=request, body=body)
    shared._enforce_public_memorial_rate_limit("chat", request=request, context=personal_memory_context)
    if not difficult_memory_mode and shared._is_difficult_memory_question(question_text):
        answer = shared._memorial_chat_fallback_answer(
            payload,
            question_text,
            private_profile,
            slug=slug,
            memory_runtime=memory_runtime,
            llm_model=selected_model,
            fallback_reason="difficult_memory_guardrail",
            difficult_memory_mode=False,
        )
        answer["llm_model"] = selected_model
        answer["llm_provider"] = "memorial_guardrail"
        answer["llm_request_model"] = selected_model
        answer["llm_fallback_used"] = True
    elif shared._is_memorial_transcript_relationship_question(question_text) or shared._is_memorial_mail_practice_question(question_text):
        answer = shared._memorial_chat_fallback_answer(
            payload,
            question_text,
            private_profile,
            slug=slug,
            memory_runtime=memory_runtime,
            llm_model=selected_model,
            fallback_reason="mail_practice_guardrail" if shared._is_memorial_mail_practice_question(question_text) else "transcript_relationship_guardrail",
            difficult_memory_mode=difficult_memory_mode,
        )
    else:
        answer = shared._memorial_chat_answer(
            payload,
            question_text,
            private_profile,
            requested_model=selected_model,
            slug=slug,
            memory_runtime=memory_runtime,
            personal_memory_context=personal_memory_context,
            difficult_memory_mode=difficult_memory_mode,
        )
    shared._remember_personal_conversation_turn(
        slug=slug,
        context=personal_memory_context,
        question=question_text,
        answer=shared._text(answer.get("answer"), ""),
    )
    if shared._is_memorial_ooda_question(question_text) and not answer.get("ooda"):
        answer["ooda"] = shared._memorial_ooda_struct(question_text)
    answer["personal_memory"] = shared._personal_memory_public_status(slug=slug, context=personal_memory_context)
    return JSONResponse(answer)


async def public_memorial_speech_transcribe(slug: str, request: Request) -> JSONResponse:
    shared._load_memorial(slug)
    shared._enforce_public_memorial_rate_limit("speech_transcribe", request=request)
    content_length = shared._content_length_or_zero(request)
    if content_length > shared._MAX_SPEECH_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="audio_too_large")
    payload = await request.body()
    content_type = str(request.headers.get("content-type") or "application/octet-stream")
    result = dict(shared._memorial_transcribe_audio_blob(payload=payload, content_type=content_type))
    transcript_text = shared._text(result.get("transcript_text"))
    effective_question = shared._canonical_memorial_contact_opening_question(transcript_text)
    visible_transcript = shared._memorial_visible_transcript_text(transcript_text=transcript_text, effective_question=effective_question)
    if transcript_text:
        result["transcript_text"] = effective_question
        result["transcript_effective_text"] = effective_question
        result["transcript_original_text"] = visible_transcript
    shared._log_memorial_timing(
        "speech_transcribe",
        slug=slug,
        content_type=content_type,
        audio_bytes=len(payload),
        transcript_chars=len(visible_transcript if transcript_text else shared._text(result.get("transcript_text"))),
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
    tts_options = shared._tts_plugin_options(payload=merged_config, voice_profile_ready=bool(base_config.get("voice_profile_ready")))
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
        lead_in_ms=shared._MEMORIAL_CONTACT_TTS_LEAD_IN_MS if direct_contact_opening else (shared._MEMORIAL_FAST_TTS_LEAD_IN_MS if selected_plugin == shared.PIPER_FAST_TTS_PLUGIN_ID else shared._MEMORIAL_TTS_LEAD_IN_MS),
        tail_silence_ms=shared._MEMORIAL_CONTACT_TTS_TAIL_SILENCE_MS if direct_contact_opening else shared._MEMORIAL_TTS_TAIL_SILENCE_MS,
        force_regenerate=force_regenerate,
    )
    shared._register_memorial_known_audio_transcript(payload=audio, transcript_text=text, transcriber="memorial_tts_provenance_cache")
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
        response_payload = shared._build_memorial_conversation_turn_payload(
            slug=slug,
            audio_payload=audio_payload,
            content_type=content_type,
            prefer_fast_tts=prefer_fast_tts,
            memory_runtime=memory_runtime,
            personal_memory_context=personal_memory_context,
            voice_ab_variant=voice_ab_variant,
            difficult_memory_mode=difficult_memory_mode,
        )
        response_payload["personal_memory"] = shared._personal_memory_public_status(slug=slug, context=personal_memory_context)
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
