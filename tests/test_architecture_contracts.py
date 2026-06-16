from __future__ import annotations

from app.api.routes import landing_console, workspace_view_models
from app.domain.office.surfaces import OfficeSurfacePayload
from app.services import office_surface_service, release_materialization_service
from app.services.memorial_turn_runtime import MemorialTurnRuntime
from app.services.memorial_turn_service import transcribe_public_memorial_audio
from app.services.office_surface_service import build_workspace_section_payload


def test_office_surface_payload_roundtrip_preserves_core_contracts() -> None:
    payload = OfficeSurfacePayload.from_mapping(
        {
            "title": "Morning Memo",
            "summary": "What changed first.",
            "stats": [{"label": "Queue items", "value": "4"}],
            "cards": [
                {
                    "eyebrow": "Top priorities",
                    "title": "What deserves attention first",
                    "body": "Start on the ranked work.",
                    "items": [{"title": "Follow up", "detail": "Board chair", "tag": "Priority"}],
                }
            ],
            "console_form": {"kind": "capture"},
            "activation_banner": {"body": "Open Today first."},
        }
    )

    rendered = payload.as_template_payload()

    assert rendered["title"] == "Morning Memo"
    assert rendered["summary"] == "What changed first."
    assert rendered["stats"] == [{"label": "Queue items", "value": "4"}]
    assert rendered["cards"][0]["title"] == "What deserves attention first"
    assert rendered["console_form"] == {"kind": "capture"}
    assert rendered["activation_banner"] == {"body": "Open Today first."}


def test_release_materialization_service_runs_expected_scripts_in_order(monkeypatch) -> None:
    calls: list[tuple[str, str, tuple[str, ...], dict[str, str] | None]] = []

    def fake_run_python(*, python_bin: str, step: release_materialization_service.ReleaseMaterializerStep) -> None:
        calls.append((python_bin, step.name, step.command, step.extra_env))

    monkeypatch.setattr(release_materialization_service, "_run_python", fake_run_python)

    release_materialization_service.materialize_release_assets(python_bin="/tmp/python")

    assert calls[0] == ("/tmp/python", "ea_browser_workflow_proof", ("scripts/materialize_ea_browser_workflow_proof.py",), None)
    assert calls[-1] == ("/tmp/python", "memorial_operator_status", ("scripts/materialize_memorial_operator_status.py",), None)
    assert any(
        name == "whole_project_gold_map" and command == ("scripts/materialize_whole_project_gold_map.py",) and env == {"PYTHONPATH": "ea"}
        for _, name, command, env in calls
    )


def test_workspace_view_models_resolve_office_sections_from_service_layer() -> None:
    assert workspace_view_models.workspace_section_payload is build_workspace_section_payload


def test_landing_console_routes_use_console_support_module() -> None:
    assert landing_console.app_shell.__module__ == "app.api.routes.landing_console"
    globals_map = getattr(landing_console.app_shell, "__globals__", {})
    support = globals_map.get("support")
    assert support is not None
    assert getattr(support, "__name__", "") == "app.api.routes.landing_console_support"
    assert "shared" not in globals_map


def test_transcribe_public_memorial_audio_preserves_visible_transcript() -> None:
    runtime = MemorialTurnRuntime(
        text=lambda value, default="": str(value or default),
        transcribe_audio_blob=lambda *, payload, content_type: {
            "transcript_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
            "transcription_status": "transcribed",
            "transcriber": "stub",
        },
        canonical_contact_opening_question=lambda text: "Worum geht es?" if text else "",
        visible_transcript_text=lambda *, transcript_text, effective_question: transcript_text,
        load_memorial=lambda slug: {},
        load_private_profile=lambda slug: {},
        resolve_voice_chat_model=lambda *args, **kwargs: "stub-model",
        is_contact_question=lambda text: False,
        memorial_contact_answer_body=lambda text: "Worum geht es?",
        memorial_chat_answer=lambda *args, **kwargs: {},
        memorial_chat_fallback_answer=lambda *args, **kwargs: {},
        load_voice_config=lambda slug: {},
        memorial_fixed_conversation_language=lambda: "de",
        voice_ab_variant_choice=lambda **kwargs: {},
        apply_memorial_spoken_tts_clarity_policy=lambda payload: payload,
        tts_plugin_options=lambda **kwargs: [],
        resolve_server_tts_plugin=lambda **kwargs: ("stub", {"tts_plugin_enabled": True}),
        compact_memorial_realtime_answer=lambda value: str(value or ""),
        normalize_tts_text=lambda value: str(value or ""),
        render_memorial_tts_audio=lambda **kwargs: (b"", "audio/wav"),
        pad_speech_audio_lead_in=lambda **kwargs: (kwargs["payload"], kwargs["content_type"]),
        register_memorial_known_audio_transcript=lambda **kwargs: None,
        remember_personal_conversation_turn=lambda **kwargs: None,
        log_memorial_timing=lambda *args, **kwargs: None,
        list_of_dicts=lambda value: [],
        piper_fast_tts_plugin_id="stub",
        memorial_conversation_turn_llm_timeout_seconds=1.0,
        memorial_contact_tts_lead_in_ms=0,
        memorial_contact_tts_tail_silence_ms=0,
        memorial_fast_tts_lead_in_ms=0,
        memorial_tts_lead_in_ms=0,
        memorial_tts_tail_silence_ms=0,
    )

    result = transcribe_public_memorial_audio(runtime=runtime, payload=b"audio", content_type="audio/wav").as_public_payload()

    assert result["transcript_text"] == "Worum geht es?"
    assert result["transcript_effective_text"] == "Worum geht es?"
    assert result["transcript_original_text"] == "Hallo Manfred, kannst du jetzt mit mir sprechen?"


def test_office_surface_service_no_longer_depends_on_workspace_route_module() -> None:
    assert office_surface_service._row.__module__ == "app.services.office_surface_rows"
