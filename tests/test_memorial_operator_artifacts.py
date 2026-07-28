from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(path_str: str, name: str):
    path = Path(path_str)
    try:
        path = REPO_ROOT / path.relative_to("/docker/EA")
    except ValueError:
        pass
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
                "receipt_command_template": "MEMORIAL_ROOM_REVIEWER=<actual-listener> make materialize-memorial-room-audio-gold-clean",
                "required_env": {"MEMORIAL_ROOM_REVIEWER": "actual listener/operator name"},
                "required_cli_flags": ["--normal-spoken-turn-confirmed"],
                "required_checks": [{"id": "normal_spoken_turn_confirmed", "cli_flag": "--normal-spoken-turn-confirmed"}],
                "operator_steps": ["Use a non-generic reviewer label."],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOM_AUDIO_ATTESTATION_PACKET", room_attestation_packet)
    room_receipt = tmp_path / "room-audio.json"
    room_receipt.write_text(
        json.dumps(
            {
                "status": "fail",
                "reviewer": "Operator A",
                "device_label": "Memorial iPad",
                "speaker_label": "Gallery speaker",
                "room_label": "Front room",
                "checks": {
                    "actual_device_checked": True,
                    "normal_spoken_turn_confirmed": False,
                    "interruption_behavior_confirmed": False,
                    "retry_path_confirmed": False,
                },
                "check_requirements": {
                    "normal_spoken_turn_confirmed": "A normal spoken question completed as microphone capture, STT, answer, TTS, and playback.",
                    "interruption_behavior_confirmed": "Intentional interruption or barge-in behavior was observed and was not harsh or confusing.",
                    "retry_path_confirmed": "The tester observed a clear retry/recovery path after an acoustic or turn-taking problem.",
                },
                "failed_codes": [
                    "normal_spoken_turn_confirmed_missing",
                    "interruption_behavior_confirmed_missing",
                    "retry_path_confirmed_missing",
                ],
                "manual_attestation": {"source": "operator_room_review"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOM_AUDIO_RECEIPT", room_receipt)
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
    release_authority_status = tmp_path / "release-authority-status.json"
    release_authority_status.write_text(
        json.dumps(
            {
                "state": "watch",
                "authority_posture": "local_only_deploy_id",
                "summary": "Release authority is present but still has gaps to resolve.",
                "issues": ["deployment_id_local_fallback", "dirty_worktree"],
                "next_action": "Deploy from a clean committed tree with an explicit deployment ID from the real deploy system, then rematerialize the release manifest.",
                "dirty_worktree": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "RELEASE_AUTHORITY_STATUS", release_authority_status)
    monkeypatch.setattr(
        module,
        "_run_json",
        lambda script: (
            {
                "memorial_voice_gold_claim_allowed": False,
                "local_release_issues": [],
                "public_gold_issues": ["receipt_missing_or_invalid"],
                "public_browser_gold_issues": ["browser_receipt_missing_or_invalid"],
                "public_meaningful_browser_gold_issues": [],
                "memorial_surface_contract_issues": ["memorial_surface_contract_status_not_pass"],
                "room_audio_issues": ["room_receipt_missing_or_invalid"],
                "next_action": "refresh_memorial_public_auto_receipts_clean",
                "blocker_summary": {
                    "blocked_component_keys": [
                        "public_voice_receipt",
                        "public_browser_receipt",
                        "memorial_surface_contract",
                        "room_audio_receipt",
                    ],
                    "blocked_count": 4,
                },
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "blocked"}
        ),
    )
    monkeypatch.setattr(
        module,
        "_public_origin_access_status",
        lambda *, slug: {
            "status": "access_blocked",
            "base_url": "https://myexternalbrain.com",
            "source_key": "EA_PUBLIC_APP_BASE_URL",
            "page_status_code": 403,
            "manifest_status_code": 403,
            "next_action": "allow_anonymous_public_memorial_origin_access",
            "reason": "public_origin_access_blocked",
        },
    )
    monkeypatch.setattr(
        module,
        "_memorial_public_runtime_status",
        lambda: {
            "status": "blocked",
            "project_mode": "EA_CORE",
            "enabled_project_modes": ["EA_CORE"],
            "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
            "compose_overrides": [],
            "public_origin": "https://myexternalbrain.com",
            "next_action": "deploy_ea_memorial",
            "reason": "public_origin_not_deployed_in_memorial_mode",
        },
    )
    assert module.main(
        [
            "--output",
            str(tmp_path / "operator_status.json"),
            "--release-authority-status",
            str(release_authority_status),
        ]
    ) == 0
    payload = __import__("json").loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["current_label"] == "Memorial flagship experience gold: blocked"
    assert payload["public_voice_gold"] == "blocked"
    assert payload["flagship_experience_gold"] == "blocked"
    assert payload["local_release_candidate"] == "pass"
    assert payload["public_voice_receipt"] == "missing_or_blocked"
    assert payload["public_browser_meaningful_receipt"] == "missing_or_blocked"
    assert payload["public_runtime_mode"] == "blocked"
    assert payload["public_origin_access"] == "access_blocked"
    assert payload["memorial_surface_contract"] == "missing_or_blocked"
    assert payload["whole_project_gold"] == "blocked"
    assert payload["memorial_public_gold_next_action"] == "clear_release_authority_for_memorial_deploy"
    assert payload["memorial_public_gold_next_command"] == "python3 scripts/verify_release_authority.py --pretty"
    assert payload["memorial_public_gold_blocker_summary"]["blocked_count"] == 6
    assert payload["memorial_public_gold_blocker_summary"]["blocked_component_keys"] == [
        "public_voice_receipt",
        "public_browser_receipt",
        "memorial_surface_contract",
        "room_audio_receipt",
        "public_runtime_mode",
        "release_authority",
    ]
    blocked_components = {
        str(item["key"]): dict(item)
        for item in payload["memorial_public_gold_blocker_summary"]["blocked_components"]
    }
    assert blocked_components["public_runtime_mode"]["issues"] == ["public_origin_not_deployed_in_memorial_mode"]
    assert blocked_components["public_runtime_mode"]["code"] == "public_runtime_mode"
    assert blocked_components["public_runtime_mode"]["component"] == "Public runtime mode"
    assert blocked_components["public_runtime_mode"]["next_action"] == "deploy_ea_memorial"
    assert blocked_components["release_authority"]["issues"] == ["deployment_id_local_fallback", "dirty_worktree"]
    assert blocked_components["release_authority"]["code"] == "release_authority"
    assert blocked_components["release_authority"]["component"] == "Release authority"
    assert blocked_components["release_authority"]["next_action"] == "clear_release_authority_for_memorial_deploy"
    assert payload["artifact_paths"]["public_auto_receipts_clean"] == "scripts/materialize_memorial_public_auto_receipts_clean.py"
    assert payload["artifact_paths"]["public_memorial_deploy"] == "make deploy-ea-memorial"
    assert payload["artifact_paths"]["release_authority_probe"] == "python3 scripts/verify_release_authority.py --pretty"
    assert payload["artifact_paths"]["release_authority_status"] == str(release_authority_status)
    assert payload["artifact_paths"]["public_origin_probe"] == "GET /memorials/manfred and /memorials/manfred.json on the configured public origin"
    assert payload["release_authority"]["status"] == "blocked"
    assert payload["release_authority"]["authority_posture"] == "local_only_deploy_id"
    assert payload["release_authority"]["issues"] == ["deployment_id_local_fallback", "dirty_worktree"]
    assert payload["whole_project_map_summary"]["blocking_planes"] == ["memorial_public_origin_gold"]
    assert payload["artifact_paths"]["room_audio_attestation_packet"] == str(room_attestation_packet)
    assert payload["room_audio_attestation_packet"]["status"] == "ready"
    assert payload["room_audio_attestation_packet"]["manual_only"] is True
    assert payload["room_audio_attestation_packet"]["ci_must_not_auto_assert"] is True
    assert payload["room_audio_attestation_packet"]["next_action"] == "collect_real_room_audio_attestation"
    assert payload["room_audio_attestation_packet"]["receipt_command_template"]
    assert payload["room_audio_attestation_packet"]["required_check_ids"] == ["normal_spoken_turn_confirmed"]
    assert payload["room_audio_attestation_packet"]["required_env"]
    assert payload["room_audio_attestation_packet"]["operator_steps"]
    assert payload["room_audio_receipt_detail"]["status"] == "fail"
    assert payload["room_audio_receipt_detail"]["missing_check_ids"] == [
        "normal_spoken_turn_confirmed",
        "interruption_behavior_confirmed",
        "retry_path_confirmed",
    ]
    assert payload["room_audio_receipt_detail"]["failed_codes"] == [
        "normal_spoken_turn_confirmed_missing",
        "interruption_behavior_confirmed_missing",
        "retry_path_confirmed_missing",
    ]
    missing_hint_names = {
        item["name"]
        for item in payload["room_audio_receipt_detail"]["missing_input_hints"]
    }
    assert "--normal-spoken-turn-confirmed" in missing_hint_names
    assert "--interruption-behavior-confirmed" in missing_hint_names
    assert "--retry-path-confirmed" in missing_hint_names
    assert payload["room_audio_receipt_detail"]["next_action"] == "collect_real_room_audio_attestation"
    assert payload["artifact_paths"]["memorial_surface_contract"] == "scripts/verify_project_mode_runtime.py --mode memorial"
    assert payload["memorial_surface_contract_detail"]["status"] == "blocked"
    assert payload["public_runtime_mode_detail"]["reason"] == "public_origin_not_deployed_in_memorial_mode"
    assert payload["public_origin_access_detail"]["reason"] == "public_origin_access_blocked"


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
                "public_meaningful_browser_gold_issues": [],
                    "memorial_surface_contract_issues": [],
                    "room_audio_issues": [],
                    "public_spatial_tour_issues": [],
                    "public_spatial_tour_receipt": ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json",
                    "next_action": "maintain_memorial_public_origin_gold",
                "blocker_summary": {"blocked_component_keys": [], "blocked_count": 0},
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "pass"}
        ),
    )
    monkeypatch.setattr(
        module,
        "_public_origin_access_status",
        lambda *, slug: {
            "status": "pass",
            "base_url": "https://memorial.example.test",
            "source_key": "EA_PUBLIC_APP_BASE_URL",
            "page_status_code": 200,
            "manifest_status_code": 200,
            "next_action": "maintain_public_memorial_origin_access",
        },
    )
    monkeypatch.setattr(
        module,
        "_memorial_public_runtime_status",
        lambda: {
            "status": "pass",
            "project_mode": "MEMORIAL",
            "enabled_project_modes": ["MEMORIAL"],
            "compose_files": ["docker-compose.yml", "docker-compose.prod.yml", "docker-compose.memorial.yml"],
            "compose_overrides": ["docker-compose.memorial.yml"],
            "public_origin": "https://memorial.example.test",
            "next_action": "maintain_memorial_public_runtime",
            "reason": "memorial_runtime_declared",
        },
    )
    assert module.main(["--output", str(tmp_path / "operator_status.json")]) == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["whole_project_gold"] == "pass"
    assert payload["public_browser_meaningful_receipt"] == "pass"
    assert payload["public_runtime_mode"] == "pass"
    assert payload["public_origin_access"] == "pass"
    assert payload["memorial_surface_contract"] == "pass"
    assert payload["status"] == "pass"
    assert payload["memorial_public_gold_next_action"] == "maintain_memorial_public_origin_gold"
    assert payload["memorial_public_gold_blocker_summary"]["blocked_count"] == 0
    assert payload["artifact_paths"]["public_gold_receipt"] == ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"
    assert payload["workflow_backing"]["status"] == "no"
    assert payload["memorial_surface_contract_detail"]["status"] == "pass"
    assert payload["public_voice_receipt_semantics"]["label"] in {
        "Memorial public voice provenance proof",
        "Memorial public voice gold proof",
    }
    assert payload["public_origin_access_detail"]["next_action"] == "maintain_public_memorial_origin_access"
    assert payload["public_runtime_mode_detail"]["next_action"] == "maintain_memorial_public_runtime"


def test_memorial_operator_status_public_origin_access_status_reports_blocked_http(monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_public_origin_access",
    )
    monkeypatch.setattr(module, "_configured_public_origin", lambda: ("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com"))
    responses = {
        "https://myexternalbrain.com/memorials/manfred": (403, "Forbidden"),
        "https://myexternalbrain.com/memorials/manfred.json": (403, "Forbidden"),
    }
    monkeypatch.setattr(module, "_http_status", lambda url: responses[url])

    status = module._public_origin_access_status(slug="manfred")

    assert status["status"] == "access_blocked"
    assert status["reason"] == "public_origin_access_blocked"
    assert status["next_action"] == "allow_anonymous_public_memorial_origin_access"
    assert status["page_status_code"] == 403
    assert status["manifest_status_code"] == 403


def test_memorial_operator_status_public_runtime_status_reports_ea_core_only(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_public_runtime_mode",
    )
    deploy_context = tmp_path / "deploy_context.json"
    release_manifest = tmp_path / "release_manifest.json"
    deploy_context.write_text(
        json.dumps(
            {
                "project_mode": "EA_CORE",
                "enabled_project_modes": ["EA_CORE"],
                "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
                "compose_overrides": [],
                "public_origin": "https://myexternalbrain.com",
            }
        ),
        encoding="utf-8",
    )
    release_manifest.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(module, "DEPLOY_CONTEXT", deploy_context)
    monkeypatch.setattr(module, "RELEASE_MANIFEST", release_manifest)

    status = module._memorial_public_runtime_status()

    assert status["status"] == "blocked"
    assert status["reason"] == "public_origin_not_deployed_in_memorial_mode"
    assert status["next_action"] == "deploy_ea_memorial"


def test_memorial_operator_status_public_origin_access_status_reports_not_found(monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_public_origin_not_found",
    )
    monkeypatch.setattr(module, "_configured_public_origin", lambda: ("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com"))
    responses = {
        "https://myexternalbrain.com/memorials/manfred": (404, '{"detail":"Not Found"}'),
        "https://myexternalbrain.com/memorials/manfred.json": (404, '{"detail":"Not Found"}'),
    }
    monkeypatch.setattr(module, "_http_status", lambda url: responses[url])

    status = module._public_origin_access_status(slug="manfred")

    assert status["status"] == "blocked"
    assert status["reason"] == "public_origin_memorial_not_found"
    assert status["next_action"] == "republish_public_memorial_bundle_or_fix_slug"
    assert status["page_status_code"] == 404
    assert status["manifest_status_code"] == 404


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


def test_room_audio_receipt_detail_maps_failed_codes_to_operator_inputs(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_room_failed_input_hints",
    )
    receipt = tmp_path / "room-audio.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "fail",
                "checks": {
                    "normal_spoken_turn_confirmed": False,
                    "retry_path_confirmed": False,
                },
                "check_requirements": {
                    "normal_spoken_turn_confirmed": "Normal turn completed.",
                    "retry_path_confirmed": "Retry path clear.",
                },
                "failed_codes": [
                    "normal_spoken_turn_confirmed_missing",
                    "retry_path_confirmed_missing",
                    "reviewer_generic",
                    "device_label_generic",
                    "notes_missing",
                    "manual_attestation_id_missing",
                    "manual_attestation_signed_at_missing",
                    "dirty_worktree",
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOM_AUDIO_RECEIPT", receipt)

    detail = module._room_audio_receipt_detail()

    hints = {(item["code"], item["kind"], item["name"]) for item in detail["missing_input_hints"]}
    assert ("normal_spoken_turn_confirmed_missing", "cli_flag", "--normal-spoken-turn-confirmed") in hints
    assert ("retry_path_confirmed_missing", "cli_flag", "--retry-path-confirmed") in hints
    assert ("reviewer_generic", "env", "MEMORIAL_ROOM_REVIEWER") in hints
    assert ("device_label_generic", "env", "MEMORIAL_ROOM_DEVICE_LABEL") in hints
    assert ("notes_missing", "env", "MEMORIAL_ROOM_NOTES") in hints
    assert ("manual_attestation_id_missing", "env", "MEMORIAL_ROOM_ATTESTATION_ID") in hints
    assert ("manual_attestation_signed_at_missing", "env", "MEMORIAL_ROOM_ATTESTATION_SIGNED_AT") in hints
    assert ("dirty_worktree", "source", "source_worktree") in hints


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
                "public_spatial_tour_issues": [],
                "public_spatial_tour_receipt": ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json",
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "pass"}
        ),
    )

    assert module.main(["--output", str(tmp_path / "operator_status.json")]) == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["current_label"] == "Memorial flagship experience gold: pass"
    assert payload["public_voice_gold"] == "pass"
    assert payload["flagship_experience_gold"] == "pass"
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
                "public_spatial_tour_issues": [],
                "public_spatial_tour_receipt": ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json",
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "blocked", "issues": ["whole-project gold map is stale relative to current HEAD"]}
        ),
    )

    assert module.main(["--output", str(tmp_path / "operator_status.json")]) == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["whole_project_gold"] == "blocked"
    assert payload["current_label"] == "Memorial flagship experience gold: pass"
    assert payload["public_voice_gold"] == "pass"
    assert payload["flagship_experience_gold"] == "pass"
    assert payload["status"] == "pass"


