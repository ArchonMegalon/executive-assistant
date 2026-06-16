from __future__ import annotations

import base64
import concurrent.futures
import time
from typing import Any

from fastapi import HTTPException

from app.domain.memorial.turns import MemorialSpeechTranscription, MemorialTurnRequest, MemorialTurnResult
from app.services.memorial_stt_error_log import classify_memorial_stt_issue, log_memorial_stt_issue


def transcribe_public_memorial_audio(*, shared, payload: bytes, content_type: str) -> MemorialSpeechTranscription:
    result = dict(shared._memorial_transcribe_audio_blob(payload=payload, content_type=content_type))
    transcript_text = shared._text(result.get("transcript_text"))
    effective_question = shared._canonical_memorial_contact_opening_question(transcript_text)
    visible_transcript = shared._memorial_visible_transcript_text(
        transcript_text=transcript_text,
        effective_question=effective_question,
    )
    if transcript_text:
        result["transcript_text"] = effective_question
        result["transcript_effective_text"] = effective_question
        result["transcript_original_text"] = visible_transcript
    return MemorialSpeechTranscription(
        transcript_text=shared._text(result.get("transcript_text")),
        transcript_effective_text=shared._text(result.get("transcript_effective_text")),
        transcript_original_text=shared._text(result.get("transcript_original_text")),
        transcription_status=shared._text(result.get("transcription_status")),
        transcriber=shared._text(result.get("transcriber")),
        extra=result,
    )


