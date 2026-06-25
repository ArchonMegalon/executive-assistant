from __future__ import annotations

import base64
import concurrent.futures
import time
from typing import Any

from fastapi import HTTPException

from app.domain.memorial.turns import MemorialAnswerPlan, MemorialRenderedAudio, MemorialSpeechTranscription, MemorialTurnRequest, MemorialTurnResult
from app.services.memorial_stt_error_log import classify_memorial_stt_issue, log_memorial_stt_issue
from app.services.memorial_turn_runtime import MemorialTurnRuntime


def transcribe_public_memorial_audio(*, runtime: MemorialTurnRuntime, payload: bytes, content_type: str) -> MemorialSpeechTranscription:
    stt_started = time.perf_counter()
    result = dict(runtime.transcribe_audio_blob(payload=payload, content_type=content_type))
    stt_ms = (time.perf_counter() - stt_started) * 1000.0
    transcript_text = runtime.text(result.get("transcript_text"), "")
    effective_question = runtime.canonical_contact_opening_question(transcript_text)
    visible_transcript = runtime.visible_transcript_text(
        transcript_text=transcript_text,
        effective_question=effective_question,
    )
    if transcript_text:
        result["transcript_text"] = effective_question
        result["transcript_effective_text"] = effective_question
        result["transcript_original_text"] = visible_transcript
    return MemorialSpeechTranscription(
        transcript_text=runtime.text(result.get("transcript_text"), ""),
        transcript_effective_text=runtime.text(result.get("transcript_effective_text"), ""),
        transcript_original_text=runtime.text(result.get("transcript_original_text"), ""),
        transcription_status=runtime.text(result.get("transcription_status"), ""),
        transcriber=runtime.text(result.get("transcriber"), ""),
        stt_ms=stt_ms,
        extra=result,
    )


def build_public_memorial_turn(*, runtime: MemorialTurnRuntime, request: MemorialTurnRequest, memory_runtime=None) -> MemorialTurnResult:
    total_started = time.perf_counter()
    payload = runtime.load_memorial(request.slug)
    private_profile = runtime.load_private_profile(request.slug)
    transcription = transcribe_public_memorial_audio(
        runtime=runtime,
        payload=request.audio_payload,
        content_type=request.content_type,
    )
    transcript_text = transcription.transcript_effective_text
    if not transcript_text:
        detail = runtime.text(
            transcription.extra.get("detail") or transcription.transcription_status or "speech_transcription_empty",
            "speech_transcription_empty",
        )
        raise HTTPException(status_code=400, detail=f"speech_transcription_empty:{detail}")
    answer_plan = _build_answer_plan(
        runtime=runtime,
        payload=payload,
        private_profile=private_profile,
        transcript_text=transcript_text,
        request=request,
        memory_runtime=memory_runtime,
    )
    rendered_audio = _render_turn_audio(
        runtime=runtime,
        slug=request.slug,
        payload=payload,
        request=request,
        answer_plan=answer_plan,
    )
    if not bytes(rendered_audio.payload or b""):
        raise HTTPException(status_code=502, detail="tts_audio_missing")
    if not runtime.text(rendered_audio.content_type, "").strip().lower().startswith("audio/"):
        raise HTTPException(status_code=502, detail="tts_content_type_invalid")
    response_payload = dict(answer_plan.answer_payload)
    response_payload["transcript_text"] = transcription.transcript_text
    response_payload["transcript_effective_text"] = transcription.transcript_effective_text
    response_payload["transcript_original_text"] = transcription.transcript_original_text
    response_payload["audio_content_type"] = rendered_audio.content_type
    response_payload["audio_base64"] = base64.b64encode(rendered_audio.payload).decode("ascii")
    response_payload["audio_unavailable"] = False
    response_payload["voice_delivery_status"] = "spoken_audio_ready"
    response_payload["spoken_turn"] = True
    response_payload["tts_plugin"] = rendered_audio.tts_plugin
    response_payload["tts_fast_path"] = rendered_audio.tts_fast_path
    _log_turn_issue_if_needed(
        runtime=runtime,
        request=request,
        transcription=transcription,
        response_payload=response_payload,
        rendered_audio=rendered_audio,
    )
    runtime.register_memorial_known_audio_transcript(
        payload=rendered_audio.payload,
        transcript_text=rendered_audio.answer_audio_text,
        transcriber="memorial_tts_provenance_cache",
        primary_transcript_text=runtime.text(response_payload.get("answer"), ""),
    )
    runtime.remember_personal_conversation_turn(
        slug=request.slug,
        context=request.personal_memory_context or {},
        question=transcript_text,
        answer=runtime.text(response_payload.get("answer"), ""),
    )
    runtime.log_memorial_timing(
        "conversation_turn",
        slug=request.slug,
        content_type=request.content_type,
        transcript_chars=len(transcription.transcript_original_text),
        answer_chars=len(rendered_audio.answer_audio_text),
        requested_model=answer_plan.selected_model,
        effective_model=runtime.text(response_payload.get("llm_model"), ""),
        fallback_used=bool(response_payload.get("llm_fallback_used")),
        tts_plugin=rendered_audio.tts_plugin,
        tts_fast_path=rendered_audio.tts_fast_path,
        stt_ms=transcription.stt_ms,
        llm_ms=answer_plan.llm_ms,
        tts_ms=rendered_audio.tts_ms,
        pad_ms=rendered_audio.pad_ms,
        total_ms=(time.perf_counter() - total_started) * 1000.0,
    )
    return MemorialTurnResult(response_payload=response_payload)