def _stub_public_memorial_projection_pass(module, monkeypatch) -> None:
    monkeypatch.setattr(
        module,
        "_memorial_public_runtime_status",
        lambda: {"status": "pass"},
    )
    monkeypatch.setattr(
        module,
        "_public_origin_access_status",
        lambda *, slug: {"status": "pass"},
    )


def test_memorial_operator_status_uses_source_state_head(tmp_path, monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_operator_status.py", "materialize_memorial_operator_status_source_head")
    _stub_public_memorial_projection_pass(module, monkeypatch)
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "operator_status.json")
    monkeypatch.setattr(module, "resolve_source_state_head", lambda root: "SOURCE_HEAD")
    monkeypatch.setattr(
        module,
        "source_worktree_metadata",
        lambda root, **kwargs: {
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
                "status": "blocked",
                "memorial_voice_gold_claim_allowed": False,
                "local_release_issues": ["receipt_stale_relative_to_current_head"],
                "public_gold_issues": ["receipt_stale_relative_to_current_head"],
                "public_browser_gold_issues": ["browser_receipt_stale_relative_to_current_head"],
                "public_meaningful_browser_gold_issues": [],
                "memorial_surface_contract_issues": [],
                "room_audio_issues": [],
                "next_action": "refresh_memorial_public_auto_receipts_clean",
                "next_command": "scripts/materialize_memorial_public_auto_receipts_clean.py",
                "blocker_summary": {
                    "blocked_component_keys": ["local_release_receipt"],
                    "blocked_components": [
                        {
                            "key": "local_release_receipt",
                            "label": "Local release receipt",
                            "issues": ["receipt_stale_relative_to_current_head"],
                            "next_action": "refresh_local_memorial_voice_receipt",
                        }
                    ],
                    "blocked_count": 1,
                },
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "pass"}
        ),
    )

    assert module.main(["--output", str(tmp_path / "operator_status.json")]) == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["source_git_head"] == "SOURCE_HEAD"
    assert payload["source_worktree_dirty"] is False
    assert payload["source_dirty_count"] == 0
    assert payload["memorial_public_gold_next_action"] == "refresh_memorial_public_auto_receipts_clean"
    assert payload["memorial_public_gold_next_command"] == "scripts/materialize_memorial_public_auto_receipts_clean.py"


