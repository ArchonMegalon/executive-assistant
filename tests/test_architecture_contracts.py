from __future__ import annotations

from pathlib import Path

from app.api.routes import landing_console, workspace_view_models
from app.domain.office.surfaces import OfficeSurfacePayload
from app.services import office_surface_service, release_materialization_service
from app.services import memorial_turn_service
from app.services.memorial_turn_runtime import MemorialTurnRuntime
from app.domain.memorial.turns import MemorialTurnRequest
from app.services.memorial_turn_service import build_public_memorial_turn, transcribe_public_memorial_audio
from app.services.office_surface_service import build_workspace_section_payload


def test_continuous_improvement_goal_keeps_manfred_spoken_conversation_in_scope() -> None:
    goal_text = (Path(__file__).resolve().parents[1] / ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "manfred premium speech goal" in goal_text
    assert "spoken conversation" in goal_text
    assert "text-only answer is a degraded fallback" in goal_text
    assert "manfred is not premium if he cannot reliably speak back" in goal_text


def test_continuous_improvement_goal_keeps_scope_gap_audit_in_scope() -> None:
    goal_text = (Path(__file__).resolve().parents[1] / ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "whole-project scope gap audit goal" in goal_text
    assert "build, run, remember, explain, publish" in goal_text
    assert "privacy/retention, telemetry/slos" in goal_text
    assert "owner-boundary pressure" in goal_text


def test_continuous_improvement_goal_keeps_acceptance_evidence_in_scope() -> None:
    goal_text = (Path(__file__).resolve().parents[1] / ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "real-world executive assistant acceptance evidence goal" in goal_text
    assert "one real morning brief is accepted as worth reading" in goal_text
    assert "raw private context, actor identity, and object references stay out" in goal_text
    assert "partial evidence must reduce the remaining blocker list" in goal_text


def test_continuous_improvement_goal_keeps_paid_assistant_ooda_scope() -> None:
    goal_text = (Path(__file__).resolve().parents[1] / ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "smart paid human assistant" in goal_text
    assert "paid-human-assistant-grade ooda loop" in goal_text
    assert "filled carts" in goal_text
    assert "inspect live sites" in goal_text
    assert "decision-ready packet the user can approve, dismiss, or defer in seconds" in goal_text
    assert "do not stop at a raw link dump" in goal_text
    assert "approval-ready handoff" in goal_text
    assert "staged link, approval state, delivery route, blockers, and follow-through receipt" in goal_text
    assert "resume later without repeating research" in goal_text
    assert "teable as an admin projection" in goal_text
    assert "pocket.ai or other consented audio transcript stream" in goal_text
    assert "audit before delivery" in goal_text
    assert "provider/category fit" in goal_text
    assert "1200 wien" in goal_text
    assert "gmail draft" in goal_text
    assert "telegram is an action surface, not a progress log" in goal_text
    assert "stale-approval cleanup" in goal_text


def test_continuous_improvement_goal_keeps_media_acceptance_in_scope() -> None:
    goal_text = (Path(__file__).resolve().parents[1] / ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "whole-project media acceptance goal" in goal_text
    assert "epub audiobooks are not done when the m4b exists" in goal_text
    assert "voice auditions must keep replacing dismissed voices immediately" in goal_text
    assert "promo videos are not done when an mp4 exists" in goal_text
    assert "generated, delivered, listened, accepted, published, and human-reviewed" in goal_text


def test_continuous_improvement_goal_keeps_premium_docs_memorial_whatsapp_in_scope() -> None:
    goal_text = (Path(__file__).resolve().parents[1] / ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "premium docs and memorial channel goal" in goal_text
    assert "the chummer docs repo is premium" in goal_text
    assert "whatsapp delivery is a first-class memorial channel" in goal_text
    assert "let manfred send an approved whatsapp message" in goal_text


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
    assert any(
        name == "ea_provider_contract_receipts"
        and command == ("scripts/materialize_ea_provider_contract_receipts.py",)
        and env == {"PYTHONPATH": "ea"}
        for _, name, command, env in calls
    )
    assert any(
        name == "memorial_stt_provider_benchmark"
        and command == ("scripts/benchmark_memorial_stt_providers.py",)
        and env == {"PYTHONPATH": "ea"}
        for _, name, command, env in calls
    )
    assert any(
        name == "teable_env_recovery_readiness"
        and command == ("scripts/materialize_teable_env_recovery_readiness.py",)
        and env is None
        for _, name, command, env in calls
    )
    assert any(
        name == "mymedia_alexa_readiness"
        and command == ("scripts/materialize_mymedia_alexa_readiness.py",)
        and env is None
        for _, name, command, env in calls
    )
    assert any(
        name == "proactive_ooda_operator_status"
        and command == ("scripts/materialize_proactive_ooda_operator_status.py",)
        and env is None
        for _, name, command, env in calls
    )
    assert any(
        name == "proactive_ooda_gold_acceptance"
        and command == ("scripts/materialize_proactive_ooda_gold_acceptance.py",)
        and env is None
        for _, name, command, env in calls
    )
    assert any(
        name == "runtime_dependency_evidence"
        and command == ("scripts/materialize_runtime_dependency_evidence.py",)
        and env is None
        for _, name, command, env in calls
    )
    assert any(
        name == "deploy_context"
        and command == ("scripts/materialize_deploy_context.py",)
        and env is None
        for _, name, command, env in calls
    )
    names = [name for _, name, _, _ in calls]
    assert names.index("telegram_video_delivery_receipt") < names.index("telegram_video_delivery_live_receipt")
    assert names.index("telegram_video_delivery_live_receipt") < names.index("whole_project_gold_map")
    assert names.index("ea_provider_contract_receipts") < names.index("whole_project_gold_map")
    assert names.index("teable_env_recovery_readiness") < names.index("mymedia_alexa_readiness")
    assert names.index("mymedia_alexa_readiness") < names.index("whatsapp_web_action_processor_readiness")
    assert names.index("whatsapp_web_action_processor_readiness") < names.index("proactive_ooda_operator_status")
    assert names.index("proactive_ooda_operator_status") < names.index("proactive_ooda_gold_acceptance")
    assert names.index("proactive_ooda_gold_acceptance") < names.index("continuous_improvement_goal_posture")
    assert names.index("mymedia_alexa_readiness") < names.index("continuous_improvement_goal_posture")
    assert names.index("memorial_stt_provider_benchmark") < names.index("memorial_operator_status")
    assert names.index("continuous_improvement_goal_posture") < names.index("deploy_context")
    assert names.index("runtime_dependency_evidence") < names.index("deploy_context")
    assert names.index("deploy_context") < names.index("release_manifest")
    assert names.index("release_manifest") < names.index("release_authority_status")
    assert names.index("release_authority_status") < names.index("ea_flagship_release_gate")
    assert names.index("ea_flagship_release_gate") < names.index("weekly_product_pulse")
    assert names.index("weekly_product_pulse") < names.index("whole_project_gold_map")
    assert names.index("whole_project_gold_map") < names.index("memorial_operator_status")


def test_workspace_view_models_resolve_office_sections_from_service_layer() -> None:
    assert workspace_view_models.workspace_section_payload is build_workspace_section_payload


def test_landing_console_routes_use_console_support_module() -> None:
    assert landing_console.app_shell.__module__ == "app.api.routes.landing_console"
    globals_map = getattr(landing_console.app_shell, "__globals__", {})
    support = globals_map.get("support")
    assert support is not None
    assert getattr(support, "__name__", "") == "app.api.routes.landing_console_support"
    assert "shared" not in globals_map


def test_transcribe_public_memorial_audio_preserves_visible_transcript(monkeypatch) -> None:
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
    clock = iter([100.0, 100.125])
    monkeypatch.setattr(memorial_turn_service.time, "perf_counter", lambda: next(clock))

    result = transcribe_public_memorial_audio(runtime=runtime, payload=b"audio", content_type="audio/wav").as_public_payload()

    assert result["transcript_text"] == "Worum geht es?"
    assert result["transcript_effective_text"] == "Worum geht es?"
    assert result["transcript_original_text"] == "Hallo Manfred, kannst du jetzt mit mir sprechen?"
    assert result["stt_ms"] == 125.0


def test_memorial_conversation_turn_timing_uses_measured_stt_latency(monkeypatch) -> None:
    timing_calls: list[dict[str, object]] = []
    clock_values = iter(
        [
            10.000,  # total start
            10.010,  # stt start
            10.210,  # stt end
            10.220,  # llm start
            10.250,  # llm end
            10.260,  # tts start
            10.320,  # tts end
            10.330,  # pad start
            10.340,  # pad end
            10.350,  # total end
        ]
    )
    monkeypatch.setattr(memorial_turn_service.time, "perf_counter", lambda: next(clock_values))
    runtime = MemorialTurnRuntime(
        text=lambda value, default="": str(value or default),
        transcribe_audio_blob=lambda *, payload, content_type: {
            "transcript_text": "Wie stehst du zur Gerechtigkeit?",
            "transcription_status": "transcribed",
            "transcriber": "stub",
        },
        canonical_contact_opening_question=lambda text: text,
        visible_transcript_text=lambda *, transcript_text, effective_question: transcript_text,
        load_memorial=lambda slug: {"person_name": "Manfred"},
        load_private_profile=lambda slug: {},
        resolve_voice_chat_model=lambda *args, **kwargs: "stub-model",
        is_contact_question=lambda text: False,
        memorial_contact_answer_body=lambda text: "Worum geht es?",
        memorial_chat_answer=lambda *args, **kwargs: {
            "answer": "Gerechtigkeit braucht klare Fakten.",
            "answer_audio_text": "Gerechtigkeit braucht klare Fakten.",
            "sources": [],
            "llm_model": "stub-model",
            "llm_provider": "stub-provider",
            "llm_fallback_used": False,
        },
        memorial_chat_fallback_answer=lambda *args, **kwargs: {},
        load_voice_config=lambda slug: {},
        memorial_fixed_conversation_language=lambda: "de",
        voice_ab_variant_choice=lambda **kwargs: {},
        apply_memorial_spoken_tts_clarity_policy=lambda payload: payload,
        tts_plugin_options=lambda **kwargs: [{"tts_plugin": "stub", "tts_plugin_enabled": True}],
        resolve_server_tts_plugin=lambda **kwargs: ("stub", {"tts_plugin_enabled": True}),
        compact_memorial_realtime_answer=lambda value: str(value or ""),
        normalize_tts_text=lambda value: str(value or ""),
        render_memorial_tts_audio=lambda **kwargs: (b"RIFFaudio", "audio/wav"),
        pad_speech_audio_lead_in=lambda **kwargs: (kwargs["payload"], kwargs["content_type"]),
        register_memorial_known_audio_transcript=lambda **kwargs: None,
        remember_personal_conversation_turn=lambda **kwargs: None,
        log_memorial_timing=lambda event, **fields: timing_calls.append({"event": event, **fields}),
        list_of_dicts=lambda value: [],
        piper_fast_tts_plugin_id="stub",
        memorial_conversation_turn_llm_timeout_seconds=1.0,
        memorial_contact_tts_lead_in_ms=0,
        memorial_contact_tts_tail_silence_ms=0,
        memorial_fast_tts_lead_in_ms=0,
        memorial_tts_lead_in_ms=0,
        memorial_tts_tail_silence_ms=0,
    )

    build_public_memorial_turn(
        runtime=runtime,
        request=MemorialTurnRequest(slug="manfred", audio_payload=b"audio", content_type="audio/wav"),
    )

    assert timing_calls[-1]["event"] == "conversation_turn"
    assert round(float(timing_calls[-1]["stt_ms"]), 1) == 200.0


def test_office_surface_service_no_longer_depends_on_workspace_route_module() -> None:
    assert office_surface_service._row.__module__ == "app.services.office_surface_rows"
