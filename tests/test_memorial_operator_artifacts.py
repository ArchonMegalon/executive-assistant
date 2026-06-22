from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module(path_str: str, name: str):
    path = Path(path_str)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_memorial_phrase_bank_materializer_writes_expected_ids(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_phrase_bank.py", "materialize_memorial_phrase_bank")
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "phrase_bank.json")
    assert module.main() == 0
    payload = __import__("json").loads((tmp_path / "phrase_bank.json").read_text(encoding="utf-8"))
    ids = {item["id"] for item in payload["phrases"]}
    assert {"contact_opening", "present_world_guardrail", "weather_guardrail"} <= ids


def test_memorial_operator_status_materializer_summarizes_blocked_public_gold(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_operator_status.py", "materialize_memorial_operator_status")
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "operator_status.json")
    monkeypatch.setattr(module, "MEANINGFUL_BROWSER_RECEIPT", tmp_path / "meaningful-browser.json")
    room_attestation_packet = tmp_path / "room-attestation-packet.json"
    room_attestation_packet.write_text(
        json.dumps(
            {
                "status": "ready",
                "manual_only": True,
                "ci_must_not_auto_assert": True,
                "proof_target": ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
                "operator_command": "make materialize-memorial-room-audio-gold-clean",
                "required_env": {"MEMORIAL_ROOM_REVIEWER": "actual listener/operator name"},
                "required_checks": [{"id": "normal_spoken_turn_confirmed"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOM_AUDIO_ATTESTATION_PACKET", room_attestation_packet)
    whole_project_map = tmp_path / "whole-project-gold-map.json"
    whole_project_map.write_text(
        json.dumps(
            {
                "overall_status": "not_gold",
                "gold_claim_allowed": False,
                "blocking_planes": ["memorial_public_origin_gold"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WHOLE_PROJECT_GOLD_MAP", whole_project_map)
    monkeypatch.setattr(
        module,
        "_run_json",
        lambda script: (
            {
                "memorial_voice_gold_claim_allowed": False,
                "local_release_issues": [],
                "public_gold_issues": ["receipt_missing_or_invalid"],
                "public_browser_gold_issues": ["browser_receipt_missing_or_invalid"],
                "room_audio_issues": ["room_receipt_missing_or_invalid"],
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "blocked"}
        ),
    )
    assert module.main() == 0
    payload = __import__("json").loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["current_label"] == "Memorial public-origin gold: blocked"
    assert payload["local_release_candidate"] == "pass"
    assert payload["public_voice_receipt"] == "missing_or_blocked"
    assert payload["public_browser_meaningful_receipt"] == "missing_or_blocked"
    assert payload["whole_project_gold"] == "blocked"
    assert payload["whole_project_map_summary"]["blocking_planes"] == ["memorial_public_origin_gold"]
    assert payload["artifact_paths"]["room_audio_attestation_packet"] == str(room_attestation_packet)
    assert payload["room_audio_attestation_packet"]["status"] == "ready"
    assert payload["room_audio_attestation_packet"]["manual_only"] is True
    assert payload["room_audio_attestation_packet"]["ci_must_not_auto_assert"] is True
    assert payload["room_audio_attestation_packet"]["next_action"] == "collect_real_room_audio_attestation"
    assert payload["room_audio_attestation_packet"]["required_check_ids"] == ["normal_spoken_turn_confirmed"]


def test_memorial_operator_status_run_json_reads_blocked_json_from_stderr(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_operator_status.py", "materialize_memorial_operator_status_stderr")

    class _Proc:
        stdout = ""
        stderr = '{"status":"blocked","issues":["stale_receipt"]}'

    calls: dict[str, object] = {}

    def _fake_run(*args, **kwargs):
        calls["cwd"] = kwargs.get("cwd")
        return _Proc()

    monkeypatch.setattr(module.subprocess, "run", _fake_run)
    payload = module._run_json("scripts/verify_whole_project_gold_map.py")
    assert payload["status"] == "blocked"
    assert calls["cwd"] == module.ROOT


def test_memorial_operator_status_marks_whole_project_gold_pass_only_when_map_allows_it(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_operator_status.py", "materialize_memorial_operator_status_gold_pass")
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "operator_status.json")
    meaningful_receipt = tmp_path / "meaningful-browser.json"
    meaningful_receipt.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    monkeypatch.setattr(module, "MEANINGFUL_BROWSER_RECEIPT", meaningful_receipt)
    whole_project_map = tmp_path / "whole-project-gold-map.json"
    whole_project_map.write_text(
        json.dumps(
            {
                "overall_status": "gold",
                "gold_claim_allowed": True,
                "blocking_planes": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WHOLE_PROJECT_GOLD_MAP", whole_project_map)
    monkeypatch.setattr(
        module,
        "_run_json",
        lambda script: (
            {
                "memorial_voice_gold_claim_allowed": True,
                "local_release_issues": [],
                "public_gold_issues": [],
                "public_browser_gold_issues": [],
                "room_audio_issues": [],
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "pass"}
        ),
    )
    assert module.main() == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["whole_project_gold"] == "pass"
    assert payload["public_browser_meaningful_receipt"] == "pass"
    assert payload["status"] == "pass"
    assert payload["artifact_paths"]["public_gold_receipt"] == ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"
    assert payload["workflow_backing"]["status"] == "no"
    assert payload["public_voice_receipt_semantics"]["label"] in {
        "Memorial public voice provenance proof",
        "Memorial public voice gold proof",
    }


def test_memorial_operator_status_reads_public_voice_transcriber_mode_from_metrics(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_metrics_semantics",
    )
    receipt = tmp_path / "public-voice.json"
    receipt.write_text(
        json.dumps(
            {
                "metrics": {
                    "direct_tts_transcriber": "memorial_tts_provenance_cache",
                    "conversation_turn_transcriber": "memorial_tts_provenance_cache",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "PUBLIC_VOICE_RECEIPT", receipt)

    payload = module._public_voice_receipt_semantics()
    assert payload["label"] == "Memorial public voice provenance proof"
    assert payload["transcriber_mode"] == "provenance_cache"
    assert payload["direct_tts_transcriber"] == "memorial_tts_provenance_cache"
    assert payload["conversation_turn_transcriber"] == "memorial_tts_provenance_cache"


def test_memorial_operator_status_summarizes_spoken_tts_playback(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_spoken_tts",
    )
    public_voice = tmp_path / "public-voice.json"
    public_browser = tmp_path / "public-browser.json"
    room_audio = tmp_path / "room-audio.json"
    public_voice.write_text(
        json.dumps(
            {
                "status": "pass",
                "metrics": {
                    "direct_tts_audio_status": "pass",
                    "conversation_turn_audio_status": "pass",
                    "direct_tts_f1": 1.0,
                    "conversation_turn_audio_f1": 0.95,
                },
            }
        ),
        encoding="utf-8",
    )
    public_browser.write_text(
        json.dumps(
            {
                "status": "pass",
                "audio_ready_for_ui": True,
                "audio_payload_ready": False,
                "audio_unavailable": False,
                "ui_audio_play_calls": 1,
                "ui_audio_play_ended": 1,
                "ui_audio_play_error": "",
                "conversation_turn_payload": {"audio_base64": ""},
            }
        ),
        encoding="utf-8",
    )
    room_audio.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    monkeypatch.setattr(module, "PUBLIC_VOICE_RECEIPT", public_voice)
    monkeypatch.setattr(module, "PUBLIC_BROWSER_RECEIPT", public_browser)
    monkeypatch.setattr(module, "ROOM_AUDIO_RECEIPT", room_audio)

    status = module._spoken_tts_playback_status()

    assert status["status"] == "pass"
    assert status["premium_status"] == "pass"
    assert status["browser_audio_transport"] == "ui_playback_probe"
    assert status["browser_play_calls"] == 1
    assert status["browser_play_ended"] == 1
    assert status["failed_codes"] == []
    assert status["premium_failed_codes"] == []


def test_memorial_operator_status_blocks_premium_tts_without_room_audio(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_spoken_tts_room_blocked",
    )
    public_voice = tmp_path / "public-voice.json"
    public_browser = tmp_path / "public-browser.json"
    room_audio = tmp_path / "room-audio.json"
    public_voice.write_text(
        json.dumps(
            {
                "status": "pass",
                "metrics": {
                    "direct_tts_audio_status": "pass",
                    "conversation_turn_audio_status": "pass",
                    "direct_tts_f1": 1.0,
                    "conversation_turn_audio_f1": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )
    public_browser.write_text(
        json.dumps(
            {
                "status": "pass",
                "audio_ready_for_ui": True,
                "audio_unavailable": False,
                "ui_audio_play_calls": 1,
                "ui_audio_play_ended": 1,
                "ui_audio_play_error": "",
            }
        ),
        encoding="utf-8",
    )
    room_audio.write_text(json.dumps({"status": "fail"}), encoding="utf-8")
    monkeypatch.setattr(module, "PUBLIC_VOICE_RECEIPT", public_voice)
    monkeypatch.setattr(module, "PUBLIC_BROWSER_RECEIPT", public_browser)
    monkeypatch.setattr(module, "ROOM_AUDIO_RECEIPT", room_audio)

    status = module._spoken_tts_playback_status()

    assert status["status"] == "pass"
    assert status["premium_status"] == "blocked"
    assert status["failed_codes"] == []
    assert status["premium_failed_codes"] == ["room_audio_attestation_not_pass"]
    assert status["next_action"] == "collect_real_room_audio_attestation"


def test_memorial_operator_status_reports_missing_room_attestation_packet(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_room_packet_missing",
    )
    packet = tmp_path / "missing-room-attestation.json"
    monkeypatch.setattr(module, "ROOM_AUDIO_ATTESTATION_PACKET", packet)

    status = module._room_audio_attestation_packet_status()

    assert status["status"] == "missing"
    assert status["manual_only"] is True
    assert status["operator_command"] == "make materialize-memorial-room-audio-attestation-packet"
    assert status["next_action"] == "materialize_manual_attestation_packet"


def test_memorial_operator_status_summarizes_blocked_spoken_stt_benchmark(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_spoken_stt",
    )
    receipt = tmp_path / "memorial_stt_provider_benchmark.generated.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "blocked",
                "scoring": {
                    "production_eligible_rule": "provider must pass every ground-truth benchmark sample and hostile variant",
                    "text_mode": "redacted",
                    "raw_transcript_fields": False,
                    "redacted_text_fields": True,
                },
                "availability": {
                    "cartesia_configured": False,
                    "onemin_key_count": 0,
                    "cartesia": {
                        "configured": False,
                        "credential_source": "none",
                        "default_credential_files": [
                            {
                                "path": "config/cartesia.local.json",
                                "present": False,
                                "contains_key": False,
                            }
                        ],
                    },
                },
                "provider_ranking": [
                    {
                        "provider": "full_runtime",
                        "passed_samples": 0,
                        "sample_count": 4,
                        "avg_token_f1": 0.0,
                        "avg_wer": 1.0,
                        "avg_latency_ms": 12.5,
                        "production_eligible": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "STT_PROVIDER_BENCHMARK_RECEIPT", receipt)

    status = module._spoken_stt_provider_benchmark_status()

    assert status["status"] == "blocked"
    assert status["receipt_status"] == "blocked"
    assert status["production_eligible"] is False
    assert status["best_provider"] == ""
    assert status["production_provider"] == ""
    assert status["top_candidate_provider"] == "full_runtime"
    assert status["provider_label"] == "no_production_stt_provider"
    assert status["passed_samples"] == 0
    assert status["sample_count"] == 4
    assert status["availability"]["cartesia_configured"] is False
    assert status["cartesia_credential_status"]["credential_source"] == "none"
    assert status["next_action"] == "configure_cartesia_credentials"
    assert status["scoring"]["production_eligible_rule"] == "provider must pass every ground-truth benchmark sample and hostile variant"
    assert status["scoring"]["text_mode"] == "redacted"
    assert status["scoring"]["raw_transcript_fields"] is False
    assert status["scoring"]["redacted_text_fields"] is True


def test_memorial_operator_status_prioritizes_invalid_stt_fixtures_before_provider_tuning(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_stt_fixture_quality",
    )
    receipt = tmp_path / "memorial_stt_provider_benchmark.generated.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "blocked",
                "fixture_quality_status": "blocked",
                "fixture_quality_failed_codes": [
                    "audio_too_short_for_expected_text",
                    "captured_audio_too_short",
                ],
                "availability": {
                    "cartesia_configured": True,
                    "cartesia": {
                        "configured": True,
                        "credential_source": "default_credential_file",
                    },
                },
                "provider_ranking": [
                    {
                        "provider": "full_runtime",
                        "passed_samples": 0,
                        "sample_count": 4,
                        "avg_token_f1": 0.0,
                        "avg_wer": 1.0,
                        "avg_latency_ms": 0.0,
                        "production_eligible": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "STT_PROVIDER_BENCHMARK_RECEIPT", receipt)

    status = module._spoken_stt_provider_benchmark_status()

    assert status["status"] == "blocked"
    assert status["cartesia_credential_status"]["credential_source"] == "default_credential_file"
    assert status["fixture_quality_status"] == "blocked"
    assert status["fixture_quality_failed_codes"] == [
        "audio_too_short_for_expected_text",
        "captured_audio_too_short",
    ]
    assert status["next_action"] == "replace_memorial_stt_captured_fixtures"


def test_memorial_operator_status_reports_passed_synthetic_stt_benchmark_honestly(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_stt_pass",
    )
    receipt = tmp_path / "memorial_stt_provider_benchmark.generated.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "pass",
                "fixture_quality_status": "pass",
                "fixture_quality_failed_codes": [],
                "availability": {
                    "cartesia_configured": True,
                    "cartesia": {
                        "configured": True,
                        "credential_source": "default_credential_file",
                    },
                },
                "provider_ranking": [
                    {
                        "provider": "full_runtime",
                        "passed_samples": 4,
                        "sample_count": 4,
                        "avg_token_f1": 1.0,
                        "avg_wer": 0.0,
                        "avg_latency_ms": 431.5,
                        "production_eligible": True,
                    }
                ],
                "rows": [
                    {"provenance": {"synthetic": True}},
                    {"provenance": {"synthetic": True}},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "STT_PROVIDER_BENCHMARK_RECEIPT", receipt)

    status = module._spoken_stt_provider_benchmark_status()

    assert status["status"] == "pass"
    assert status["production_provider"] == "full_runtime"
    assert status["avg_wer"] == 0.0
    assert status["ground_truth_fixture_mode"] == "synthetic_only"
    assert status["next_action"] == "add_real_captured_stt_fixture"


def test_memorial_operator_status_names_cartesia_transcriber_and_blocked_fallbacks(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_stt_cartesia_fallbacks",
    )
    receipt = tmp_path / "memorial_stt_provider_benchmark.generated.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "pass",
                "fixture_quality_status": "pass",
                "fixture_quality_failed_codes": [],
                "availability": {
                    "cartesia_configured": True,
                    "cartesia": {
                        "configured": True,
                        "credential_source": "default_credential_file",
                    },
                    "onemin_key_count": 71,
                    "shadow_provider": "blipai",
                },
                "provider_ranking": [
                    {
                        "provider": "full_runtime",
                        "passed_samples": 4,
                        "sample_count": 4,
                        "scored_samples": 4,
                        "avg_token_f1": 1.0,
                        "avg_wer": 0.0,
                        "avg_latency_ms": 431.5,
                        "production_eligible": True,
                    },
                    {
                        "provider": "shadow",
                        "passed_samples": 0,
                        "sample_count": 4,
                        "scored_samples": 4,
                        "avg_token_f1": 0.0,
                        "avg_wer": 1.0,
                        "production_eligible": False,
                    },
                    {
                        "provider": "onemin_sample",
                        "passed_samples": 0,
                        "sample_count": 4,
                        "scored_samples": 0,
                        "avg_token_f1": 0.0,
                        "avg_wer": 1.0,
                        "production_eligible": False,
                    },
                ],
                "rows": [
                    {
                        "provenance": {"synthetic": True},
                        "full_runtime": {
                            "transcriber": "cartesia/ink-whisper+enhanced_wav",
                            "passed": True,
                        },
                    },
                    {
                        "provenance": {"synthetic": True},
                        "full_runtime": {
                            "transcriber": "cartesia/ink-whisper+enhanced_wav",
                            "passed": True,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "STT_PROVIDER_BENCHMARK_RECEIPT", receipt)

    status = module._spoken_stt_provider_benchmark_status()

    assert status["status"] == "pass"
    assert status["production_provider"] == "full_runtime"
    assert status["provider_key"] == "full_runtime"
    assert status["production_transcriber"] == "cartesia/ink-whisper+enhanced_wav"
    assert status["provider_label"] == "cartesia/ink-whisper+enhanced_wav"
    assert status["fallback_health"] == "blocked"
    assert status["fallback_production_eligible"] is False
    assert [item["provider"] for item in status["fallback_provider_statuses"]] == [
        "shadow",
        "onemin_sample",
    ]


def test_memorial_operator_status_reconciles_failed_captured_candidate_next_action() -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_reconcile_failed_captured_candidate",
    )

    status = module._reconcile_spoken_stt_next_action(
        {
            "status": "pass",
            "next_action": "add_real_captured_stt_fixture",
        },
        {
            "status": "pass",
            "promotion_gate": {
                "next_action": "run_captured_candidate_benchmark_before_fixture_manifest",
            },
        },
        {
            "status": "blocked",
            "captured_rows": 2,
        },
    )

    assert status["real_captured_fixture_status"] == "captured_candidate_benchmark_blocked"
    assert status["next_action"] == "inspect_captured_candidate_ground_truth_or_capture_new_audio"


def test_memorial_operator_status_reconciles_passed_captured_candidate_next_action() -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_reconcile_passed_captured_candidate",
    )

    status = module._reconcile_spoken_stt_next_action(
        {
            "status": "pass",
            "next_action": "add_real_captured_stt_fixture",
        },
        {"status": "pass"},
        {
            "status": "pass",
            "captured_rows": 2,
        },
    )

    assert status["real_captured_fixture_status"] == "captured_candidate_benchmark_pass"
    assert status["next_action"] == "promote_captured_candidate_to_fixture_manifest"


def test_memorial_operator_status_reports_missing_stt_fixture_candidate(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_missing_stt_candidate",
    )
    monkeypatch.setattr(module, "STT_FIXTURE_CANDIDATE_RECEIPT", tmp_path / "missing.json")

    status = module._stt_fixture_candidate_status()

    assert status["status"] == "missing"
    assert status["next_action"] == "materialize_candidate_from_pcloud_with_operator_transcript_and_consent"


def test_memorial_operator_status_routes_implausible_stt_fixture_candidate_to_normalization(
    tmp_path,
    monkeypatch,
) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_blocked_stt_candidate",
    )
    receipt = tmp_path / "candidate.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "blocked",
                "failed_codes": ["audio_duration_implausible"],
                "bundle": {"id": "082347_realtime_audio_turn_generic_fallback_answer"},
                "audio": {"bytes": 84558, "duration_seconds": 134217.728},
                "candidate_manifest_entry": {
                    "sample": "real_room_retry_candidate",
                    "synthetic": False,
                },
                "text_mode": "redacted",
                "raw_text_fields": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "STT_FIXTURE_CANDIDATE_RECEIPT", receipt)

    status = module._stt_fixture_candidate_status()

    assert status["status"] == "blocked"
    assert status["bundle_id"] == "082347_realtime_audio_turn_generic_fallback_answer"
    assert status["sample"] == "real_room_retry_candidate"
    assert status["raw_text_fields"] is False
    assert status["next_action"] == "normalize_captured_audio_before_fixture_promotion"


def test_memorial_operator_status_reports_passed_stt_fixture_candidate(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_passed_stt_candidate",
    )
    receipt = tmp_path / "candidate.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "pass",
                "failed_codes": [],
                "candidate_scope": "audio_quality_and_provenance_only",
                "promotion_gate": {
                    "status": "pending_captured_candidate_benchmark",
                    "required_receipt": ".codex-studio/published/memorial_stt_provider_benchmark_captured_candidate.generated.json",
                    "may_update_fixture_manifest": False,
                    "next_action": "run_captured_candidate_benchmark_before_fixture_manifest",
                },
                "bundle": {"id": "captured-question"},
                "audio": {"bytes": 32000, "duration_seconds": 3.0},
                "candidate_manifest_entry": {
                    "sample": "real_room_retry_candidate",
                    "synthetic": False,
                },
                "text_mode": "redacted",
                "raw_text_fields": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "STT_FIXTURE_CANDIDATE_RECEIPT", receipt)

    status = module._stt_fixture_candidate_status()

    assert status["status"] == "pass"
    assert status["synthetic"] is False
    assert status["candidate_scope"] == "audio_quality_and_provenance_only"
    assert status["promotion_gate"]["may_update_fixture_manifest"] is False
    assert status["next_action"] == "run_captured_candidate_benchmark_before_fixture_manifest"


def test_memorial_operator_status_reports_missing_stt_capture_discovery(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_missing_stt_capture_discovery",
    )
    monkeypatch.setattr(module, "STT_CAPTURE_DISCOVERY_RECEIPT", tmp_path / "missing.json")

    status = module._stt_capture_discovery_status()

    assert status["status"] == "missing"
    assert status["next_action"] == "materialize_redacted_capture_discovery_from_selected_pcloud_bundles"


def test_memorial_operator_status_routes_truncated_stt_capture_discovery_to_new_capture(
    tmp_path,
    monkeypatch,
) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_truncated_stt_capture_discovery",
    )
    receipt = tmp_path / "discovery.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "blocked",
                "target_samples": ["contact_opening"],
                "bundle_count": 5,
                "matched_count": 5,
                "promotable_count": 0,
                "failed_codes": ["audio_too_short_for_expected_text"],
                "text_mode": "redacted",
                "raw_text_fields": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "STT_CAPTURE_DISCOVERY_RECEIPT", receipt)

    status = module._stt_capture_discovery_status()

    assert status["status"] == "blocked"
    assert status["matched_count"] == 5
    assert status["promotable_count"] == 0
    assert status["raw_text_fields"] is False
    assert status["next_action"] == "capture_new_real_question_audio_or_fix_truncated_logger"


def test_memorial_operator_status_reports_promotable_stt_capture_discovery(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_promotable_stt_capture_discovery",
    )
    receipt = tmp_path / "discovery.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "pass",
                "target_samples": ["contact_opening"],
                "bundle_count": 1,
                "matched_count": 1,
                "promotable_count": 1,
                "failed_codes": [],
                "text_mode": "redacted",
                "raw_text_fields": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "STT_CAPTURE_DISCOVERY_RECEIPT", receipt)

    status = module._stt_capture_discovery_status()

    assert status["status"] == "pass"
    assert status["promotable_count"] == 1
    assert status["next_action"] == "use_promotable_discovered_capture_for_benchmark"


def test_memorial_operator_status_reports_missing_captured_candidate_benchmark(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_missing_captured_candidate_benchmark",
    )
    monkeypatch.setattr(module, "STT_CAPTURED_CANDIDATE_BENCHMARK_RECEIPT", tmp_path / "missing.json")

    status = module._captured_candidate_benchmark_status()

    assert status["status"] == "missing"
    assert status["next_action"] == "run_opt_in_captured_candidate_benchmark"


def test_memorial_operator_status_routes_failed_captured_candidate_benchmark_to_inspection(
    tmp_path,
    monkeypatch,
) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_blocked_captured_candidate_benchmark",
    )
    receipt = tmp_path / "captured-benchmark.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "blocked",
                "provider_ranking": [
                    {
                        "provider": "full_runtime",
                        "passed_samples": 4,
                        "sample_count": 6,
                        "production_eligible": False,
                    }
                ],
                "rows": [
                    {
                        "sample": "real_room_retry_candidate",
                        "variant": "captured",
                        "provenance": {"external_bundle": True},
                        "full_runtime": {
                            "passed": False,
                            "wer": 0.8889,
                            "token_f1": 0.2353,
                            "intent_correct": False,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "STT_CAPTURED_CANDIDATE_BENCHMARK_RECEIPT", receipt)

    status = module._captured_candidate_benchmark_status()

    assert status["status"] == "blocked"
    assert status["best_provider"] == "full_runtime"
    assert status["captured_rows"] == 1
    assert status["captured_full_runtime_passed"] is False
    assert status["captured_full_runtime_failures"] == [
        {
            "sample": "real_room_retry_candidate",
            "variant": "captured",
            "wer": 0.8889,
            "token_f1": 0.2353,
            "intent_correct": False,
        }
    ]
    assert status["next_action"] == "inspect_captured_candidate_ground_truth_or_stt_failure"


def test_memorial_operator_status_reports_passed_captured_candidate_benchmark(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_passed_captured_candidate_benchmark",
    )
    receipt = tmp_path / "captured-benchmark.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "pass",
                "provider_ranking": [
                    {
                        "provider": "full_runtime",
                        "passed_samples": 6,
                        "sample_count": 6,
                        "production_eligible": True,
                    }
                ],
                "rows": [
                    {
                        "sample": "real_room_retry_candidate",
                        "variant": "captured",
                        "provenance": {"external_bundle": True},
                        "full_runtime": {"passed": True},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "STT_CAPTURED_CANDIDATE_BENCHMARK_RECEIPT", receipt)

    status = module._captured_candidate_benchmark_status()

    assert status["status"] == "pass"
    assert status["production_eligible"] is True
    assert status["captured_full_runtime_passed"] is True
    assert status["next_action"] == "promote_captured_candidate_to_fixture_manifest"


def test_memorial_operator_status_keeps_memorial_pass_when_unrelated_whole_project_gold_is_disallowed(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_operator_status.py", "materialize_memorial_operator_status_whole_project_blocked")
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "operator_status.json")
    whole_project_map = tmp_path / "whole-project-gold-map.json"
    whole_project_map.write_text(
        json.dumps(
            {
                "overall_status": "not_gold",
                "gold_claim_allowed": False,
                "blocking_planes": ["chummer_desktop_ui"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WHOLE_PROJECT_GOLD_MAP", whole_project_map)
    monkeypatch.setattr(
        module,
        "_run_json",
        lambda script: (
            {
                "memorial_voice_gold_claim_allowed": True,
                "local_release_issues": [],
                "public_gold_issues": [],
                "public_browser_gold_issues": [],
                "room_audio_issues": [],
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "pass"}
        ),
    )

    assert module.main() == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["current_label"] == "Memorial public-origin gold: pass"
    assert payload["whole_project_gold"] == "blocked"
    assert payload["status"] == "pass"


def test_memorial_operator_status_fails_closed_when_whole_project_verifier_blocks(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_operator_status.py", "materialize_memorial_operator_status_verifier_blocked")
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "operator_status.json")
    whole_project_map = tmp_path / "whole-project-gold-map.json"
    whole_project_map.write_text(
        json.dumps(
            {
                "overall_status": "gold",
                "gold_claim_allowed": True,
                "blocking_planes": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WHOLE_PROJECT_GOLD_MAP", whole_project_map)
    monkeypatch.setattr(
        module,
        "_run_json",
        lambda script: (
            {
                "status": "pass",
                "memorial_voice_gold_claim_allowed": True,
                "local_release_issues": [],
                "public_gold_issues": [],
                "public_browser_gold_issues": [],
                "room_audio_issues": [],
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "blocked", "issues": ["whole-project gold map is stale relative to current HEAD"]}
        ),
    )

    assert module.main() == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["whole_project_gold"] == "blocked"
    assert payload["current_label"] == "Memorial public-origin gold: pass"
    assert payload["status"] == "pass"


def test_memorial_operator_status_uses_source_state_head(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_operator_status.py", "materialize_memorial_operator_status_source_head")
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "operator_status.json")
    monkeypatch.setattr(module, "resolve_source_state_head", lambda root: "SOURCE_HEAD")
    monkeypatch.setattr(
        module,
        "source_worktree_metadata",
        lambda root: {
            "source_worktree_dirty": False,
            "source_dirty_count": 0,
            "source_dirty_files": [],
            "source_dirty_omitted_count": 0,
            "source_dirty_status_sha256": "",
        },
    )
    monkeypatch.setattr(
        module,
        "_run_json",
        lambda script: (
            {
                "status": "pass",
                "memorial_voice_gold_claim_allowed": True,
                "local_release_issues": [],
                "public_gold_issues": [],
                "public_browser_gold_issues": [],
                "room_audio_issues": [],
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "pass"}
        ),
    )

    assert module.main() == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["source_git_head"] == "SOURCE_HEAD"
    assert payload["source_worktree_dirty"] is False
    assert payload["source_dirty_count"] == 0


def test_memorial_operator_status_reports_dirty_source_snapshot(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_dirty_source",
    )
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "operator_status.json")
    monkeypatch.setattr(module, "resolve_source_state_head", lambda root: "SOURCE_HEAD")
    monkeypatch.setattr(
        module,
        "source_worktree_metadata",
        lambda root: {
            "source_worktree_dirty": True,
            "source_dirty_count": 2,
            "source_dirty_files": ["app/api/routes/public_memorials.py"],
            "source_dirty_omitted_count": 1,
            "source_dirty_status_sha256": "dirty-sha",
        },
    )
    monkeypatch.setattr(
        module,
        "_run_json",
        lambda script: (
            {
                "status": "pass",
                "memorial_voice_gold_claim_allowed": True,
                "local_release_issues": [],
                "public_gold_issues": [],
                "public_browser_gold_issues": [],
                "room_audio_issues": [],
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "pass"}
        ),
    )

    assert module.main() == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["source_git_head"] == "SOURCE_HEAD"
    assert payload["source_worktree_dirty"] is True
    assert payload["source_dirty_count"] == 2
    assert payload["source_dirty_files"] == ["app/api/routes/public_memorials.py"]
    assert payload["source_dirty_omitted_count"] == 1
    assert payload["source_dirty_status_sha256"] == "dirty-sha"
    assert any("must not be used as final release evidence" in note for note in payload["operator_notes"])


def test_memorial_room_audio_clean_materializer_builds_expected_receipt_command() -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_room_audio_receipt_clean.py", "materialize_memorial_room_audio_receipt_clean")

    class _Args:
        python_bin = "python3"
        base_url = "https://example.com"
        slug = "manfred"
        reviewer = "reviewer"
        device_label = "laptop"
        speaker_label = "speaker"
        room_label = "office"
        notes = "ok"
        manual_attestation_id = "room-review-001"
        manual_attestation_signed_at = "2026-06-18T12:00:00Z"
        manual_attestation_source = "operator_room_review"

    cmd = module.build_room_receipt_command(_Args())
    assert cmd[:2] == ["python3", "scripts/materialize_memorial_room_audio_receipt.py"]
    assert "--base-url" in cmd
    assert "https://example.com" in cmd
    assert "--reviewer" in cmd
    assert "reviewer" in cmd
    assert "--require-public-origin" in cmd
    assert "--manual-attestation-id" in cmd
    assert "room-review-001" in cmd
    assert "--first-syllable-not-clipped" in cmd
    assert "--normal-spoken-turn-confirmed" in cmd
    assert "--interruption-behavior-confirmed" in cmd
    assert "--retry-path-confirmed" in cmd


def test_memorial_room_audio_clean_materializer_copies_expected_artifacts(tmp_path) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_room_audio_receipt_clean.py", "materialize_memorial_room_audio_receipt_clean_copy")
    clean_root = tmp_path / "clean"
    dest_root = tmp_path / "dest"
    for relpath in module.SYNC_ARTIFACTS:
        path = clean_root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    copied = module._copy_artifacts_from_clean_clone(clean_root, dest_root)

    assert set(copied) == {path.as_posix() for path in module.SYNC_ARTIFACTS}
    for relpath in module.SYNC_ARTIFACTS:
        assert (dest_root / relpath).read_text(encoding="utf-8") == "{}"


def test_memorial_public_gold_clean_materializer_builds_expected_commands() -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_public_gold_clean.py", "materialize_memorial_public_gold_clean")

    class _Args:
        python_bin = "python3"
        base_url = "https://example.com"
        slug = "manfred"
        reviewer = "reviewer"
        device_label = "laptop"
        speaker_label = "speaker"
        room_label = "office"
        notes = "ok"
        manual_attestation_id = "room-review-001"
        manual_attestation_signed_at = "2026-06-18T12:00:00Z"
        manual_attestation_source = "operator_room_review"
        direct_min_f1 = 0.92
        conversation_min_f1 = 0.90
        browser_first_answer_ms = 4500.0
        meaningful_browser_first_answer_ms = 8000.0
        meaningful_prompt = "Was war dir bei Gerechtigkeit wichtig?"

    local_voice = module.build_local_voice_receipt_command(_Args())
    voice = module.build_voice_receipt_command(_Args())
    browser = module.build_browser_receipt_command(_Args())
    meaningful = module.build_meaningful_browser_receipt_command(_Args())
    room = module.build_room_receipt_command(_Args())

    assert local_voice[:2] == ["python3", "scripts/materialize_memorial_voice_roundtrip_exit_gate.py"]
    assert ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json" in local_voice
    assert voice[:2] == ["python3", "scripts/materialize_memorial_voice_roundtrip_exit_gate.py"]
    assert "--gold-mode" in voice
    assert "--require-public-origin" in voice
    assert "https://example.com" in voice
    assert browser[:2] == ["python3", "scripts/measure_memorial_live_browser.py"]
    assert "--real-stt" in browser
    assert "--max-first-answer-ms" in browser
    assert meaningful[:2] == ["python3", "scripts/measure_memorial_live_browser.py"]
    assert "--text-prompt" in meaningful
    assert "Was war dir bei Gerechtigkeit wichtig?" in meaningful
    assert room[:2] == ["python3", "scripts/materialize_memorial_room_audio_receipt.py"]
    assert "--reviewer" in room
    assert "reviewer" in room
    assert "--manual-attestation-id" in room
    assert "room-review-001" in room
    assert "--normal-spoken-turn-confirmed" in room
    assert "--interruption-behavior-confirmed" in room
    assert "--retry-path-confirmed" in room


def test_memorial_public_gold_clean_materializer_copies_expected_artifacts(tmp_path) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_public_gold_clean.py", "materialize_memorial_public_gold_clean_copy")
    clean_root = tmp_path / "clean"
    dest_root = tmp_path / "dest"
    for relpath in module.SYNC_ARTIFACTS:
        path = clean_root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    copied = module._copy_artifacts_from_clean_clone(clean_root, dest_root)

    assert set(copied) == {path.as_posix() for path in module.SYNC_ARTIFACTS}
    for relpath in module.SYNC_ARTIFACTS:
        assert (dest_root / relpath).read_text(encoding="utf-8") == "{}"


def test_memorial_receipt_materializers_use_source_state_head(monkeypatch) -> None:
    voice = _load_module(
        "/docker/EA/scripts/materialize_memorial_voice_roundtrip_exit_gate.py",
        "materialize_memorial_voice_roundtrip_exit_gate_source_head",
    )
    browser = _load_module(
        "/docker/EA/scripts/measure_memorial_live_browser.py",
        "measure_memorial_live_browser_source_head",
    )
    room = _load_module(
        "/docker/EA/scripts/materialize_memorial_room_audio_receipt.py",
        "materialize_memorial_room_audio_receipt_source_head",
    )

    monkeypatch.setattr(voice, "resolve_source_state_head", lambda root: "SOURCE_HEAD")
    monkeypatch.setattr(browser, "resolve_source_state_head", lambda root: "SOURCE_HEAD")
    monkeypatch.setattr(room, "resolve_source_state_head", lambda root: "SOURCE_HEAD")

    assert voice._git_head() == "SOURCE_HEAD"
    assert browser._git_head() == "SOURCE_HEAD"
    assert room._git_head() == "SOURCE_HEAD"