def test_memorial_operator_status_reports_dirty_source_snapshot(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_dirty_source",
    )
    _stub_public_memorial_projection_pass(module, monkeypatch)
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "operator_status.json")
    monkeypatch.setattr(module, "resolve_source_state_head", lambda root: "SOURCE_HEAD")
    source_metadata_calls: list[dict[str, object]] = []

    def _source_metadata(root, **kwargs):
        source_metadata_calls.append(dict(kwargs))
        return {
            "source_worktree_dirty": True,
            "source_dirty_count": 2,
            "source_dirty_files": ["ea/app/api/routes/public_memorials.py", "ea/app/services/memorial_openvoice.py"],
            "source_dirty_omitted_count": 1,
            "source_dirty_status_sha256": "dirty-sha",
        }

    monkeypatch.setattr(module, "source_worktree_metadata", _source_metadata)
    monkeypatch.setattr(
        module,
        "_run_json",
        lambda script: (
            {
                "status": "blocked",
                "memorial_voice_gold_claim_allowed": False,
                "local_release_issues": ["receipt_stale_relative_to_current_head"],
                "public_gold_issues": ["receipt_stale_relative_to_current_head"],
                "public_browser_gold_issues": ["browser_receipt_stale_relative_to_current_head"],
                "public_meaningful_browser_gold_issues": [],
                "memorial_surface_contract_issues": [],
                "room_audio_issues": [],
                "next_action": "refresh_memorial_public_auto_receipts_clean",
                "source_dirty_verifier": {
                    "contract_name": "ea.source_dirty_groups_verifier.v1",
                    "status": "pass",
                    "issues": [],
                    "source_dirty_count": 2,
                    "category_count": 2,
                },
                "blocker_summary": {
                    "blocked_component_keys": ["local_release_receipt"],
                    "blocked_components": [
                        {
                            "key": "local_release_receipt",
                            "label": "Local release receipt",
                            "issues": ["receipt_stale_relative_to_current_head"],
                            "next_action": "refresh_local_memorial_voice_receipt",
                        }
                    ],
                    "blocked_count": 1,
                },
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "pass"}
        ),
    )

    assert module.main(["--output", str(tmp_path / "operator_status.json")]) == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))
    assert payload["source_git_head"] == "SOURCE_HEAD"
    assert payload["source_worktree_dirty"] is True
    assert payload["source_dirty_count"] == 2
    assert source_metadata_calls == [{"dirty_path_limit": module.SOURCE_DIRTY_FILE_LIMIT}]
    assert payload["source_dirty_files"] == ["ea/app/api/routes/public_memorials.py", "ea/app/services/memorial_openvoice.py"]
    assert payload["source_dirty_omitted_count"] == 1
    assert payload["source_dirty_status_sha256"] == "dirty-sha"
    assert payload["source_dirty_summary"]["status"] == "dirty"
    assert payload["source_dirty_summary"]["total_count"] == 2
    assert payload["source_dirty_summary"]["omitted_count"] == 1
    assert payload["source_dirty_summary"]["recommended_first_action"] == "review_and_commit_or_stash_source_groups_before_clean_receipts"
    assert payload["source_dirty_verifier"]["contract_name"] == "ea.source_dirty_groups_verifier.v1"
    assert payload["source_dirty_verifier"]["status"] == "pass"
    assert payload["source_dirty_verifier"]["issues"] == []
    assert payload["source_cleanup"]["status"] == "blocked"
    assert payload["source_cleanup"]["source_dirty_count"] == 2
    assert payload["source_cleanup"]["verifier_status"] == "pass"
    assert payload["source_cleanup"]["next_action"] == "commit_or_stash_source_changes_before_clean_receipts"
    assert payload["source_cleanup"]["next_command"] == "scripts/inspect_source_dirty_groups.py --list-categories"
    assert payload["source_cleanup"]["top_categories"] == [
        {
            "category": "api_routes",
            "visible_count": 1,
            "drilldown_command": "scripts/inspect_source_dirty_groups.py --category api_routes --limit 20",
        },
        {
            "category": "services",
            "visible_count": 1,
            "drilldown_command": "scripts/inspect_source_dirty_groups.py --category services --limit 20",
        },
    ]
    assert payload["source_cleanup"]["handoff_commands"] == [
        "git status --short",
        "scripts/inspect_source_dirty_groups.py --list-categories",
        "scripts/inspect_source_dirty_groups.py --category api_routes --limit 20",
        "scripts/inspect_source_dirty_groups.py --category services --limit 20",
    ]
    groups = {
        item["category"]: item
        for item in payload["source_dirty_summary"]["categories"]
    }
    assert groups["api_routes"]["sample_files"] == ["ea/app/api/routes/public_memorials.py"]
    assert groups["services"]["sample_files"] == ["ea/app/services/memorial_openvoice.py"]
    assert payload["memorial_public_gold_next_action"] == "commit_or_stash_source_changes_before_clean_receipts"
    assert payload["memorial_public_gold_next_command"] == "scripts/inspect_source_dirty_groups.py --list-categories"
    assert "source_worktree" in payload["memorial_public_gold_blocker_summary"]["blocked_component_keys"]
    source_blocker = {
        item["key"]: item
        for item in payload["memorial_public_gold_blocker_summary"]["blocked_components"]
    }["source_worktree"]
    assert source_blocker["issues"] == ["source_worktree_dirty"]
    assert source_blocker["next_action"] == "commit_or_stash_source_changes_before_clean_receipts"
    assert source_blocker["next_command"] == "scripts/inspect_source_dirty_groups.py --list-categories"
    assert "scripts/inspect_source_dirty_groups.py --list-categories" in payload["memorial_public_gold_blocker_summary"]["blocked_commands"]
    assert any("must not be used as final release evidence" in note for note in payload["operator_notes"])
    assert any("make verify-source-dirty-groups" in note for note in payload["operator_notes"])
    assert any("clean-clone receipt refresh intentionally refuses dirty source inputs" in note for note in payload["operator_notes"])
    assert any("Use source_dirty_summary" in note for note in payload["operator_notes"])


