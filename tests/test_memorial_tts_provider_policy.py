from __future__ import annotations

from fastapi import HTTPException

from app.api.routes import public_memorial_tts_support, public_memorials


def test_safe_tts_plugin_id_coerces_openvoice_to_unmixr() -> None:
    assert public_memorials._safe_tts_plugin_id(public_memorials.OPENVOICE_TTS_PLUGIN_ID) == public_memorials.UNMIXR_TTS_PLUGIN_ID


def test_tts_plugin_options_exclude_openvoice() -> None:
    options = public_memorial_tts_support._tts_plugin_options(
        payload={},
        voice_profile_ready=True,
        runtime_secret_placeholder=lambda value: str(value or ""),
        text=lambda value, fallback="": str(value or fallback),
        browser_speech_tts_plugin_id="browser_speech_synthesis",
        unmixr_tts_plugin_id=public_memorials.UNMIXR_TTS_PLUGIN_ID,
        openvoice_tts_plugin_id=public_memorials.OPENVOICE_TTS_PLUGIN_ID,
        piper_fast_plugin_option=lambda: {"tts_plugin": public_memorials.PIPER_FAST_TTS_PLUGIN_ID, "tts_plugin_enabled": True},
        unmixr_plugin_option=lambda **kwargs: {"tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID, "tts_plugin_enabled": True, **kwargs},
        voicewave_plugin_option=lambda **kwargs: {"tts_plugin": public_memorials.VOICEWAVE_TTS_PLUGIN_ID, "tts_plugin_enabled": True, **kwargs},
        openvoice_plugin_option=lambda **kwargs: {"tts_plugin": public_memorials.OPENVOICE_TTS_PLUGIN_ID, "tts_plugin_enabled": True, **kwargs},
        unmixr_memorial_voice_id=lambda: "unmixr-voice",
        openvoice_memorial_voice_id=lambda: "openvoice-voice",
        voicewave_memorial_voice_label=lambda: "voicewave-voice",
    )

    assert {str(option.get("tts_plugin")) for option in options} == {
        public_memorials.PIPER_FAST_TTS_PLUGIN_ID,
        "browser_speech_synthesis",
        public_memorials.UNMIXR_TTS_PLUGIN_ID,
        public_memorials.VOICEWAVE_TTS_PLUGIN_ID,
    }


def test_voice_ab_auto_build_challenger_does_not_fallback_to_openvoice(monkeypatch) -> None:
    saved_pools: list[dict[str, object]] = []

    monkeypatch.setattr(public_memorials, "_load_voice_ab_pool", lambda slug: {})
    monkeypatch.setattr(public_memorials, "_voice_ab_analysis", lambda slug: {"weak_dimensions": []})
    monkeypatch.setattr(public_memorials, "_voice_ab_profile_sample_paths", lambda **kwargs: ["sample-a.wav"])
    monkeypatch.setattr(public_memorials, "_load_memorial", lambda slug: {"person_name": "Manfred"})
    monkeypatch.setattr(public_memorials, "_load_voice_ab_ratings", lambda slug: {"round": 1})
    monkeypatch.setattr(public_memorials, "_save_voice_ab_pool", lambda slug, pool: saved_pools.append(dict(pool)))
    monkeypatch.setattr(
        public_memorials,
        "unmixr_clone_request",
        lambda **kwargs: (_ for _ in ()).throw(HTTPException(status_code=429, detail="Reached the limit")),
    )
    monkeypatch.setattr(
        public_memorials,
        "openvoice_clone_request",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("openvoice fallback must not run")),
    )

    challenger = public_memorials._voice_ab_auto_build_challenger("manfred", excluded_voice_ids=set())

    assert challenger is None
    assert saved_pools[-1]["last_clone_error"] == "Reached the limit"