def build_public_memorial_turn(*, shared, request: MemorialTurnRequest, memory_runtime=None) -> MemorialTurnResult:
    total_started = time.perf_counter()
    payload = shared._load_memorial(request.slug)
    private_profile = shared._load_private_profile(request.slug)
    transcription = transcribe_public_memorial_audio(
        shared=shared,
        payload=request.audio_payload,
        content_type=request.content_type,
    )
    transcript_text = transcription.transcript_effective_text
    if not transcript_text:
        raise HTTPException(status_code=400, detail="speech_transcription_empty")
    selected_model = shared._resolve_memorial_voice_chat_model(payload, private_profile, transcript_text)
    llm_started = time.perf_counter()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"memorial-turn-{request.slug}")
    future = executor.submit(
        shared._memorial_chat_answer,
        payload,
        transcript_text,
        private_profile,
        selected_model,
        slug=request.slug,
        memory_runtime=memory_runtime,
        personal_memory_context=request.personal_memory_context,
        difficult_memory_mode=request.difficult_memory_mode,
    )
    try:
        answer_payload = future.result(timeout=shared._MEMORIAL_CONVERSATION_TURN_LLM_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        future.cancel()
        answer_payload = shared._memorial_chat_fallback_answer(
            payload,
            transcript_text,
            private_profile,
            slug=request.slug,
            memory_runtime=memory_runtime,
            personal_memory_context=request.personal_memory_context,
            llm_model=selected_model,
            fallback_reason="conversation_turn_llm_timeout",
            difficult_memory_mode=request.difficult_memory_mode,
        )
        answer_payload["llm_model"] = selected_model
        answer_payload["llm_provider"] = "memorial_guardrail"
        answer_payload["llm_request_model"] = selected_model
        answer_payload["llm_fallback_used"] = True
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    llm_ms = (time.perf_counter() - llm_started) * 1000.0
    base_config = shared._load_voice_config(request.slug)
    merged_config = dict(base_config)
    merged_config["lang"] = shared._memorial_fixed_conversation_language()
    if request.voice_ab_variant in {"a", "b"}:
        merged_config.update(
            shared._voice_ab_variant_choice(
                slug=request.slug,
                variant_id=request.voice_ab_variant,
                context=request.personal_memory_context,
            )
        )
    merged_config = shared._apply_memorial_spoken_tts_clarity_policy(merged_config)
    tts_options = shared._tts_plugin_options(
        payload=merged_config,
        voice_profile_ready=bool(base_config.get("voice_profile_ready")),
    )
    selected_plugin, selected_option = shared._resolve_server_tts_plugin(payload=merged_config, options=tts_options)
    visible_answer = shared._compact_memorial_realtime_answer(answer_payload.get("answer"))
    answer_payload["answer"] = visible_answer
    answer_audio_text = shared._normalize_tts_text(answer_payload.get("answer_audio_text") or visible_answer)
    if not answer_audio_text:
        raise HTTPException(status_code=502, detail="memorial_answer_missing")
    if not bool(selected_option.get("tts_plugin_enabled")):
        raise HTTPException(status_code=409, detail="tts_plugin_not_ready")
    direct_contact_opening = shared._text(answer_payload.get("fallback_reason")) == "direct_contact_opening"
    if direct_contact_opening:
        lead_in_ms = shared._MEMORIAL_CONTACT_TTS_LEAD_IN_MS
        tail_silence_ms = shared._MEMORIAL_CONTACT_TTS_TAIL_SILENCE_MS
    else:
        lead_in_ms = (
            shared._MEMORIAL_FAST_TTS_LEAD_IN_MS
            if selected_plugin == shared.PIPER_FAST_TTS_PLUGIN_ID
            else shared._MEMORIAL_TTS_LEAD_IN_MS
        )
        tail_silence_ms = shared._MEMORIAL_TTS_TAIL_SILENCE_MS
    tts_started = time.perf_counter()
    audio, audio_content_type = shared._render_memorial_tts_audio(
        slug=request.slug,
        text=answer_audio_text,
        merged_config=merged_config,
        base_config=base_config,
        selected_plugin=selected_plugin,
        selected_option=selected_option,
        lead_in_ms=0,
        tail_silence_ms=0,
    )
    tts_ms = (time.perf_counter() - tts_started) * 1000.0
    pad_started = time.perf_counter()
    audio, audio_content_type = shared._pad_speech_audio_lead_in(
        payload=audio,
        content_type=audio_content_type,
        silence_ms=lead_in_ms,
        tail_silence_ms=tail_silence_ms,
        extra_filters="",
    )
    pad_ms = (time.perf_counter() - pad_started) * 1000.0
    response_payload = dict(answer_payload)
    response_payload["transcript_text"] = transcription.transcript_text
    response_payload["transcript_effective_text"] = transcription.transcript_effective_text
    response_payload["transcript_original_text"] = transcription.transcript_original_text
    response_payload["audio_content_type"] = audio_content_type
    response_payload["audio_base64"] = base64.b64encode(audio).decode("ascii")
    actual_fast_path = bool(request.prefer_fast_tts and selected_plugin == shared.PIPER_FAST_TTS_PLUGIN_ID)
    response_payload["tts_plugin"] = selected_plugin
    response_payload["tts_fast_path"] = actual_fast_path
    issue_reason = classify_memorial_stt_issue(
        transcription_status=transcription.transcription_status,
        transcript_text=transcription.transcript_original_text or transcription.transcript_text,
        answer_text=shared._text(response_payload.get("answer")),
        fallback_reason=shared._text(response_payload.get("fallback_reason")),
    )
    if issue_reason:
        try:
            log_memorial_stt_issue(
                slug=request.slug,
                route="conversation_turn",
                reason=issue_reason,
                audio_payload=request.audio_payload,
                content_type=request.content_type,
                transcription_payload=transcription.as_public_payload(),
                answer_payload=response_payload,
                extra={
                    "voice_ab_variant": request.voice_ab_variant,
                    "tts_plugin": selected_plugin,
                    "tts_fast_path": actual_fast_path,
                },
            )
        except Exception:
            pass
    shared._register_memorial_known_audio_transcript(
        payload=audio,
        transcript_text=answer_audio_text,
        transcriber="memorial_tts_provenance_cache",
        primary_transcript_text=visible_answer,
    )
    shared._remember_personal_conversation_turn(
        slug=request.slug,
        context=request.personal_memory_context or {},
        question=transcript_text,
        answer=shared._text(answer_payload.get("answer"), ""),
    )
    shared._log_memorial_timing(
        "conversation_turn",
        slug=request.slug,
        content_type=request.content_type,
        transcript_chars=len(transcription.transcript_original_text),
        answer_chars=len(answer_audio_text),
        requested_model=selected_model,
        effective_model=shared._text(answer_payload.get("llm_model")),
        fallback_used=bool(answer_payload.get("llm_fallback_used")),
        tts_plugin=selected_plugin,
        tts_fast_path=actual_fast_path,
        stt_ms=0.0,
        llm_ms=llm_ms,
        tts_ms=tts_ms,
        pad_ms=pad_ms,
        total_ms=(time.perf_counter() - total_started) * 1000.0,
    )
    return MemorialTurnResult(response_payload=response_payload)