def test_memorial_operator_status_routes_dirty_source_to_verifier_when_verifier_blocks(tmp_path, monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_dirty_source_verifier_blocked",
    )
    _stub_public_memorial_projection_pass(module, monkeypatch)
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "operator_status.json")
    monkeypatch.setattr(module, "resolve_source_state_head", lambda root: "SOURCE_HEAD")
    monkeypatch.setattr(
        module,
        "source_worktree_metadata",
        lambda root, **kwargs: {
            "source_worktree_dirty": True,
            "source_dirty_count": 1,
            "source_dirty_files": ["ea/app/services/memorial_openvoice.py"],
            "source_dirty_omitted_count": 0,
            "source_dirty_status_sha256": "dirty-sha",
        },
    )
    monkeypatch.setattr(
        module,
        "_run_json",
        lambda script: (
            {
                "status": "blocked",
                "memorial_voice_gold_claim_allowed": False,
                "local_release_issues": ["receipt_stale_relative_to_current_head"],
                "public_gold_issues": ["receipt_stale_relative_to_current_head"],
                "public_browser_gold_issues": ["browser_receipt_stale_relative_to_current_head"],
                "public_meaningful_browser_gold_issues": [],
                "memorial_surface_contract_issues": [],
                "room_audio_issues": [],
                "next_action": "refresh_memorial_public_auto_receipts_clean",
                "source_dirty_verifier": {
                    "contract_name": "ea.source_dirty_groups_verifier.v1",
                    "status": "blocked",
                    "issues": ["visible_category_total_mismatch"],
                    "source_dirty_count": 1,
                    "category_count": 1,
                },
                "blocker_summary": {
                    "blocked_component_keys": ["local_release_receipt"],
                    "blocked_components": [
                        {
                            "key": "local_release_receipt",
                            "label": "Local release receipt",
                            "issues": ["receipt_stale_relative_to_current_head"],
                            "next_action": "refresh_local_memorial_voice_receipt",
                        }
                    ],
                    "blocked_count": 1,
                },
            }
            if "verify_memorial_gold_readiness" in script
            else {"status": "pass"}
        ),
    )

    assert module.main(["--output", str(tmp_path / "operator_status.json")]) == 0
    payload = json.loads((tmp_path / "operator_status.json").read_text(encoding="utf-8"))

    assert payload["source_dirty_verifier"]["status"] == "blocked"
    assert payload["source_cleanup"]["status"] == "verifier_blocked"
    assert payload["source_cleanup"]["verifier_status"] == "blocked"
    assert payload["source_cleanup"]["verifier_issues"] == ["visible_category_total_mismatch"]
    assert payload["source_cleanup"]["next_action"] == "verify_source_dirty_groups_before_source_cleanup"
    assert payload["source_cleanup"]["next_command"] == "make verify-source-dirty-groups"
    assert "make verify-source-dirty-groups" in payload["source_cleanup"]["handoff_commands"]
    assert payload["memorial_public_gold_next_action"] == "verify_source_dirty_groups_before_source_cleanup"
    assert payload["memorial_public_gold_next_command"] == "make verify-source-dirty-groups"
    source_blocker = {
        item["key"]: item
        for item in payload["memorial_public_gold_blocker_summary"]["blocked_components"]
    }["source_worktree"]
    assert source_blocker["issues"] == [
        "source_worktree_dirty",
        "source_dirty_group_verifier_failed",
    ]