def _build_answer_plan(
    *,
    runtime: MemorialTurnRuntime,
    payload: dict[str, Any],
    private_profile: dict[str, Any],
    transcript_text: str,
    request: MemorialTurnRequest,
    memory_runtime=None,
) -> MemorialAnswerPlan:
    selected_model = runtime.resolve_voice_chat_model(payload, private_profile, transcript_text)
    llm_started = time.perf_counter()
    if runtime.is_contact_question(transcript_text):
        answer_payload = {
            "person_name": runtime.text(payload.get("person_name"), request.slug),
            "mode": "memorial_first_person_memory_chat",
            "question": transcript_text,
            "answer": runtime.memorial_contact_answer_body(transcript_text),
            "answer_audio_text": runtime.memorial_contact_answer_body(transcript_text),
            "sources": [],
            "private_context_used": bool(runtime.list_of_dicts(private_profile.get("family_context_notes"))),
            "personal_memory_used": False,
            "difficult_memory_mode": bool(request.difficult_memory_mode),
            "safety_note": "Erinnerungsmodus in Ich-Form: keine Behauptung, dass die verstorbene Person real antwortet; keine synthetische Stimmnachbildung der verstorbenen Person.",
            "llm_model": "memorial_guardrail",
            "llm_provider": "memorial_guardrail",
            "llm_request_model": selected_model,
            "llm_fallback_used": False,
            "fallback_reason": "direct_contact_opening",
        }
    else:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"memorial-turn-{request.slug}")
        future = executor.submit(
            runtime.memorial_chat_answer,
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
            answer_payload = future.result(timeout=runtime.memorial_conversation_turn_llm_timeout_seconds)
        except concurrent.futures.TimeoutError:
            future.cancel()
            answer_payload = runtime.memorial_chat_fallback_answer(
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
    return MemorialAnswerPlan(
        answer_payload=answer_payload,
        selected_model=selected_model,
        llm_ms=(time.perf_counter() - llm_started) * 1000.0,
        direct_contact_opening=runtime.text(answer_payload.get("fallback_reason"), "") == "direct_contact_opening",
    )


def _render_turn_audio(
    *,
    runtime: MemorialTurnRuntime,
    slug: str,
    payload: dict[str, Any],
    request: MemorialTurnRequest,
    answer_plan: MemorialAnswerPlan,
) -> MemorialRenderedAudio:
    base_config = runtime.load_voice_config(slug)
    merged_config = dict(base_config)
    merged_config["lang"] = runtime.memorial_fixed_conversation_language()
    if request.voice_ab_variant in {"a", "b"}:
        merged_config.update(runtime.voice_ab_variant_choice(slug=slug, variant_id=request.voice_ab_variant, context=request.personal_memory_context))
    merged_config = runtime.apply_memorial_spoken_tts_clarity_policy(merged_config)
    tts_options = runtime.tts_plugin_options(
        payload=merged_config,
        voice_profile_ready=bool(base_config.get("voice_profile_ready")),
    )
    selected_plugin, selected_option = runtime.resolve_server_tts_plugin(payload=merged_config, options=tts_options)
    visible_answer = runtime.compact_memorial_realtime_answer(answer_plan.answer_payload.get("answer"))
    answer_plan.answer_payload["answer"] = visible_answer
    answer_audio_text = runtime.normalize_tts_text(answer_plan.answer_payload.get("answer_audio_text") or visible_answer)
    if not answer_audio_text:
        raise HTTPException(status_code=502, detail="memorial_answer_missing")
    if not bool(selected_option.get("tts_plugin_enabled")):
        raise HTTPException(status_code=409, detail="tts_plugin_not_ready")
    if answer_plan.direct_contact_opening:
        lead_in_ms = runtime.memorial_contact_tts_lead_in_ms
        tail_silence_ms = runtime.memorial_contact_tts_tail_silence_ms
    else:
        lead_in_ms = (
            runtime.memorial_fast_tts_lead_in_ms
            if selected_plugin == runtime.piper_fast_tts_plugin_id
            else runtime.memorial_tts_lead_in_ms
        )
        tail_silence_ms = runtime.memorial_tts_tail_silence_ms
    tts_started = time.perf_counter()
    audio, audio_content_type = runtime.render_memorial_tts_audio(
        slug=slug,
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
    audio, audio_content_type = runtime.pad_speech_audio_lead_in(
        payload=audio,
        content_type=audio_content_type,
        silence_ms=lead_in_ms,
        tail_silence_ms=tail_silence_ms,
        extra_filters="",
    )
    return MemorialRenderedAudio(
        payload=audio,
        content_type=audio_content_type,
        answer_audio_text=answer_audio_text,
        tts_plugin=selected_plugin,
        tts_fast_path=bool(request.prefer_fast_tts and selected_plugin == runtime.piper_fast_tts_plugin_id),
        tts_ms=tts_ms,
        pad_ms=(time.perf_counter() - pad_started) * 1000.0,
    )


def _log_turn_issue_if_needed(
    *,
    runtime: MemorialTurnRuntime,
    request: MemorialTurnRequest,
    transcription: MemorialSpeechTranscription,
    response_payload: dict[str, Any],
    rendered_audio: MemorialRenderedAudio,
) -> None:
    issue_reason = classify_memorial_stt_issue(
        transcription_status=transcription.transcription_status,
        transcript_text=transcription.transcript_original_text or transcription.transcript_text,
        answer_text=runtime.text(response_payload.get("answer"), ""),
        fallback_reason=runtime.text(response_payload.get("fallback_reason"), ""),
    )
    if not issue_reason:
        return
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
                "tts_plugin": rendered_audio.tts_plugin,
                "tts_fast_path": rendered_audio.tts_fast_path,
            },
        )
    except Exception:
        pass
