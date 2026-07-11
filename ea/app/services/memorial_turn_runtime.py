from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class MemorialTurnRuntime:
    text: Callable[[object, str], str]
    transcribe_audio_blob: Callable[..., dict[str, object]]
    canonical_contact_opening_question: Callable[[str], str]
    visible_transcript_text: Callable[..., str]
    load_memorial: Callable[[str], dict[str, object]]
    load_private_profile: Callable[[str], dict[str, object]]
    resolve_voice_chat_model: Callable[..., str]
    is_contact_question: Callable[[str], bool]
    memorial_contact_answer_body: Callable[[str], str]
    memorial_chat_answer: Callable[..., dict[str, object]]
    memorial_chat_fallback_answer: Callable[..., dict[str, object]]
    load_voice_config: Callable[[str], dict[str, object]]
    memorial_fixed_conversation_language: Callable[[], str]
    voice_ab_variant_choice: Callable[..., dict[str, object]]
    apply_memorial_spoken_tts_clarity_policy: Callable[[dict[str, object]], dict[str, object]]
    tts_plugin_options: Callable[..., list[dict[str, object]]]
    resolve_server_tts_plugin: Callable[..., tuple[str, dict[str, object]]]
    compact_memorial_realtime_answer: Callable[[object], str]
    normalize_tts_text: Callable[[object], str]
    render_memorial_tts_audio: Callable[..., tuple[bytes, str]]
    pad_speech_audio_lead_in: Callable[..., tuple[bytes, str]]
    register_memorial_known_audio_transcript: Callable[..., None]
    remember_personal_conversation_turn: Callable[..., None]
    log_memorial_timing: Callable[..., None]
    list_of_dicts: Callable[[object], list[dict[str, object]]]
    piper_fast_tts_plugin_id: str
    memorial_conversation_turn_llm_timeout_seconds: float
    memorial_contact_tts_lead_in_ms: int
    memorial_contact_tts_tail_silence_ms: int
    memorial_fast_tts_lead_in_ms: int
    memorial_tts_lead_in_ms: int
    memorial_tts_tail_silence_ms: int


def runtime_from_shared(shared: Any) -> MemorialTurnRuntime:
    return MemorialTurnRuntime(
        text=shared._text,
        transcribe_audio_blob=shared._memorial_transcribe_audio_blob,
        canonical_contact_opening_question=shared._canonical_memorial_contact_opening_question,
        visible_transcript_text=shared._memorial_visible_transcript_text,
        load_memorial=shared._load_memorial,
        load_private_profile=getattr(shared, "_load_public_memorial_profile", lambda _slug: {}),
        resolve_voice_chat_model=shared._resolve_memorial_voice_chat_model,
        is_contact_question=shared._is_memorial_contact_question,
        memorial_contact_answer_body=shared._memorial_contact_answer_body,
        memorial_chat_answer=shared._memorial_chat_answer,
        memorial_chat_fallback_answer=shared._memorial_chat_fallback_answer,
        load_voice_config=shared._load_voice_config,
        memorial_fixed_conversation_language=shared._memorial_fixed_conversation_language,
        voice_ab_variant_choice=shared._voice_ab_variant_choice,
        apply_memorial_spoken_tts_clarity_policy=shared._apply_memorial_spoken_tts_clarity_policy,
        tts_plugin_options=shared._tts_plugin_options,
        resolve_server_tts_plugin=shared._resolve_server_tts_plugin,
        compact_memorial_realtime_answer=shared._compact_memorial_realtime_answer,
        normalize_tts_text=shared._normalize_tts_text,
        render_memorial_tts_audio=shared._render_memorial_tts_audio,
        pad_speech_audio_lead_in=shared._pad_speech_audio_lead_in,
        register_memorial_known_audio_transcript=shared._register_memorial_known_audio_transcript,
        remember_personal_conversation_turn=shared._remember_personal_conversation_turn,
        log_memorial_timing=shared._log_memorial_timing,
        list_of_dicts=shared._list_of_dicts,
        piper_fast_tts_plugin_id=shared.PIPER_FAST_TTS_PLUGIN_ID,
        memorial_conversation_turn_llm_timeout_seconds=shared._MEMORIAL_CONVERSATION_TURN_LLM_TIMEOUT_SECONDS,
        memorial_contact_tts_lead_in_ms=shared._MEMORIAL_CONTACT_TTS_LEAD_IN_MS,
        memorial_contact_tts_tail_silence_ms=shared._MEMORIAL_CONTACT_TTS_TAIL_SILENCE_MS,
        memorial_fast_tts_lead_in_ms=shared._MEMORIAL_FAST_TTS_LEAD_IN_MS,
        memorial_tts_lead_in_ms=shared._MEMORIAL_TTS_LEAD_IN_MS,
        memorial_tts_tail_silence_ms=shared._MEMORIAL_TTS_TAIL_SILENCE_MS,
    )