def test_memorial_operator_status_source_dirty_summary_groups_common_paths() -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_operator_status.py",
        "materialize_memorial_operator_status_dirty_summary",
    )

    summary = module._source_dirty_summary(
        {
            "source_worktree_dirty": True,
            "source_dirty_count": 6,
            "source_dirty_files": [
                "ea/app/api/routes/public_memorials.py",
                "ea/app/services/memorial_openvoice.py",
                "scripts/materialize_memorial_operator_status.py",
                "docker-compose.yml",
                "docs-public/executive-assistant/index.mdx",
                "README.md",
            ],
            "source_dirty_omitted_count": 4,
        }
    )

    assert summary["status"] == "dirty"
    assert summary["visible_count"] == 6
    assert summary["omitted_count"] == 4
    categories = [item["category"] for item in summary["categories"]]
    assert categories[:4] == ["api_routes", "services", "scripts", "deploy_runtime"]
    by_category = {item["category"]: item for item in summary["categories"]}
    assert by_category["public_docs"]["sample_files"] == ["docs-public/executive-assistant/index.mdx"]
    assert by_category["docs"]["sample_files"] == ["README.md"]
    assert summary["operator_hint"].startswith("Start with api_routes/services/scripts/deploy_runtime")


def test_inspect_source_dirty_groups_builds_operator_report(monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/inspect_source_dirty_groups.py",
        "inspect_source_dirty_groups_report",
    )

    def _source_metadata(root, *, dirty_path_limit):
        assert dirty_path_limit == module.FULL_DIRTY_SCAN_LIMIT
        return {
            "source_worktree_dirty": True,
            "source_dirty_count": 3,
            "source_dirty_files": [
                "ea/app/api/routes/public_memorials.py",
                "ea/app/services/memorial_openvoice.py",
                "scripts/deploy.sh",
            ],
            "source_dirty_omitted_count": 2,
            "source_dirty_status_sha256": "dirty-sha",
        }

    monkeypatch.setattr(module, "source_worktree_metadata", _source_metadata)

    report = module.build_report(root=Path("/tmp/ea"), dirty_path_limit=1)
    text = module.format_text(report)
    category_text = module.format_category_list(report)

    assert report["contract_name"] == "ea.source_dirty_groups.v1"
    assert report["status"] == "dirty"
    assert report["source_dirty_summary"]["total_count"] == 3
    assert [item["category"] for item in report["source_dirty_summary"]["categories"]] == [
        "api_routes",
        "services",
        "scripts",
    ]
    assert report["source_dirty_summary"]["sample_limit_per_category"] == 1
    assert report["priority_groups"] == [
        {
            "category": "api_routes",
            "visible_count": 1,
            "reason": "runtime and public-route behavior can invalidate public receipts",
            "drilldown_command": "scripts/inspect_source_dirty_groups.py --category api_routes --limit 20",
        },
        {
            "category": "services",
            "visible_count": 1,
            "reason": "provider, audio, and runtime services can invalidate latency or speech receipts",
            "drilldown_command": "scripts/inspect_source_dirty_groups.py --category services --limit 20",
        },
        {
            "category": "scripts",
            "visible_count": 1,
            "reason": "materializers and verifiers can invalidate operator evidence",
            "drilldown_command": "scripts/inspect_source_dirty_groups.py --category scripts --limit 20",
        },
    ]
    assert "git status --short" in report["recommended_commands"]
    assert "scripts/inspect_source_dirty_groups.py --list-categories" in report["recommended_commands"]
    assert "scripts/inspect_source_dirty_groups.py --category <category> --limit 20" in report["recommended_commands"]
    assert "make materialize-memorial-public-auto-receipts-clean" in report["recommended_commands"]
    assert report["category_drilldown_commands"] == [
        "scripts/inspect_source_dirty_groups.py --category api_routes --limit 20",
        "scripts/inspect_source_dirty_groups.py --category services --limit 20",
        "scripts/inspect_source_dirty_groups.py --category scripts --limit 20",
    ]
    first_category = report["source_dirty_summary"]["categories"][0]
    assert first_category["drilldown_command"] == "scripts/inspect_source_dirty_groups.py --category api_routes --limit 20"
    assert "source worktree: dirty" in text
    assert "category filter: none" in text
    assert "priority groups:" in text
    assert "- api_routes: 1 (runtime and public-route behavior can invalidate public receipts) -> scripts/inspect_source_dirty_groups.py --category api_routes --limit 20" in text
    assert (
        "- api_routes: 1 -> ea/app/api/routes/public_memorials.py "
        "(scripts/inspect_source_dirty_groups.py --category api_routes --limit 20)"
    ) in text
    assert "dirty omitted:   2" in text
    assert "categories:" in category_text
    assert "priority groups: api_routes, services, scripts" in category_text
    assert "- api_routes: 1 -> scripts/inspect_source_dirty_groups.py --category api_routes --limit 20" in category_text
    assert "- services: 1 -> scripts/inspect_source_dirty_groups.py --category services --limit 20" in category_text
    assert "scripts/inspect_source_dirty_groups.py --category <category> --limit 20" in category_text

    service_report = module.build_report(root=Path("/tmp/ea"), dirty_path_limit=1, category="services")
    service_text = module.format_text(service_report)

    assert service_report["category_filter"] == "services"
    assert service_report["source_dirty_summary"]["category_count"] == 1
    assert service_report["source_dirty_summary"]["visible_count"] == 1
    assert [item["category"] for item in service_report["source_dirty_summary"]["categories"]] == ["services"]
    assert "category filter: services" in service_text
    assert (
        "- services: 1 -> ea/app/services/memorial_openvoice.py "
        "(scripts/inspect_source_dirty_groups.py --category services --limit 20)"
    ) in service_text
    assert "- api_routes:" not in service_text


def test_verify_source_dirty_groups_accepts_coherent_dirty_report(monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/verify_source_dirty_groups.py",
        "verify_source_dirty_groups_report",
    )
    monkeypatch.setattr(
        module,
        "build_report",
        lambda **_kwargs: {
            "contract_name": "ea.source_dirty_groups.v1",
            "status": "dirty",
            "source_worktree": {
                "source_worktree_dirty": True,
                "source_dirty_count": 2,
            },
            "source_dirty_summary": {
                "status": "dirty",
                "total_count": 2,
                "visible_count": 2,
                "categories": [
                    {
                        "category": "api_routes",
                        "visible_count": 1,
                        "drilldown_command": "scripts/inspect_source_dirty_groups.py --category api_routes --limit 20",
                    },
                    {
                        "category": "services",
                        "visible_count": 1,
                        "drilldown_command": "scripts/inspect_source_dirty_groups.py --category services --limit 20",
                    },
                ],
            },
            "recommended_commands": [
                "scripts/inspect_source_dirty_groups.py --list-categories",
                "scripts/inspect_source_dirty_groups.py --category <category> --limit 20",
            ],
            "category_drilldown_commands": [
                "scripts/inspect_source_dirty_groups.py --category api_routes --limit 20",
                "scripts/inspect_source_dirty_groups.py --category services --limit 20",
            ],
            "priority_groups": [
                {
                    "category": "api_routes",
                    "visible_count": 1,
                    "reason": "runtime route",
                    "drilldown_command": "scripts/inspect_source_dirty_groups.py --category api_routes --limit 20",
                },
            ],
        },
    )

    payload = module.build_verification_payload()

    assert payload["contract_name"] == "ea.source_dirty_groups_verifier.v1"
    assert payload["status"] == "pass"
    assert payload["issues"] == []
    assert payload["source_dirty_count"] == 2
    assert payload["category_count"] == 2
    assert payload["priority_group_count"] == 1


def test_verify_source_dirty_groups_blocks_malformed_report(monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/verify_source_dirty_groups.py",
        "verify_source_dirty_groups_malformed_report",
    )
    monkeypatch.setattr(
        module,
        "build_report",
        lambda **_kwargs: {
            "contract_name": "wrong",
            "status": "dirty",
            "source_worktree": {"source_dirty_count": 2},
            "source_dirty_summary": {
                "status": "dirty",
                "total_count": 1,
                "visible_count": 1,
                "categories": [
                    {
                        "category": "api_routes",
                        "visible_count": 1,
                        "drilldown_command": "wrong",
                    }
                ],
            },
            "recommended_commands": [],
            "category_drilldown_commands": [],
        },
    )

    payload = module.build_verification_payload()

    assert payload["status"] == "blocked"
    assert "contract_name_mismatch" in payload["issues"]
    assert "dirty_total_mismatch" in payload["issues"]
    assert "category_drilldown_command_mismatch:api_routes" in payload["issues"]
    assert "list_categories_recommendation_missing" in payload["issues"]


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
        spatial_deploy_receipt = Path("/private/deploy-receipt.json")
        spatial_candidate_browser_receipt = Path("/private/candidate-browser-receipt.json")

    local_voice = module.build_local_voice_receipt_command(_Args())
    voice = module.build_voice_receipt_command(_Args())
    browser = module.build_browser_receipt_command(_Args())
    meaningful = module.build_meaningful_browser_receipt_command(_Args())
    room = module.build_room_receipt_command(_Args())
    spatial = module.build_spatial_receipt_command(_Args())

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
    assert meaningful[meaningful.index("--slug") + 1] == "manfred"
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
    assert spatial == [
        "python3",
        "scripts/materialize_memorial_spatial_tour_public_origin.py",
        "--deploy-receipt",
        "/private/deploy-receipt.json",
        "--candidate-browser-receipt",
        "/private/candidate-browser-receipt.json",
        "--public-base-url",
        "https://example.com",
        "--output",
        ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json",
    ]
    assert module.SYNC_ARTIFACTS.index(
        Path(".codex-studio/published/memorial_spatial_tour_public_origin.generated.json")
    ) < module.SYNC_ARTIFACTS.index(
        Path(".codex-design/product/PROJECT_MODES.generated.json")
    )
    assert module.SYNC_ARTIFACTS.index(
        Path(".codex-design/product/PROJECT_MODES.generated.json")
    ) < module.SYNC_ARTIFACTS.index(
        Path(".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json")
    )
    assert module.SYNC_ARTIFACTS[-1] == Path(
        ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json"
    )


def test_memorial_public_gold_clean_resolves_bare_python_from_path(monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_public_gold_clean.py", "materialize_memorial_public_gold_clean_python")

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/python3" if name == "python3" else None)

    assert module._resolve_python_bin("python3") == "/usr/bin/python3"
    assert module._resolve_python_bin(".venv/bin/python") == str(module.ROOT / ".venv/bin/python")
    assert module._resolve_python_bin("/opt/python/bin/python") == "/opt/python/bin/python"


def test_memorial_public_gold_clean_rejects_dirty_source_worktree(monkeypatch) -> None:
    module = _load_module("/docker/EA/scripts/materialize_memorial_public_gold_clean.py", "materialize_memorial_public_gold_clean_dirty_source")
    monkeypatch.setattr(
        module,
        "source_worktree_metadata",
        lambda root: {
            "source_worktree_dirty": True,
            "source_dirty_count": 2,
            "source_dirty_files": ["ea/app/api/routes/public_memorials.py", "scripts/deploy.sh"],
            "source_dirty_omitted_count": 0,
        },
    )

    try:
        module._assert_source_worktree_clean()
    except SystemExit as exc:
        message = str(exc)
        assert message.startswith("source_worktree_dirty:commit_or_stash_source_changes_before_clean_receipts:")
        assert "count=2" in message
        assert "ea/app/api/routes/public_memorials.py" in message
    else:
        raise AssertionError("expected SystemExit")


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


def test_memorial_public_auto_receipts_clean_builds_expected_commands() -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_public_auto_receipts_clean.py",
        "materialize_memorial_public_auto_receipts_clean",
    )

    class _Args:
        python_bin = "python3"
        base_url = "https://example.com"
        slug = "manfred"
        direct_min_f1 = 0.92
        conversation_min_f1 = 0.90
        browser_first_answer_ms = 4500.0
        meaningful_browser_first_answer_ms = 8000.0
        meaningful_prompt = "Was war dir bei Gerechtigkeit wichtig?"
        spatial_deploy_receipt = Path("/private/deploy-receipt.json")
        spatial_candidate_browser_receipt = Path("/private/candidate-browser-receipt.json")

    local_voice = module.build_local_voice_receipt_command(_Args())
    voice = module.build_voice_receipt_command(_Args())
    browser = module.build_browser_receipt_command(_Args())
    meaningful = module.build_meaningful_browser_receipt_command(_Args())
    spatial = module.build_spatial_receipt_command(_Args())

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
    assert spatial == [
        "python3",
        "scripts/materialize_memorial_spatial_tour_public_origin.py",
        "--deploy-receipt",
        "/private/deploy-receipt.json",
        "--candidate-browser-receipt",
        "/private/candidate-browser-receipt.json",
        "--public-base-url",
        "https://example.com",
        "--output",
        ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json",
    ]
    assert module.SYNC_ARTIFACTS.index(
        Path(".codex-studio/published/memorial_spatial_tour_public_origin.generated.json")
    ) < module.SYNC_ARTIFACTS.index(
        Path(".codex-design/product/PROJECT_MODES.generated.json")
    )
    assert module.SYNC_ARTIFACTS.index(
        Path(".codex-design/product/PROJECT_MODES.generated.json")
    ) < module.SYNC_ARTIFACTS.index(
        Path(".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json")
    )
    assert module.SYNC_ARTIFACTS[-1] == Path(
        ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json"
    )


def test_memorial_clean_materializers_require_explicit_spatial_input_receipts() -> None:
    root = Path(__file__).resolve().parents[1]
    scripts = (
        root / "scripts" / "materialize_memorial_public_gold_clean.py",
        root / "scripts" / "materialize_memorial_public_auto_receipts_clean.py",
    )

    for script in scripts:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "--spatial-deploy-receipt" in result.stderr
        assert "--spatial-candidate-browser-receipt" in result.stderr


def test_memorial_public_auto_receipts_clean_resolves_bare_python_from_path(monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_public_auto_receipts_clean.py",
        "materialize_memorial_public_auto_receipts_clean_python",
    )

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/python3" if name == "python3" else None)

    assert module._resolve_python_bin("python3") == "/usr/bin/python3"
    assert module._resolve_python_bin(".venv/bin/python") == str(module.ROOT / ".venv/bin/python")
    assert module._resolve_python_bin("/opt/python/bin/python") == "/opt/python/bin/python"


def test_memorial_public_auto_receipts_clean_allows_generated_only_worktree(monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_public_auto_receipts_clean.py",
        "materialize_memorial_public_auto_receipts_clean_clean_source",
    )
    expected = {
        "source_worktree_dirty": False,
        "source_dirty_count": 0,
        "source_dirty_files": [],
        "source_dirty_omitted_count": 0,
    }
    monkeypatch.setattr(module, "source_worktree_metadata", lambda root: expected)

    assert module._assert_source_worktree_clean() == expected


def test_memorial_public_auto_receipts_clean_rejects_dirty_source_worktree(monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_public_auto_receipts_clean.py",
        "materialize_memorial_public_auto_receipts_clean_dirty_source",
    )
    monkeypatch.setattr(
        module,
        "source_worktree_metadata",
        lambda root: {
            "source_worktree_dirty": True,
            "source_dirty_count": 1,
            "source_dirty_files": ["ea/app/services/memorial_openvoice.py"],
            "source_dirty_omitted_count": 3,
        },
    )

    try:
        module._assert_source_worktree_clean()
    except SystemExit as exc:
        message = str(exc)
        assert message.startswith("source_worktree_dirty:commit_or_stash_source_changes_before_clean_receipts:")
        assert "count=1" in message
        assert "ea/app/services/memorial_openvoice.py" in message
        assert "omitted=3" in message
    else:
        raise AssertionError("expected SystemExit")


def test_memorial_public_auto_receipts_clean_copies_expected_artifacts(tmp_path) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_public_auto_receipts_clean.py",
        "materialize_memorial_public_auto_receipts_clean_copy",
    )
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


def test_memorial_public_auto_receipts_clean_preflight_rejects_localhost() -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_public_auto_receipts_clean.py",
        "materialize_memorial_public_auto_receipts_clean_preflight_local",
    )

    try:
        module._preflight_public_origin(base_url="http://127.0.0.1:8090", slug="manfred")
    except SystemExit as exc:
        assert str(exc) == "public_origin_must_not_be_localhost:http://127.0.0.1:8090"
    else:
        raise AssertionError("expected SystemExit")


def test_memorial_public_auto_receipts_clean_preflight_requires_live_page_and_manifest(monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_public_auto_receipts_clean.py",
        "materialize_memorial_public_auto_receipts_clean_preflight_remote",
    )
    calls: list[str] = []

    def _fake_http_status(url: str) -> tuple[int, str]:
        calls.append(url)
        if url.endswith("/memorials/manfred"):
            return 404, '{"detail":"not found"}'
        return 200, "{}"

    monkeypatch.setattr(module, "_http_status", _fake_http_status)

    try:
        module._preflight_public_origin(base_url="https://myexternalbrain.com", slug="manfred")
    except SystemExit as exc:
        assert str(exc).startswith("public_origin_page_unavailable:404:https://myexternalbrain.com/memorials/manfred:")
    else:
        raise AssertionError("expected SystemExit")
    assert calls == ["https://myexternalbrain.com/memorials/manfred"]


def test_memorial_public_auto_receipts_clean_preflight_explains_access_block(monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_public_auto_receipts_clean.py",
        "materialize_memorial_public_auto_receipts_clean_preflight_403",
    )

    def _fake_http_status(url: str) -> tuple[int, str]:
        if url.endswith("/memorials/manfred"):
            return 403, "Forbidden"
        return 200, "{}"

    monkeypatch.setattr(module, "_http_status", _fake_http_status)

    try:
        module._preflight_public_origin(base_url="https://myexternalbrain.com", slug="manfred")
    except SystemExit as exc:
        message = str(exc)
        assert message.startswith("public_origin_page_unavailable:403:https://myexternalbrain.com/memorials/manfred:Forbidden:")
        assert "access-blocked" in message
        assert "anonymously reachable" in message
    else:
        raise AssertionError("expected SystemExit")


def test_memorial_public_auto_receipts_clean_preflight_explains_not_found(monkeypatch) -> None:
    module = _load_module(
        "/docker/EA/scripts/materialize_memorial_public_auto_receipts_clean.py",
        "materialize_memorial_public_auto_receipts_clean_preflight_404_detail",
    )

    def _fake_http_status(url: str) -> tuple[int, str]:
        if url.endswith("/memorials/manfred"):
            return 404, '{"detail":"Not Found"}'
        return 200, "{}"

    monkeypatch.setattr(module, "_http_status", _fake_http_status)

    try:
        module._preflight_public_origin(base_url="https://myexternalbrain.com", slug="manfred")
    except SystemExit as exc:
        message = str(exc)
        assert message.startswith('public_origin_page_unavailable:404:https://myexternalbrain.com/memorials/manfred:')
        assert "republish the public memorial bundle" in message
        assert "verify the slug" in message
    else:
        raise AssertionError("expected SystemExit")


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
