from __future__ import annotations

import importlib.util
import io
import json
import logging
import os
import subprocess
import sys
import urllib.error
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "ea_live_ops.py"


def _module():
    spec = importlib.util.spec_from_file_location("ea_live_ops", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "database_url": "postgresql://ea:test@localhost/ea",
        "binding_id": "ea-whatsapp-web-session",
        "principal_id": "principal-default",
        "session_api_base_url": "https://wa-web.test",
        "session_ref": "",
        "timeout_seconds": 5.0,
        "dry_run": False,
    }
    values.update(overrides)
    return Namespace(**values)


def _patch_onemin_direct_refresh_ready(monkeypatch, module) -> None:
    monkeypatch.setattr(
        module,
        "probe_onemin_direct_refresh_posture",
        lambda **_kwargs: {
            "probe_ok": True,
            "checked": True,
            "ready": True,
            "status": "already_refreshed",
            "reason": "all_selected_accounts_already_refreshed",
            "next_action": "",
            "receipt_name": "onemin_direct_refresh_live_guardrails.json",
            "selected_account_count": 1,
            "pending_account_count": 0,
            "owner_row_count": 74,
            "attempted_count": 1,
            "current_run_refreshed_count": 0,
            "refreshed_count": 1,
            "error_count": 0,
            "rate_limited": False,
            "controls": {
                "batch_size": 1,
                "batch_backoff_seconds": 1.0,
                "max_rate_limit_sleep_seconds": 120.0,
                "continue_on_rate_limit": True,
                "refresh_transport": "direct_provider_api",
                "proxy_mode": "direct_no_ui_proxy",
                "proxy_pool_size": 0,
                "proxy_reachable_count": 0,
                "expected_proxy_country": "",
                "proxy_country": "",
                "proxy_country_verified": False,
                "controls_inferred_from_defaults": False,
                "single_account_batch_mode": True,
            },
            "telegram_delivery": {
                "checked": False,
                "sent": False,
                "reason": "",
                "ready": False,
                "message_count": 0,
            },
            "observed_at": "2026-07-05T15:07:20Z",
            "source": "private_receipt:onemin_direct_refresh_live_guardrails.json",
        },
    )


def _ready_unmixr_preflight(*, slot_count: int = 3) -> dict[str, object]:
    return {
        "contract_name": "ea.telegram_epub_audiobook_runtime_preflight.v1",
        "observed_at": "2026-06-23T10:00:00Z",
        "status": "pass",
        "failed_checks": [],
        "warned_checks": [],
        "checks": [
            {"key": "telegram_audiobook_enabled", "status": "pass"},
            {"key": "jobs_root_durable", "status": "pass"},
            {"key": "jobs_root_writable", "status": "pass"},
            {"key": "external_tts_enabled", "status": "pass"},
            {"key": "unmixr_auto_render_enabled", "status": "pass"},
            {"key": "voice_catalog_configured", "status": "pass"},
        ],
        "provider": {
            "api_key_slot_count": slot_count,
            "voice_catalog_count": 292,
            "voice_discovery_enabled": True,
            "unmixr_auto_render_enabled": True,
            "voice_audition_min_candidates": 3,
        },
    }


def test_runtime_container_exec_json_wraps_python_with_in_container_timeout(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_runtime_container_name", lambda: "ea-api")
    observed: dict[str, object] = {}

    def _fake_run(command, **kwargs):
        observed["command"] = list(command)
        observed["timeout"] = kwargs.get("timeout")
        return SimpleNamespace(returncode=0, stdout='{"ok": true, "status": "ready"}\n', stderr="")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    exit_code, payload, container = module._runtime_container_exec_json(code="print('ok')", timeout_seconds=7.0)

    assert exit_code == 0
    assert payload["ok"] is True
    assert container == "ea-api"
    assert observed["command"][:8] == [
        "docker",
        "exec",
        "ea-api",
        "timeout",
        "--kill-after=2s",
        "7s",
        "python3",
        "-c",
    ]
    assert observed["timeout"] == 12.0


def test_runtime_container_unmixr_credit_balance_uses_sanitized_runtime_receipt(monkeypatch) -> None:
    module = _module()
    observed: dict[str, object] = {}
    receipt = {
        "contract_name": "ea.unmixr_credit_balance.v1",
        "status": "pass",
        "observed_at": "2026-07-10T21:55:00Z",
        "configured_slot_count": 3,
        "successful_slot_count": 3,
        "positive_prebuilt_slot_count": 3,
        "prebuilt_credits_min": 480000,
        "prebuilt_credits_max": 500000,
        "cloned_credits_min": 80000,
        "cloned_credits_max": 100000,
        "rows": [
            {
                "slot": 1,
                "http_status": 200,
                "prebuilt_credits": 500000,
                "cloned_credits": 100000,
                "cloned_profile": 4,
            },
            {
                "slot": 2,
                "http_status": 200,
                "prebuilt_credits": 490000,
                "cloned_credits": 90000,
                "cloned_profile": 4,
            },
            {
                "slot": 3,
                "http_status": 200,
                "prebuilt_credits": 480000,
                "cloned_credits": 80000,
                "cloned_profile": 4,
            },
        ],
        "raw_credentials_exposed": False,
        "raw_response_bodies_exposed": False,
    }

    def _fake_exec_json(*, code: str, timeout_seconds: float):
        observed["code"] = code
        observed["timeout_seconds"] = timeout_seconds
        return 0, dict(receipt), "ea-api"

    monkeypatch.setattr(module, "_runtime_container_exec_json", _fake_exec_json)

    report = module._runtime_container_unmixr_credit_balance(timeout_seconds=31.0)

    runtime_code = str(observed["code"])
    assert "https://unmixr.com/api/v1/credit-balance/" in runtime_code
    assert "_unmixr_api_key_slots" in runtime_code
    assert 'method="GET"' in runtime_code
    assert observed["timeout_seconds"] == 31.0
    assert report == receipt
    assert report["raw_credentials_exposed"] is False
    assert report["raw_response_bodies_exposed"] is False


def test_runtime_container_unmixr_credit_balance_strictly_sanitizes_runtime_payload(monkeypatch) -> None:
    module = _module()
    secret = "super-secret-api-key"
    monkeypatch.setattr(
        module,
        "_runtime_container_exec_json",
        lambda **_kwargs: (
            0,
            {
                "contract_name": "attacker-controlled",
                "status": "pass",
                "observed_at": secret,
                "api_key": secret,
                "rows": [
                    {
                        "slot": 99,
                        "http_status": 200,
                        "prebuilt_credits": secret,
                        "cloned_credits": 12,
                        "cloned_profile": 4,
                        "raw_response": secret,
                    },
                    {
                        "slot": 100,
                        "http_status": 503,
                        "error_type": secret,
                        "api_key": secret,
                    },
                ],
            },
            "ea-api",
        ),
    )

    report = module._runtime_container_unmixr_credit_balance()

    assert report["contract_name"] == "ea.unmixr_credit_balance.v1"
    assert report["configured_slot_count"] == 2
    assert report["successful_slot_count"] == 1
    assert report["rows"][0] == {
        "slot": 1,
        "http_status": 200,
        "prebuilt_credits": 0,
        "cloned_credits": 12,
        "cloned_profile": 4,
    }
    assert report["rows"][1] == {"slot": 2, "http_status": 503, "error_type": "Exception"}
    assert secret not in json.dumps(report, sort_keys=True)


def test_docker_compose_exec_json_defaults_to_ea_project(monkeypatch) -> None:
    module = _module()
    monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
    monkeypatch.delenv("EA_LIVE_OPS_COMPOSE_PROJECT_NAME", raising=False)
    monkeypatch.delenv("EA_COMPOSE_PROJECT_NAME", raising=False)
    observed: dict[str, object] = {}

    def _fake_run(command, **kwargs):
        observed["command"] = list(command)
        observed["env"] = dict(kwargs.get("env") or {})
        observed["timeout"] = kwargs.get("timeout")
        return SimpleNamespace(returncode=0, stdout='{"ok": true}\n', stderr="")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    exit_code, payload, _stdout, _stderr = module._docker_compose_exec_json(
        compose_file="/docker/EA/docker-compose.yml",
        service="ea-proactive-ooda",
        command=["python", "-c", "print('ok')"],
        timeout_seconds=7.0,
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert observed["env"]["COMPOSE_PROJECT_NAME"] == "ea"
    assert observed["command"][:6] == ["docker", "compose", "-f", "/docker/EA/docker-compose.yml", "exec", "-T"]
    assert observed["command"][7:10] == ["timeout", "--kill-after=2s", "7s"]
    assert observed["timeout"] == 12.0


def test_proactive_runtime_inputs_default_to_repo_state_on_host(monkeypatch) -> None:
    module = _module()
    monkeypatch.delenv("EA_PROACTIVE_OODA_STATE_PATH", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_RECEIPT_PATH", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_STAGE_PACKET_DIR", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR", raising=False)
    monkeypatch.setattr(module, "_proactive_runtime_root", lambda: Path("/docker/EA"))

    inputs = module._proactive_runtime_inputs()

    assert inputs["state_path"] == "/docker/EA/state/proactive_ooda_notified.json"
    assert inputs["receipt_path"] == "/docker/EA/state/proactive_ooda_latest_run.generated.json"
    assert inputs["stage_packet_dir"] == "/docker/EA/state/proactive_ooda_stage_packets"
    assert inputs["safe_work_result_dir"] == "/docker/EA/state/proactive_ooda_safe_work_results"


def test_docker_compose_exec_json_reports_timeout_payload(monkeypatch) -> None:
    module = _module()

    def _fake_run(_command, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="docker compose exec", timeout=12.0)

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    exit_code, payload, _stdout, _stderr = module._docker_compose_exec_json(
        compose_file="/docker/EA/docker-compose.yml",
        service="ea-proactive-ooda",
        command=["python", "-c", "print('ok')"],
        timeout_seconds=7.0,
    )

    assert exit_code == 124
    assert payload["ok"] is False
    assert payload["timed_out"] is True
    assert payload["reason"] == "TimeoutExpired:7s"
    assert payload["timeout_seconds"] == 7.0


def test_docker_compose_exec_json_preserves_explicit_project(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "custom-stack")
    monkeypatch.setenv("EA_LIVE_OPS_COMPOSE_PROJECT_NAME", "ea")
    observed: dict[str, object] = {}

    def _fake_run(_command, **kwargs):
        observed["env"] = dict(kwargs.get("env") or {})
        return SimpleNamespace(returncode=0, stdout='{"ok": true}\n', stderr="")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    module._docker_compose_exec_json(
        compose_file="/docker/EA/docker-compose.yml",
        service="ea-proactive-ooda",
        command=["python", "-c", "print('ok')"],
        timeout_seconds=7.0,
    )

    assert observed["env"]["COMPOSE_PROJECT_NAME"] == "custom-stack"


def test_proactive_source_coverage_report_classifies_sources_without_raw_payloads() -> None:
    module = _module()
    rows = [
        {
            "created_at": "2026-06-29T07:00:00Z",
            "channel": "google_workspace",
            "event_type": "gmail_draft_followthrough",
            "payload_keys": ["gmail_thread_id_sha256", "calendar_renewal_hint"],
            "hints": ["deadline follow-up"],
        },
        {
            "created_at": "2026-06-29T07:05:00Z",
            "channel": "pocket_ai_audio_transcripts",
            "event_type": "pocket_recording_archive_indexed",
            "payload_keys": ["transcript_sha256"],
            "hints": ["relationship occasion"],
        },
        {
            "created_at": "2026-06-29T07:10:00Z",
            "channel": "vendor_research",
            "event_type": "shopping_shortlist",
            "payload_keys": ["supplier", "profile_location"],
            "hints": ["Amazon purchase context"],
        },
    ]

    report = module._proactive_source_coverage_report(
        principal_id="cf-email:tibor.girschele@gmail.com",
        rows=rows,
        observation_repository="PostgresChannelRuntimeStore",
        observed_at="2026-06-29T07:15:00Z",
        observation_limit=50,
    )

    assert report["status"] == "repaired"
    assert report["observation_row_count"] == 3
    assert report["observed_lane_count"] == report["lane_count"]
    assert report["missing_lane_keys"] == []
    lanes = {lane["key"]: lane for lane in report["lanes"]}
    for key in module.PROACTIVE_SOURCE_COVERAGE_LANE_KEYS:
        assert lanes[key]["observed"] is True
        assert lanes[key]["raw_payload_exposed"] is False
        assert lanes[key]["raw_transcript_text_exposed"] is False
        assert lanes[key]["raw_credential_exposed"] is False
    assert report["privacy"]["raw_rows_exposed"] is False
    assert report["privacy"]["source_ids_hashed"] is True


def test_probe_provider_unmixr_operator_format_uses_runtime_preflight(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_runtime_container_preflight", lambda **_kwargs: {})
    monkeypatch.setattr(
        module,
        "audiobook_runtime_preflight",
        lambda: {
            "contract_name": "ea.telegram_epub_audiobook_runtime_preflight.v1",
            "observed_at": "2026-06-23T10:00:00Z",
            "provider": {
                "api_key_slot_count": 3,
                "voice_catalog_count": 11,
                "voice_discovery_enabled": True,
                "unmixr_auto_render_enabled": True,
                "voice_audition_min_candidates": 3,
            },
            "status": "pass",
        },
    )
    monkeypatch.setattr(module, "_provider_display_name", lambda _provider_key: "Unmixr AI")

    report = module.probe_provider("unmixr", output_format="operator")

    assert report["provider_key"] == "unmixr"
    assert report["status"] == "warn"
    assert report["remaining"] == 3
    assert report["unit"] == "configured_api_key_slots"
    assert report["source"] == "ea.telegram_epub_audiobook_runtime_preflight.v1"
    assert report["raw"]["preflight_execution_source"] == "host_fallback"
    assert report["raw"]["runtime_preflight_available"] is False
    assert "state=warn" in str(report["operator_text"])
    assert "remaining=3 configured_api_key_slots" in str(report["operator_text"])
    assert "observed_at=2026-06-23T10:00:00Z" in str(report["operator_text"])


def test_probe_provider_unmixr_treats_optional_preflight_warnings_as_operationally_pass(monkeypatch) -> None:
    module = _module()
    preflight = {
        "contract_name": "ea.telegram_epub_audiobook_runtime_preflight.v1",
        "observed_at": "2026-06-23T10:00:00Z",
        "status": "warn",
        "failed_checks": [],
        "warned_checks": ["player_access_base_url_present", "unmixr_bulk_pacing_configured"],
        "checks": [
            {"key": "telegram_audiobook_enabled", "status": "pass"},
            {"key": "jobs_root_durable", "status": "pass"},
            {"key": "jobs_root_writable", "status": "pass"},
            {"key": "external_tts_enabled", "status": "pass"},
            {"key": "unmixr_auto_render_enabled", "status": "pass"},
            {"key": "voice_catalog_configured", "status": "pass"},
        ],
        "provider": {
            "api_key_slot_count": 3,
            "voice_catalog_count": 11,
            "voice_discovery_enabled": True,
            "unmixr_auto_render_enabled": True,
            "voice_audition_min_candidates": 3,
        },
    }
    monkeypatch.setattr(module, "_runtime_container_preflight", lambda **_kwargs: dict(preflight))
    monkeypatch.setattr(module, "audiobook_runtime_preflight", lambda: {"status": "fail"})
    monkeypatch.setattr(
        module,
        "_runtime_container_unmixr_credit_balance",
        lambda **_kwargs: {
            "contract_name": "ea.unmixr_credit_balance.v1",
            "status": "pass",
            "observed_at": "2026-06-23T10:00:01Z",
            "configured_slot_count": 3,
            "successful_slot_count": 3,
            "positive_prebuilt_slot_count": 3,
            "prebuilt_credits_min": 480000,
        },
    )
    monkeypatch.setattr(module, "_provider_display_name", lambda _provider_key: "Unmixr AI")

    report = module.probe_provider("unmixr", output_format="json")

    assert report["status"] == "pass"
    assert report["raw"]["preflight_status"] == "warn"
    assert report["raw"]["preflight_warned_checks"] == [
        "player_access_base_url_present",
        "unmixr_bulk_pacing_configured",
    ]


def test_probe_provider_unmixr_prefers_runtime_container_preflight(monkeypatch) -> None:
    module = _module()
    runtime_calls: list[float] = []

    def fake_runtime_preflight(*, timeout_seconds: float) -> dict[str, object]:
        runtime_calls.append(timeout_seconds)
        return {
            "contract_name": "ea.telegram_epub_audiobook_runtime_preflight.v1",
            "observed_at": "2026-06-23T10:00:00Z",
            "status": "warn",
            "failed_checks": [],
            "warned_checks": ["player_access_base_url_present"],
            "checks": [
                {"key": "telegram_audiobook_enabled", "status": "pass"},
                {"key": "jobs_root_durable", "status": "pass"},
                {"key": "jobs_root_writable", "status": "pass"},
                {"key": "external_tts_enabled", "status": "pass"},
                {"key": "unmixr_auto_render_enabled", "status": "pass"},
                {"key": "voice_catalog_configured", "status": "pass"},
            ],
            "provider": {
                "api_key_slot_count": 3,
                "voice_catalog_count": 290,
                "voice_discovery_enabled": True,
                "unmixr_auto_render_enabled": True,
                "voice_audition_min_candidates": 3,
            },
        }

    monkeypatch.setattr(
        module,
        "_runtime_container_preflight",
        fake_runtime_preflight,
    )
    monkeypatch.setattr(
        module,
        "_runtime_container_unmixr_credit_balance",
        lambda **_kwargs: {
            "contract_name": "ea.unmixr_credit_balance.v1",
            "status": "pass",
            "observed_at": "2026-06-23T10:00:01Z",
            "configured_slot_count": 3,
            "successful_slot_count": 3,
            "positive_prebuilt_slot_count": 3,
            "prebuilt_credits_min": 480000,
            "prebuilt_credits_max": 500000,
            "cloned_credits_min": 80000,
            "cloned_credits_max": 100000,
            "raw_credentials_exposed": False,
            "raw_response_bodies_exposed": False,
        },
    )
    monkeypatch.setattr(module, "audiobook_runtime_preflight", lambda: {"status": "fail", "provider": {"api_key_slot_count": 0, "voice_catalog_count": 0}})
    monkeypatch.setattr(module, "_provider_display_name", lambda _provider_key: "Unmixr AI")
    monkeypatch.setattr(module, "_runtime_container_name", lambda: "ea-api")

    report = module.probe_provider("unmixr", output_format="json")

    assert report["status"] == "pass"
    assert report["remaining"] == 480000
    assert report["unit"] == "prebuilt_character_credits_min_per_slot"
    assert report["source"] == "ea.unmixr_credit_balance.v1"
    assert runtime_calls == [45.0]
    assert report["raw"]["runtime_container"] == "ea-api"
    assert report["raw"]["preflight_execution_source"] == "runtime_container"
    assert report["raw"]["runtime_preflight_available"] is True
    assert report["raw"]["preflight_status"] == "warn"
    assert report["raw"]["credit_balance"]["raw_credentials_exposed"] is False


def test_probe_provider_unmixr_failed_balance_uses_preflight_fallback_fields(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_runtime_container_preflight", lambda **_kwargs: _ready_unmixr_preflight())
    monkeypatch.setattr(
        module,
        "_runtime_container_unmixr_credit_balance",
        lambda **_kwargs: {
            "contract_name": "ea.unmixr_credit_balance.v1",
            "status": "probe_failed",
            "observed_at": "2026-06-23T10:00:01Z",
            "reason": "runtime_container_timeout",
            "raw_credentials_exposed": False,
            "raw_response_bodies_exposed": False,
        },
    )
    monkeypatch.setattr(module, "_provider_display_name", lambda _provider_key: "Unmixr AI")

    report = module.probe_provider("unmixr", output_format="json")

    assert report["status"] == "warn"
    assert report["remaining"] == 3
    assert report["unit"] == "configured_api_key_slots"
    assert report["observed_at"] == "2026-06-23T10:00:00Z"
    assert report["source"] == "ea.telegram_epub_audiobook_runtime_preflight.v1"


def test_probe_provider_unmixr_balance_coverage_controls_operational_status(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_runtime_container_preflight", lambda **_kwargs: _ready_unmixr_preflight())
    monkeypatch.setattr(module, "_provider_display_name", lambda _provider_key: "Unmixr AI")
    cases = (
        (
            {
                "contract_name": "ea.unmixr_credit_balance.v1",
                "status": "pass",
                "observed_at": "2026-06-23T10:00:01Z",
                "configured_slot_count": 3,
                "successful_slot_count": 2,
                "positive_prebuilt_slot_count": 2,
                "prebuilt_credits_min": 480000,
            },
            "warn",
            480000,
        ),
        (
            {
                "contract_name": "ea.unmixr_credit_balance.v1",
                "status": "pass",
                "observed_at": "2026-06-23T10:00:01Z",
                "configured_slot_count": 3,
                "successful_slot_count": 3,
                "positive_prebuilt_slot_count": 0,
                "prebuilt_credits_min": 0,
            },
            "fail",
            0,
        ),
    )

    for balance, expected_status, expected_remaining in cases:
        monkeypatch.setattr(
            module,
            "_runtime_container_unmixr_credit_balance",
            lambda balance=balance, **_kwargs: dict(balance),
        )

        report = module.probe_provider("unmixr", output_format="json")

        assert report["status"] == expected_status
        assert report["remaining"] == expected_remaining
        assert report["unit"] == "prebuilt_character_credits_min_per_slot"
        assert report["source"] == "ea.unmixr_credit_balance.v1"


def test_probe_provider_pushbullet_reports_missing_setup_without_raw_secrets(monkeypatch) -> None:
    module = _module()
    observed: dict[str, object] = {}

    def _fake_build_receipt(*, probe_live: bool, timeout_seconds: float, required_clients=()):  # type: ignore[no-untyped-def]
        observed["probe_live"] = probe_live
        observed["timeout_seconds"] = timeout_seconds
        observed["required_clients"] = tuple(required_clients or ())
        return {
            "status": "blocked_setup_required",
            "generated_at": "2026-07-02T20:10:00Z",
            "generated_by": "scripts/materialize_pushbullet_delivery_readiness.py",
            "provider": "pushbullet",
            "account_label": "default(missing)",
            "account_label_basis": "default_client_missing",
            "client_count": 1,
            "multi_client_expected": True,
            "required_client_keys": ["default", "elisabeth"],
            "client_coverage": {
                "configured_client_count": 1,
                "configured_required_client_count": 1,
                "token_present_required_client_count": 0,
                "missing_client_keys": ["default"],
                "missing_token_keys": ["elisabeth"],
            },
            "missing_setup": [
                "pushbullet_client_missing:default",
                "pushbullet_token_missing:elisabeth",
            ],
            "operator_action": {
                "next_action": "create_missing_pushbullet_access_tokens",
                "next_action_href": "https://www.pushbullet.com/#settings/account",
                "next_action_label": "Open Pushbullet account settings",
                "next_action_method": "get",
            },
            "live_probes": [],
        }

    monkeypatch.setattr(module.pushbullet_delivery_readiness, "build_receipt", _fake_build_receipt)
    monkeypatch.setattr(module, "_provider_display_name", lambda _provider_key: "Pushbullet")

    report = module.probe_provider("pushbullet", output_format="operator", timeout_seconds=12.0)

    assert observed == {
        "probe_live": True,
        "timeout_seconds": 12.0,
        "required_clients": (),
    }
    assert report["provider_key"] == "pushbullet"
    assert report["status"] == "blocked_setup_required"
    assert report["ready"] is False
    assert report["probe_ok"] is True
    assert report["account_label"] == "default(missing)"
    assert report["account_label_basis"] == "default_client_missing"
    assert report["reason"] == "pushbullet_client_missing:default,pushbullet_token_missing:elisabeth"
    assert report["next_action"] == "create_missing_pushbullet_access_tokens"
    assert report["next_action_href"] == "https://www.pushbullet.com/#settings/account"
    assert report["next_action_label"] == "Open Pushbullet account settings"
    assert report["next_action_method"] == "get"
    assert report["raw"]["required_client_keys"] == ["default", "elisabeth"]
    assert report["raw"]["account_label_basis"] == "default_client_missing"
    assert report["raw"]["configured_required_client_count"] == 1
    assert report["raw"]["token_present_required_client_count"] == 0
    assert report["raw"]["missing_client_keys"] == ["default"]
    assert report["raw"]["missing_token_keys"] == ["elisabeth"]
    assert report["raw"]["raw_email_exposed"] is False
    assert report["raw"]["raw_token_exposed"] is False
    assert "pushbullet_readiness status=blocked_setup_required" in str(report["operator_text"])
    assert "account=default(missing)" in str(report["operator_text"])
    assert "missing_clients=default" in str(report["operator_text"])
    assert "missing_tokens=elisabeth" in str(report["operator_text"])
    assert "next=create_missing_pushbullet_access_tokens" in str(report["operator_text"])


def test_probe_provider_pushbullet_live_verified_reports_ready_state(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module.pushbullet_delivery_readiness,
        "build_receipt",
        lambda **_kwargs: {
            "status": "ready_live_verified",
            "generated_at": "2026-07-02T20:12:00Z",
            "generated_by": "scripts/materialize_pushbullet_delivery_readiness.py",
            "provider": "pushbullet",
            "account_label": "default->elisabeth",
            "account_label_basis": "default_client_ref",
            "default_client_ref": "elisabeth",
            "client_count": 2,
            "multi_client_expected": True,
            "required_client_keys": ["default", "elisabeth"],
            "client_coverage": {
                "configured_client_count": 2,
                "configured_required_client_count": 2,
                "token_present_required_client_count": 2,
                "missing_client_keys": [],
                "missing_token_keys": [],
            },
            "missing_setup": [],
            "operator_action": {
                "next_action": "keep_pushbullet_clients_configured",
                "next_action_href": "https://www.pushbullet.com/#settings/account",
                "next_action_label": "Open Pushbullet account settings",
                "next_action_method": "get",
            },
            "live_probes": [
                {"status": "pass", "client_key": "default", "raw_email_exposed": False, "raw_token_exposed": False},
                {"status": "pass", "client_key": "elisabeth", "raw_email_exposed": False, "raw_token_exposed": False},
            ],
        },
    )
    monkeypatch.setattr(module, "_provider_display_name", lambda _provider_key: "Pushbullet")

    report = module.probe_provider("pushbullet", output_format="json", timeout_seconds=5.0)

    assert report["provider_key"] == "pushbullet"
    assert report["status"] == "ready_live_verified"
    assert report["ready"] is True
    assert report["probe_ok"] is True
    assert report["account_label"] == "default->elisabeth"
    assert report["account_label_basis"] == "default_client_ref"
    assert report["reason"] == ""
    assert report["next_action"] == "keep_pushbullet_clients_configured"
    assert report["raw"]["client_count"] == 2
    assert report["raw"]["account_label_basis"] == "default_client_ref"
    assert report["raw"]["live_probe_count"] == 2
    assert report["raw"]["missing_setup"] == []
    assert report["raw"]["raw_email_exposed"] is False
    assert report["raw"]["raw_token_exposed"] is False


def test_probe_provider_cost_pressure_reports_runtime_token_pressure(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "_runtime_provider_cost_pressure_payload",
        lambda **_kwargs: (
            0,
            {
                "ok": True,
                "observed_at": "2026-07-02T10:00:00Z",
                "window": "24h",
                "provider_order": ["onemin", "magixai", "gemini_vortex"],
                "groundwork_provider_order": ["onemin", "magixai", "gemini_vortex"],
                "cheap_provider_order": ["onemin", "magixai", "gemini_vortex"],
                "hard_provider_order": ["onemin", "magixai", "gemini_vortex"],
                "cost_gated_lanes": ["audit", "fast", "groundwork", "overflow", "review", "review_light"],
                "gemini_token_usage": {
                    "provider_key": "gemini_vortex",
                    "billing_truth_boundary": "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth",
                    "selected_window": {
                        "window_seconds": 86400.0,
                        "request_count": 3,
                        "tokens_in": 190000,
                        "tokens_out": 15000,
                        "total_tokens": 205000,
                        "soft_cap_tokens": 200000,
                        "state": "soft_cap_exceeded",
                    },
                    "24h": {
                        "window_seconds": 86400.0,
                        "request_count": 3,
                        "tokens_in": 190000,
                        "tokens_out": 15000,
                        "total_tokens": 205000,
                        "soft_cap_tokens": 200000,
                        "state": "soft_cap_exceeded",
                    },
                },
                "onemin_capacity": {
                    "configured_slots": 70,
                    "ready_slots": 12,
                    "degraded_slots": 2,
                    "unknown_slots": 56,
                    "state": "ready",
                },
                "onemin_aggregate": {
                    "sum_free_credits": 12345,
                    "remaining_percent_total": 81.2,
                    "burn_basis": "observed_usage",
                },
                "onemin_billing_aggregate": {
                    "sum_free_credits": 12000,
                    "remaining_percent_total": 80.0,
                    "next_topup_at": "2026-07-03T00:00:00Z",
                },
                "fast_lane_route": {"effective_order": ["onemin", "magixai", "gemini_vortex"]},
            },
            "ea-api",
        ),
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-02T10:00:01Z")

    report = module.probe_provider_cost_pressure(output_format="operator")

    assert report["probe_ok"] is True
    assert report["status"] == "gemini_soft_cap_exceeded"
    assert report["source"] == "runtime_container_exec:ea-api:provider_ledger_cache"
    assert report["primary_background_provider"] == "onemin"
    assert report["fast_provider_order"][:3] == ["onemin", "magixai", "gemini_vortex"]
    assert report["groundwork_provider_order"][:3] == ["onemin", "magixai", "gemini_vortex"]
    assert report["onemin_preferred_when_speed_is_not_critical"] is True
    assert report["onemin_preferred_whenever_usable"] is True
    assert report["onemin_usable"] is True
    assert report["onemin_ready_slots"] == 12
    assert report["gemini_token_tracking"]["24h"]["total_tokens"] == 205000
    assert report["gemini_token_tracking"]["soft_cap_percent_24h"] == 102.5
    assert report["gemini_token_tracking"]["background_cost_gate"] == "closed"
    assert report["routing_decision"] == "prefer_onemin_background_and_remove_gemini_from_cost_gated_background_lanes"
    assert report["privacy"]["raw_provider_secret_exposed"] is False
    assert report["privacy"]["raw_prompt_or_response_text_exposed"] is False
    assert "gemini_24h_tokens=205000/200000" in str(report["operator_text"])


def test_probe_provider_cost_pressure_falls_back_to_host_payload(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "_runtime_provider_cost_pressure_payload",
        lambda **_kwargs: (124, {"ok": False, "reason": "TimeoutExpired:30s"}, "ea-api"),
    )
    monkeypatch.setattr(
        module,
        "_provider_cost_pressure_payload_from_host",
        lambda **_kwargs: {
            "ok": True,
            "observed_at": "2026-07-02T10:05:00Z",
            "window": "24h",
            "provider_order": ["onemin", "magixai", "gemini_vortex"],
            "groundwork_provider_order": ["onemin", "magixai", "gemini_vortex"],
            "cheap_provider_order": ["onemin", "magixai", "gemini_vortex"],
            "hard_provider_order": ["onemin", "magixai", "gemini_vortex"],
            "cost_gated_lanes": ["groundwork"],
            "gemini_token_usage": {
                "provider_key": "gemini_vortex",
                "billing_truth_boundary": "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth",
                "selected_window": {"total_tokens": 10, "soft_cap_tokens": 200000, "state": "within_soft_cap"},
                "24h": {"total_tokens": 10, "soft_cap_tokens": 200000, "state": "within_soft_cap"},
            },
            "onemin_capacity": {"configured_slots": 70, "ready_slots": 0},
            "onemin_aggregate": {},
            "onemin_billing_aggregate": {},
        },
    )

    report = module.probe_provider_cost_pressure(output_format="json")

    assert report["probe_ok"] is True
    assert report["source"] == "host_process:provider_ledger_cache"
    assert report["status"] == "active_cost_control_onemin_not_live_ready"
    assert report["onemin_usable"] is False
    assert report["gemini_token_tracking"]["background_cost_gate"] == "open"
    assert report["routing_decision"] == "keep_onemin_first_but_use_cost_gated_fallback_until_onemin_ready"


def test_probe_provider_cost_pressure_treats_unknown_unprobed_onemin_as_probe_pending(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "_runtime_provider_cost_pressure_payload",
        lambda **_kwargs: (124, {"ok": False, "reason": "TimeoutExpired:30s"}, "ea-api"),
    )
    monkeypatch.setattr(
        module,
        "_provider_cost_pressure_payload_from_host",
        lambda **_kwargs: {
            "ok": True,
            "observed_at": "2026-07-02T10:05:00Z",
            "window": "24h",
            "provider_order": ["onemin", "magixai", "gemini_vortex"],
            "groundwork_provider_order": ["onemin", "magixai", "gemini_vortex"],
            "cheap_provider_order": ["onemin", "magixai", "gemini_vortex"],
            "hard_provider_order": ["onemin", "magixai", "gemini_vortex"],
            "cost_gated_lanes": ["groundwork"],
            "gemini_token_usage": {
                "provider_key": "gemini_vortex",
                "billing_truth_boundary": "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth",
                "selected_window": {"total_tokens": 10, "soft_cap_tokens": 200000, "state": "within_soft_cap"},
                "24h": {"total_tokens": 10, "soft_cap_tokens": 200000, "state": "within_soft_cap"},
            },
            "onemin_capacity": {
                "configured_slots": 70,
                "ready_slots": 0,
                "unknown_slots": 70,
                "state": "unknown",
            },
            "onemin_aggregate": {},
            "onemin_billing_aggregate": {},
        },
    )

    report = module.probe_provider_cost_pressure(output_format="json")

    assert report["probe_ok"] is True
    assert report["source"] == "host_process:provider_ledger_cache"
    assert report["status"] == "active_cost_control_onemin_probe_pending"
    assert report["onemin_usable"] is True
    assert report["onemin_probe_pending"] is True
    assert report["onemin_unknown_slots"] == 70
    assert report["routing_decision"] == "prefer_onemin_background_pending_probe_with_gemini_fallback_only"


def test_probe_provider_onemin_prefers_runtime_container_aggregate(monkeypatch) -> None:
    module = _module()

    def _fail_host_container():
        raise RuntimeError("postgresql://private-value@ea-db")

    def _fake_runtime_exec_json(**kwargs):
        assert "aggregate_snapshot" in kwargs["code"]
        return (
            0,
            {
                "ok": True,
                "aggregate": {
                    "live_remaining_credits_total": 123456,
                    "account_count": 2,
                    "ready_account_count": 2,
                    "live_positive_balance_account_count": 1,
                    "live_ready_account_count": 1,
                    "slot_count": 4,
                    "global_configured_slot_count": 4,
                    "live_positive_balance_slot_count": 2,
                    "live_ready_slot_count": 1,
                    "estimated_hours_remaining_at_current_pace": 9.5,
                    "scope": "all_accounts",
                    "accounts": [
                        {
                            "last_billing_snapshot_at": "2026-06-29T12:00:00Z",
                            "next_topup_at": "2026-07-01T00:00:00Z",
                        }
                    ],
                },
            },
            "ea-api",
        )

    monkeypatch.setattr(module, "_container", _fail_host_container)
    monkeypatch.setattr(module, "_runtime_container_exec_json", _fake_runtime_exec_json)

    report = module.probe_provider("onemin", output_format="operator")

    assert report["provider_key"] == "onemin"
    assert report["status"] == "repaired"
    assert report["remaining"] == 123456
    assert report["refresh_at"] == "2026-07-01T00:00:00Z"
    assert report["observed_at"] == "2026-06-29T12:00:00Z"
    assert report["source"] == "runtime_container_exec:onemin_manager.aggregate_snapshot"
    assert report["raw"]["status_basis"] == "live_ready_slot_count"
    assert report["raw"]["probe"]["runtime_container"] == "ea-api"
    assert "remaining=123456 credits" in str(report["operator_text"])
    assert "live_ready_slots=1" in str(report["operator_text"])
    assert "positive_slots=2" in str(report["operator_text"])
    serialized = json.dumps(report)
    assert "private-value" not in serialized
    assert "ea-db" not in serialized
    assert "postgresql://" not in serialized


def test_probe_provider_onemin_falls_back_to_host_aggregate(monkeypatch) -> None:
    module = _module()

    class _OneminManager:
        def aggregate_snapshot(self, **_kwargs):
            return {
                "state": "ready",
                "sum_free_credits": 456,
                "account_count": 1,
                "live_positive_balance_account_count": 1,
                "estimated_hours_remaining_at_current_pace": 1.25,
                "scope": "host_fallback",
                "accounts": [{"last_billing_snapshot_at": "2026-06-29T12:15:00Z"}],
            }

    monkeypatch.setattr(
        module,
        "_runtime_container_exec_json",
        lambda **_kwargs: (1, {"ok": False, "reason": "runtime_container_exec_exit_1"}, "ea-api"),
    )
    monkeypatch.setattr(module, "_provider_health_report", lambda: {"providers": {"onemin": {"state": "ready"}}})
    monkeypatch.setattr(module, "_container", lambda: SimpleNamespace(onemin_manager=_OneminManager()))
    monkeypatch.setattr(module, "_provider_display_name", lambda _provider_key: "1min.AI")

    report = module.probe_provider("onemin")

    assert report["status"] == "ready"
    assert report["remaining"] == 456
    assert report["source"] == "host_app_container:onemin_manager.aggregate_snapshot"
    assert report["raw"]["probe"]["runtime_probe"]["reason"] == "runtime_container_exec_exit_1"
    assert report["raw"]["probe"]["host_probe"]["reason"] == ""


def test_probe_provider_onemin_reports_no_secret_failure_when_all_paths_fail(monkeypatch) -> None:
    module = _module()

    def _fail_host_container():
        raise RuntimeError("postgresql://private-value@ea-db")

    monkeypatch.setattr(
        module,
        "_runtime_container_exec_json",
        lambda **_kwargs: (1, {"ok": False, "reason": "runtime_container_exec_exit_1"}, "ea-api"),
    )
    monkeypatch.setattr(module, "_provider_health_report", lambda: {"providers": {"onemin": {"state": "unknown"}}})
    monkeypatch.setattr(module, "_container", _fail_host_container)

    report = module.probe_provider("onemin", output_format="operator")

    assert report["status"] == "probe_failed"
    assert report["remaining"] is None
    assert report["raw"]["reason"] == "runtime_container_exec_exit_1"
    assert report["raw"]["runtime_probe"]["reason"] == "runtime_container_exec_exit_1"
    assert report["raw"]["host_probe"]["reason"] == "RuntimeError"
    assert "state=probe_failed" in str(report["operator_text"])
    serialized = json.dumps(report)
    assert "private-value" not in serialized
    assert "ea-db" not in serialized
    assert "postgresql://" not in serialized
    assert "Traceback" not in serialized


def test_probe_whatsapp_readiness_refreshes_receipt_and_formats_operator_text(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    output_path = tmp_path / "whatsapp-readiness.json"

    def _fake_build_whatsapp_web_action_processor_readiness(*, output_path: Path):
        return {
            "status": "blocked",
            "ready": False,
            "reason": "sidecar_not_ready",
            "reasons": ["sidecar_not_ready"],
            "next_action": "restore_whatsapp_web_session_sidecar_readiness",
            "generated_at": "2026-06-29T13:10:49Z",
            "output_path": str(output_path),
            "source_git_head": "abc123",
            "effective_session_ref": "tibor-wa-web",
            "effective_session_ref_source": "state_file",
            "sidecar_ready": False,
            "sidecar_status": "qr_required",
            "sidecar_qr_required": True,
            "sidecar_qr_present": True,
            "sidecar_qr_age_seconds": 35,
            "sidecar_qr_fresh": True,
            "processor_container_enabled": True,
            "processor_callback_secret_present": True,
            "api_callback_secret_present": True,
            "state_fresh": True,
            "state_age_seconds": 0,
            "runtime_ready_claim_allowed": False,
            "live_delivery_claim_allowed": False,
            "qr": "raw-secret-qr",
        }

    monkeypatch.setattr(
        module.whatsapp_action_processor_readiness,
        "build_whatsapp_web_action_processor_readiness",
        _fake_build_whatsapp_web_action_processor_readiness,
    )

    report = module.probe_whatsapp_readiness(refresh=True, receipt_path=str(output_path), output_format="operator")
    serialized = json.dumps(report, sort_keys=True)

    assert report["probe_ok"] is True
    assert report["status"] == "blocked"
    assert report["ready"] is False
    assert report["reason"] == "sidecar_not_ready"
    assert report["next_action"] == "scan_whatsapp_web_qr"
    assert report["receipt_next_action"] == "restore_whatsapp_web_session_sidecar_readiness"
    assert report["sidecar_qr_required"] is True
    assert report["sidecar_qr_present"] is True
    assert report["processor_container_enabled"] is True
    assert "whatsapp_readiness status=blocked" in str(report["operator_text"])
    assert "qr=required:true,present:true,age_seconds:35,fresh:true" in str(report["operator_text"])
    assert "raw-secret-qr" not in serialized


def test_probe_whatsapp_readiness_volatile_refresh_uses_temporary_receipt(monkeypatch) -> None:
    module = _module()
    captured_paths: list[Path] = []

    def _fake_build_whatsapp_web_action_processor_readiness(*, output_path: Path):
        captured_paths.append(output_path)
        return {
            "status": "blocked",
            "ready": False,
            "reason": "sidecar_not_ready",
            "generated_at": "2026-06-29T13:10:49Z",
            "output_path": str(output_path),
            "sidecar_status": "qr_required",
            "sidecar_qr_present": True,
            "sidecar_qr_required": True,
        }

    monkeypatch.setattr(
        module.whatsapp_action_processor_readiness,
        "build_whatsapp_web_action_processor_readiness",
        _fake_build_whatsapp_web_action_processor_readiness,
    )

    report = module.probe_whatsapp_readiness(refresh=True, output_format="json", volatile=True)

    assert report["probe_ok"] is True
    assert report["volatile"] is True
    assert report["source"] == "materialize_whatsapp_web_action_processor_readiness:volatile"
    assert captured_paths
    assert captured_paths[0].name == module.DEFAULT_READINESS_RECEIPT_FILENAME
    assert captured_paths[0].parent != module.DEFAULT_READINESS_RECEIPT_PATH.parent
    assert report["output_path"] == str(captured_paths[0])


def test_probe_whatsapp_readiness_can_read_existing_receipt_without_refresh(tmp_path: Path) -> None:
    module = _module()
    receipt_path = tmp_path / "whatsapp-readiness.json"
    receipt_path.write_text(
        json.dumps(
            {
                "status": "ready",
                "ready": True,
                "reason": "ready",
                "reasons": [],
                "next_action": "send_epub_over_whatsapp_to_start_or_refresh_live_audiobook_flow",
                "generated_at": "2026-06-29T13:11:00Z",
                "output_path": str(receipt_path),
                "effective_session_ref": "tibor-wa-web",
                "sidecar_ready": True,
                "sidecar_status": "ready",
                "processor_container_enabled": True,
                "state_fresh": True,
            }
        ),
        encoding="utf-8",
    )

    report = module.probe_whatsapp_readiness(refresh=False, receipt_path=str(receipt_path), output_format="json")

    assert report["probe_ok"] is True
    assert report["status"] == "ready"
    assert report["ready"] is True
    assert report["source"] == "receipt_file"
    assert report["output_path"] == str(receipt_path)


def test_probe_whatsapp_pairing_writes_qr_svg_without_serializing_raw_qr(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.setattr(module, "_safe_load_whatsapp_binding", lambda _args: (None, ""))
    monkeypatch.setattr(module, "_qr_age_seconds", lambda _value: 35)

    def _fake_sidecar_get(**kwargs):
        assert kwargs["suffix"] == "qr"
        return {
            "ok": True,
            "ready": False,
            "status": "qr_required",
            "qr_present": True,
            "qr_required": True,
            "last_qr_at": "2026-06-29T14:00:00Z",
            "qr": "raw-secret-qr",
        }

    def _fake_sidecar_bytes(**kwargs):
        assert kwargs["suffix"] == "qr.svg"
        return b"<svg>raw-qr-shape</svg>", "image/svg+xml", "https://wa-web.test/sessions/session-1/qr.svg"

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)
    monkeypatch.setattr(module, "_sidecar_bytes", _fake_sidecar_bytes)

    report = module.probe_whatsapp_pairing(
        args=_args(session_ref="session-1"),
        output_format="operator",
        output_dir=str(tmp_path),
    )
    serialized = json.dumps(report, sort_keys=True)

    assert report["status"] == "available"
    assert report["next_action"] == "scan_whatsapp_web_qr"
    assert report["qr_svg_written"] is True
    assert report["qr_svg_content_type"] == "image/svg+xml"
    assert Path(str(report["qr_svg_path"])).read_text(encoding="utf-8") == "<svg>raw-qr-shape</svg>"
    assert "whatsapp_pairing status=available" in str(report["operator_text"])
    assert "raw-secret-qr" not in serialized
    assert "raw-qr-shape" not in serialized


def test_probe_whatsapp_pairing_can_dry_run_telegram_document_send(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    observed: dict[str, object] = {}
    monkeypatch.setattr(module, "_safe_load_whatsapp_binding", lambda _args: (None, ""))
    monkeypatch.setattr(module, "_qr_age_seconds", lambda _value: 12)
    monkeypatch.setattr(
        module,
        "_sidecar_get",
        lambda **_kwargs: {
            "ok": True,
            "ready": False,
            "status": "qr_required",
            "qr_present": True,
            "qr_required": True,
            "last_qr_at": "2026-06-29T14:00:00Z",
        },
    )
    monkeypatch.setattr(
        module,
        "_sidecar_bytes",
        lambda **_kwargs: (b"<svg>qr</svg>", "image/svg+xml", "https://wa-web.test/sessions/session-1/qr.svg"),
    )

    def _fake_send_document(*, principal_id: str, document_ref: str, caption: str, dry_run: bool):
        observed.update(
            {
                "principal_id": principal_id,
                "document_ref": document_ref,
                "caption": caption,
                "dry_run": dry_run,
            }
        )
        return {
            "sent": False,
            "reason": "dry_run",
            "principal_id": principal_id,
            "chat_ref_present": True,
            "chat_ref_sha256": "e" * 64,
            "delivery_transport": "telegram_bot",
        }

    monkeypatch.setattr(module, "send_telegram_document", _fake_send_document)

    report = module.probe_whatsapp_pairing(
        args=_args(session_ref="session-1"),
        output_format="operator",
        send_telegram_to_principal="principal-1",
        dry_run=True,
        output_dir=str(tmp_path),
        telegram_operator_streams="media",
    )

    assert report["telegram_sent"] is False
    assert report["telegram_reason"] == "dry_run"
    assert report["telegram_chat_ref_sha256"] == "e" * 64
    assert observed["principal_id"] == "principal-1"
    assert observed["dry_run"] is True
    assert "pair_url=https://wa-web.test/sessions/session-1/pair" in str(observed["caption"])
    assert report["pair_url_actionable_from_telegram"] is True
    assert report["telegram_caption_includes_pair_url"] is True
    assert Path(str(observed["document_ref"])).is_file()
    assert "telegram_sent=false" in str(report["operator_text"])


def test_probe_whatsapp_pairing_telegram_caption_withholds_host_local_pair_url(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    observed: dict[str, object] = {}
    monkeypatch.setattr(module, "_safe_load_whatsapp_binding", lambda _args: (None, ""))
    monkeypatch.setattr(module, "_qr_age_seconds", lambda _value: 10)
    monkeypatch.setattr(
        module,
        "_sidecar_get",
        lambda **_kwargs: {
            "ok": True,
            "ready": False,
            "status": "qr_required",
            "qr_present": True,
            "qr_required": True,
            "last_qr_at": "2026-06-29T14:00:00Z",
        },
    )
    monkeypatch.setattr(
        module,
        "_sidecar_bytes",
        lambda **_kwargs: (b"<svg>qr</svg>", "image/svg+xml", "http://127.0.0.1:8098/sessions/session-1/qr.svg"),
    )

    def _fake_send_document(*, principal_id: str, document_ref: str, caption: str, dry_run: bool):
        observed.update(
            {
                "principal_id": principal_id,
                "document_ref": document_ref,
                "caption": caption,
                "dry_run": dry_run,
            }
        )
        return {
            "sent": False,
            "reason": "dry_run",
            "principal_id": principal_id,
            "chat_ref_present": True,
            "chat_ref_sha256": "e" * 64,
            "delivery_transport": "telegram_bot",
        }

    monkeypatch.setattr(module, "send_telegram_document", _fake_send_document)

    report = module.probe_whatsapp_pairing(
        args=_args(session_api_base_url="http://127.0.0.1:8098", session_ref="session-1"),
        output_format="operator",
        send_telegram_to_principal="principal-1",
        dry_run=True,
        output_dir=str(tmp_path),
        telegram_operator_streams="media",
    )

    caption = str(observed["caption"])
    assert report["pair_url_scope"] == "host_local"
    assert report["pair_url_actionable_from_telegram"] is False
    assert report["telegram_caption_includes_pair_url"] is False
    assert "pair_url=http://127.0.0.1:8098" not in caption
    assert "pair_url_scope=host_local" in caption
    assert "scan the attached QR" in caption


def test_probe_whatsapp_pairing_suppresses_telegram_when_media_stream_not_allowed(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.setattr(module, "_safe_load_whatsapp_binding", lambda _args: (None, ""))
    monkeypatch.setattr(module, "_qr_age_seconds", lambda _value: 12)
    monkeypatch.setattr(
        module,
        "_sidecar_get",
        lambda **_kwargs: {
            "ok": True,
            "ready": False,
            "status": "qr_required",
            "qr_present": True,
            "qr_required": True,
            "last_qr_at": "2026-06-29T14:00:00Z",
        },
    )
    monkeypatch.setattr(
        module,
        "_sidecar_bytes",
        lambda **_kwargs: (b"<svg>qr</svg>", "image/svg+xml", "https://wa-web.test/sessions/session-1/qr.svg"),
    )
    monkeypatch.setattr(
        module,
        "send_telegram_document",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("telegram send should stay suppressed")),
    )

    report = module.probe_whatsapp_pairing(
        args=_args(session_ref="session-1"),
        output_format="json",
        send_telegram_to_principal="principal-1",
        dry_run=True,
        output_dir=str(tmp_path),
    )

    assert report["telegram_sent"] is False
    assert report["telegram_reason"] == "operator_stream_not_allowed"
    assert report["telegram_delivery_transport"] == "telegram_bot_document"
    assert report["allowed_operator_streams"] == ["office_loop", "office_setup", "recovery"]


def test_probe_whatsapp_pairing_reports_degraded_fallback_when_binding_lookup_errors(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.setattr(module, "_safe_load_whatsapp_binding", lambda _args: (None, "OperationalError"))
    monkeypatch.setattr(module, "_qr_age_seconds", lambda _value: 10)
    monkeypatch.setattr(
        module,
        "_sidecar_get",
        lambda **_kwargs: {
            "ok": True,
            "ready": False,
            "status": "qr_required",
            "qr_present": True,
            "qr_required": True,
            "last_qr_at": "2026-06-29T14:00:00Z",
        },
    )
    monkeypatch.setattr(
        module,
        "_sidecar_bytes",
        lambda **_kwargs: (b"<svg>qr</svg>", "image/svg+xml", "http://127.0.0.1:8098/sessions/session-1/qr.svg"),
    )

    report = module.probe_whatsapp_pairing(
        args=_args(session_api_base_url="http://127.0.0.1:8098", session_ref="session-1"),
        output_dir=str(tmp_path),
    )

    assert report["status"] == "available"
    assert report["binding_lookup_status"] == "degraded_sidecar_fallback"
    assert report["binding_lookup_error"] == "OperationalError"
    assert report["binding_lookup_recovered"] is True
    assert report["binding_lookup_fallback_source"] == "whatsapp_web_session_sidecar_qr"


def test_main_probe_whatsapp_pairing_prints_operator_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="probe-whatsapp-pairing",
            format="operator",
            telegram_principal_id="principal-1",
            send_telegram=False,
            dry_run=False,
            write_qr_svg=True,
            output_dir="",
        ),
    )
    monkeypatch.setattr(
        module,
        "probe_whatsapp_pairing",
        lambda **_kwargs: {"probe_ok": True, "operator_text": "whatsapp_pairing status=available"},
    )

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "whatsapp_pairing status=available"


def test_probe_whatsapp_readiness_failure_reports_exception_type_without_secret(monkeypatch) -> None:
    module = _module()

    def _fake_build_whatsapp_web_action_processor_readiness(*, output_path: Path):
        raise RuntimeError("token secret raw QR")

    monkeypatch.setattr(
        module.whatsapp_action_processor_readiness,
        "build_whatsapp_web_action_processor_readiness",
        _fake_build_whatsapp_web_action_processor_readiness,
    )

    report = module.probe_whatsapp_readiness(refresh=True, output_format="operator")
    serialized = json.dumps(report, sort_keys=True)

    assert report["probe_ok"] is False
    assert report["status"] == "probe_failed"
    assert report["reason"] == "RuntimeError"
    assert "token secret raw QR" not in serialized
    assert "whatsapp_readiness status=probe_failed" in str(report["operator_text"])


def test_operator_text_for_telegram_readiness_keeps_secret_material_out() -> None:
    module = _module()

    text = module._operator_text_for_telegram_readiness(
        {
            "status": "ready",
            "ready": True,
            "principal_id": "principal-1",
            "binding_id": "binding-1",
            "chat_ref_present": True,
            "chat_ref_sha256": "a" * 64,
            "bot_token_present": True,
            "bot_key": "default",
            "bot_handle": "@ea_bot",
            "observed_at": "2026-06-29T13:00:00Z",
            "source": "runtime_container_exec:telegram_delivery.local_binding_scan",
            "raw_chat_ref": "123456789",
            "raw_bot_token": "telegram-secret-token",
        }
    )

    assert "telegram_readiness status=ready" in text
    assert "ready=true" in text
    assert "chat_ref_present=true" in text
    assert "bot_token_present=true" in text
    assert "principal=principal-1" in text
    assert "binding=binding-1" in text
    assert "telegram-secret-token" not in text
    assert "123456789" not in text
    assert "chat_ref_sha256" not in text


def test_probe_telegram_readiness_runtime_reports_ready_without_chat_secret(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T13:40:00Z")

    def _fake_exec_json(*, code: str, timeout_seconds: float):
        assert "resolve_primary_telegram_binding" not in code
        assert "build_container" not in code
        assert "build_tool_runtime" in code
        assert "list_connector_bindings" in code
        assert "os._exit(0)" in code
        assert "flush=True" in code
        assert timeout_seconds == 75.0
        return (
            0,
            {
                "ok": True,
                "ready": True,
                "status": "ready",
                "reason": "",
                "binding_id": "binding-1",
                "principal_id": "principal-1",
                "binding_status": "enabled",
                "chat_ref_present": True,
                "chat_ref_sha256": "a" * 64,
                "bot_key": "default",
                "bot_handle": "ea_concierge_bot",
                "bot_token_present": True,
            },
            "ea-api",
        )

    monkeypatch.setattr(module, "_runtime_container_exec_json", _fake_exec_json)

    report = module.probe_telegram_readiness(principal_id="principal-1", output_format="operator")
    serialized = json.dumps(report, sort_keys=True)

    assert report["probe_ok"] is True
    assert report["ready"] is True
    assert report["status"] == "ready"
    assert report["observed_at"] == "2026-06-29T13:40:00Z"
    assert report["runtime_container"] == "ea-api"
    assert report["chat_ref_sha256"] == "a" * 64
    assert "chat_ref_present=true" in str(report["operator_text"])
    assert "bot_token_present=true" in str(report["operator_text"])
    assert "246813579" not in serialized
    assert "telegram-token" not in serialized


def test_probe_telegram_readiness_reports_missing_token_next_action(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T13:41:00Z")

    def _fake_exec_json(*, code: str, timeout_seconds: float):
        return (
            0,
            {
                "ok": True,
                "ready": False,
                "status": "blocked",
                "reason": "telegram_bot_token_missing",
                "binding_id": "binding-1",
                "principal_id": "principal-1",
                "binding_status": "enabled",
                "chat_ref_present": True,
                "chat_ref_sha256": "b" * 64,
                "bot_key": "default",
                "bot_handle": "ea_concierge_bot",
                "bot_token_present": False,
            },
            "ea-api",
        )

    monkeypatch.setattr(module, "_runtime_container_exec_json", _fake_exec_json)

    report = module.probe_telegram_readiness(principal_id="principal-1", output_format="operator")

    assert report["probe_ok"] is True
    assert report["ready"] is False
    assert report["status"] == "blocked"
    assert report["reason"] == "telegram_bot_token_missing"
    assert report["next_action"] == "configure_telegram_bot_token"
    assert "reason=telegram_bot_token_missing" in str(report["operator_text"])
    assert "next=configure_telegram_bot_token" in str(report["operator_text"])


def test_probe_telegram_readiness_runtime_failure_is_not_probe_ok(monkeypatch) -> None:
    module = _module()

    def _fake_exec_json(*, code: str, timeout_seconds: float):
        return (
            0,
            {
                "ok": False,
                "ready": False,
                "status": "probe_failed",
                "reason": "RuntimeError",
            },
            "ea-api",
        )

    monkeypatch.setattr(module, "_runtime_container_exec_json", _fake_exec_json)

    report = module.probe_telegram_readiness(principal_id="principal-1", output_format="operator")

    assert report["probe_ok"] is False
    assert report["ready"] is False
    assert report["status"] == "probe_failed"
    assert report["reason"] == "RuntimeError"
    assert report["next_action"] == "inspect_telegram_readiness_runtime_probe"


def test_probe_telegram_readiness_runtime_timeout_falls_back_to_host_scan(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-04T15:08:00Z")
    monkeypatch.setattr(
        module,
        "_runtime_container_exec_json",
        lambda **_kwargs: (124, {"ok": False, "reason": "TimeoutExpired:15s"}, "ea-api"),
    )
    monkeypatch.setattr(
        module,
        "_telegram_readiness_payload_from_host",
        lambda **_kwargs: {
            "ok": True,
            "ready": True,
            "status": "ready",
            "reason": "",
            "binding_id": "binding-1",
            "principal_id": "principal-1",
            "binding_status": "enabled",
            "chat_ref_present": True,
            "chat_ref_sha256": "f" * 64,
            "bot_key": "default",
            "bot_handle": "ea_concierge_bot",
            "bot_token_present": True,
        },
    )

    report = module.probe_telegram_readiness(principal_id="principal-1", timeout_seconds=15.0, output_format="json")

    assert report["probe_ok"] is True
    assert report["ready"] is True
    assert report["status"] == "ready"
    assert report["reason"] == ""
    assert report["binding_id"] == "binding-1"
    assert report["chat_ref_sha256"] == "f" * 64
    assert report["runtime_container"] == "ea-api"
    assert report["source"] == "host_process:telegram_delivery.local_binding_scan"


def test_probe_teable_recovery_reports_ready_without_raw_table_id(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T14:10:00Z")

    def _fake_sync_env_to_teable_json(command: str, *, timeout_seconds: float):
        assert timeout_seconds == 30.0
        payload = {
            "status": "pass",
            "table_id": "tbl-secret-id",
            "expected_rows": 535,
            "same_hash": 535,
            "root_restore_count": 420,
            "local_restore_count": 100,
            "service_restore_count": 9,
            "referenced_file_restore_count": 6,
            "different_hash_count": 0,
        }
        if command == "verify":
            return 0, payload | {
                "missing_count": 0,
                "missing_secret_value_count": 0,
                "extra_restorable_count": 0,
                "uncovered_local_secret_file_count": 0,
            }, ""
        if command == "local-status":
            return 0, payload | {
                "missing_artifact_count": 0,
                "wrong_mode_count": 0,
                "wrong_modes": [],
            }, ""
        raise AssertionError(command)

    monkeypatch.setattr(module, "_sync_env_to_teable_json", _fake_sync_env_to_teable_json)

    report = module.probe_teable_recovery(output_format="operator")
    serialized = json.dumps(report, sort_keys=True)

    assert report["ready"] is True
    assert report["status"] == "ready"
    assert report["verify_status"] == "pass"
    assert report["local_status"] == "pass"
    assert report["table_id_present"] is True
    assert len(str(report["table_id_sha256"])) == 64
    assert report["wrong_mode_count"] == 0
    assert "teable_recovery status=ready" in str(report["operator_text"])
    assert "tbl-secret-id" not in serialized


def test_probe_fastestvpn_transport_reports_bounded_ch_topology_without_env_values(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-08-13T06:00:00Z")
    payloads = {
        "ea-fastestvpn-proxy-ch": {
            "State": {"Running": True, "Health": {"Status": "healthy"}},
            "NetworkSettings": {"Ports": {"3128/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9315"}]}},
        },
        "ea-api": {
            "Config": {
                "Env": [
                    "ONEMIN_DIRECT_API_PROXY_SERVER=http://ea-fastestvpn-proxy-ch:3128",
                    "ONEMIN_DIRECT_API_PROXY_POOL=http://ea-fastestvpn-proxy-ch:3128",
                    "PRIVATE_TOKEN=never-serialize-me",
                ],
                "Labels": {
                    "com.docker.compose.project.config_files": "/docker/EA/docker-compose.yml,/docker/EA/docker-compose.fastestvpn.yml"
                },
            }
        },
        "ea-worker": {"Config": {"Env": ["EA_ROLE=worker"]}},
        "ea-scheduler": {"Config": {"Env": ["EA_ROLE=scheduler"]}},
        "ea-whatsapp-web-session": {"Config": {"Env": ["EA_ROLE=whatsapp"]}},
    }
    monkeypatch.setattr(module, "_docker_inspect_container_json", lambda name, **_kwargs: payloads.get(name, {}))

    report = module.probe_fastestvpn_transport_status(output_format="operator")
    serialized = json.dumps(report, sort_keys=True)

    assert report["ready"] is True
    assert report["failed_checks"] == []
    assert report["proxy"]["loopback_only"] is True
    assert report["ea_api"]["ch_only"] is True
    assert all(not row["proxy_env_present"] for row in report["excluded_services"].values())
    assert report["secret_material_exposed"] is False
    assert "never-serialize-me" not in serialized
    assert "http://ea-fastestvpn-proxy-ch:3128" not in serialized


def test_probe_fastestvpn_transport_fails_on_public_bind_or_worker_proxy(monkeypatch) -> None:
    module = _module()
    payloads = {
        "ea-fastestvpn-proxy-ch": {
            "State": {"Running": True, "Health": {"Status": "healthy"}},
            "NetworkSettings": {"Ports": {"3128/tcp": [{"HostIp": "0.0.0.0", "HostPort": "9315"}]}},
        },
        "ea-api": {
            "Config": {
                "Env": [
                    "ONEMIN_DIRECT_API_PROXY_SERVER=http://ea-fastestvpn-proxy-ch:3128",
                    "ONEMIN_DIRECT_API_PROXY_POOL=http://ea-fastestvpn-proxy-ch:3128",
                ],
                "Labels": {"com.docker.compose.project.config_files": "docker-compose.fastestvpn.yml"},
            }
        },
        "ea-worker": {"Config": {"Env": ["ONEMIN_DIRECT_API_PROXY_SERVER=http://retired-proxy:3128"]}},
        "ea-scheduler": {"Config": {"Env": []}},
        "ea-whatsapp-web-session": {"Config": {"Env": []}},
    }
    monkeypatch.setattr(module, "_docker_inspect_container_json", lambda name, **_kwargs: payloads.get(name, {}))

    report = module.probe_fastestvpn_transport_status()

    assert report["ready"] is False
    assert report["status"] == "blocked"
    assert "loopback_only" in report["failed_checks"]
    assert "excluded_services_proxy_free" in report["failed_checks"]


def test_probe_teable_recovery_maps_wrong_secret_mode_to_operator_action(monkeypatch) -> None:
    module = _module()

    def _fake_sync_env_to_teable_json(command: str, *, timeout_seconds: float):
        if command == "verify":
            return 0, {
                "status": "pass",
                "table_id": "tbl-secret-id",
                "expected_rows": 535,
                "same_hash": 535,
                "missing_count": 0,
                "different_hash_count": 0,
                "missing_secret_value_count": 0,
                "extra_restorable_count": 0,
                "uncovered_local_secret_file_count": 0,
            }, ""
        if command == "local-status":
            return 1, {
                "status": "fail",
                "table_id": "tbl-secret-id",
                "expected_rows": 535,
                "same_hash": 535,
                "root_restore_count": 420,
                "local_restore_count": 100,
                "service_restore_count": 9,
                "referenced_file_restore_count": 6,
                "missing_artifact_count": 0,
                "wrong_mode_count": 1,
                "different_hash_count": 0,
                "wrong_modes": [{"path": "/docker/EA/config/secret-file", "mode": "0o644"}],
            }, ""
        raise AssertionError(command)

    monkeypatch.setattr(module, "_sync_env_to_teable_json", _fake_sync_env_to_teable_json)

    report = module.probe_teable_recovery(output_format="operator")

    assert report["ready"] is False
    assert report["status"] == "blocked"
    assert report["reason"] == "teable_recovery_local_secret_mode_drift"
    assert report["next_action"] == "chmod_referenced_secret_files_owner_only"
    assert report["wrong_mode_count"] == 1
    assert report["wrong_mode_paths"] == ["/docker/EA/config/secret-file"]
    assert "wrong_modes=1" in str(report["operator_text"])


def test_probe_teable_recovery_prioritizes_hash_drift_over_generic_verify_failure(monkeypatch) -> None:
    module = _module()

    def _fake_sync_env_to_teable_json(command: str, *, timeout_seconds: float):
        if command == "verify":
            return 1, {
                "status": "fail",
                "table_id": "tbl-secret-id",
                "expected_rows": 551,
                "same_hash": 547,
                "missing_count": 0,
                "different_hash_count": 4,
                "different_hash_keys": [
                    "ea_root:CODEXEA_IMPLEMENT_MODEL",
                    "ea_root:CODEXEA_REPAIR_MODEL",
                    "ea_root:CODEXEA_WORKER_MODEL",
                    "ea_root:EA_SURVIVAL_ROUTE_ORDER",
                ],
                "missing_secret_value_count": 0,
                "extra_restorable_count": 0,
                "uncovered_local_secret_file_count": 0,
            }, ""
        if command == "local-status":
            return 1, {
                "status": "fail",
                "table_id": "tbl-secret-id",
                "expected_rows": 551,
                "same_hash": 547,
                "root_restore_count": 434,
                "local_restore_count": 100,
                "service_restore_count": 11,
                "referenced_file_restore_count": 6,
                "missing_artifact_count": 0,
                "wrong_mode_count": 0,
                "different_hash_count": 4,
                "different_hash_keys": [
                    "ea_root:EA_SURVIVAL_ROUTE_ORDER",
                    "ea_root:CODEXEA_IMPLEMENT_MODEL",
                ],
                "wrong_modes": [],
            }, ""
        raise AssertionError(command)

    monkeypatch.setattr(module, "_sync_env_to_teable_json", _fake_sync_env_to_teable_json)

    report = module.probe_teable_recovery(output_format="operator")

    assert report["ready"] is False
    assert report["status"] == "blocked"
    assert report["reason"] == "teable_recovery_local_hash_drift"
    assert report["next_action"] == "run_env_recover_teable_or_refresh_backup_after_review"
    assert report["different_hash_count"] == 4
    assert report["different_hash_key_samples"] == [
        "ea_root:CODEXEA_IMPLEMENT_MODEL",
        "ea_root:CODEXEA_REPAIR_MODEL",
        "ea_root:CODEXEA_WORKER_MODEL",
        "ea_root:EA_SURVIVAL_ROUTE_ORDER",
    ]
    assert "drift=ea_root:CODEXEA_IMPLEMENT_MODEL" in str(report["operator_text"])


def test_main_probe_teable_recovery_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(module, "parse_args", lambda: Namespace(command="probe-teable-recovery", format="operator", timeout_seconds=5.0))

    def _fake_probe_teable_recovery(*, output_format: str, timeout_seconds: float):
        assert output_format == "operator"
        assert timeout_seconds == 5.0
        return {"ready": True, "operator_text": "teable ok"}

    monkeypatch.setattr(module, "probe_teable_recovery", _fake_probe_teable_recovery)

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "teable ok"


def test_main_probe_telegram_readiness_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(command="probe-telegram-readiness", telegram_principal_id="principal-1", format="operator"),
    )

    def _fake_probe_telegram_readiness(*, principal_id: str, timeout_seconds: float, output_format: str):
        assert principal_id == "principal-1"
        assert timeout_seconds == 75.0
        assert output_format == "operator"
        return {"probe_ok": True, "operator_text": "telegram ok"}

    monkeypatch.setattr(module, "probe_telegram_readiness", _fake_probe_telegram_readiness)

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "telegram ok"


def test_parse_args_probe_google_workspace_oauth_uses_proactive_principal_default(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", "cf-email:test@example.com")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ea_live_ops.py",
            "probe-google-workspace-oauth",
            "--expected-google-email",
            "work.tibor.girschele@gmail.com",
        ],
    )

    args = module.parse_args()

    assert args.command == "probe-google-workspace-oauth"
    assert args.telegram_principal_id == "cf-email:test@example.com"
    assert args.scope_bundle == "full_workspace"
    assert args.probe_gcloud is True
    assert args.observed_google_email == ""


def test_parse_args_trigger_mymedia_amazon_pairing_uses_private_runtime_defaults(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    defaults_path = tmp_path / "mymedia-runtime-defaults.json"
    defaults_path.write_text(
        json.dumps(
            {
                "amazon_otp_channel": "sms",
                "amazon_phone_suffix": "777",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_RUNTIME_DEFAULTS_PATH", str(defaults_path))
    monkeypatch.setattr(sys, "argv", ["ea_live_ops.py", "trigger-mymedia-amazon-pairing"])

    args = module.parse_args()

    assert args.command == "trigger-mymedia-amazon-pairing"
    assert args.otp_channel == "sms"
    assert args.phone_suffix == "777"


def test_parse_args_repair_mymedia_console_api_uses_runtime_defaults(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_CONTAINER", "mymediaalexa")
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_WEB_BASE_URL", "http://127.0.0.1:52051")
    monkeypatch.setattr(
        sys,
        "argv",
        ["ea_live_ops.py", "repair-mymedia-console-api", "--format", "operator", "--timeout-seconds", "90"],
    )

    args = module.parse_args()

    assert args.command == "repair-mymedia-console-api"
    assert args.container_name == "mymediaalexa"
    assert args.web_base_url == "http://127.0.0.1:52051"
    assert args.format == "operator"
    assert args.timeout_seconds == 90.0


def test_parse_args_probe_sonarr_tv_season_uses_runtime_defaults(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_SONARR_BASE_URL", "http://127.0.0.1:8989")
    monkeypatch.setenv("EA_SONARR_CONFIG_PATH", "/docker/arr-v2/sonarr/config.xml")
    monkeypatch.setenv("EA_SONARR_STAGING_ROOT", "/mnt/pcloud/staging/downloads")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ea_live_ops.py",
            "probe-sonarr-tv-season",
            "--series-id",
            "36",
            "--season-number",
            "2",
            "--format",
            "operator",
        ],
    )

    args = module.parse_args()

    assert args.command == "probe-sonarr-tv-season"
    assert args.series_id == 36
    assert args.season_number == 2
    assert args.sonarr_base_url == "http://127.0.0.1:8989"
    assert args.sonarr_config_path == "/docker/arr-v2/sonarr/config.xml"
    assert args.staging_root == "/mnt/pcloud/staging/downloads"
    assert args.format == "operator"


def test_probe_google_workspace_oauth_reports_mismatch_without_raw_email(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-01T19:40:00Z")
    monkeypatch.setattr(
        module.google_workspace_oauth_readiness,
        "build_receipt",
        lambda **_kwargs: {
            "status": "blocked_setup_required",
            "blocker_kind": "oauth_test_user_or_verification_required",
            "console_deep_link": "https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
            "auth_link_template": "https://myexternalbrain.com/app/actions/google/connect?return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace&expected_google_email=%3Credacted-email%3E",
            "missing_setup": ["oauth_test_user_missing_or_app_unverified", "gcloud_project_mismatch"],
            "expected_google_account": {"present": True, "domain": "gmail.com", "email_sha256": "abc"},
            "oauth_client": {"client_project_id": "propertyquarry-498318", "client_project_number": "95627800296"},
            "gcloud_probe": {
                "active_project": "openclaw-concierge",
                "active_project_matches_oauth_project": False,
                "active_account_present": True,
            },
            "operator_action": {
                "user_action_required": True,
                "next_action": "add_google_oauth_test_user_and_retry_full_workspace_auth",
                "next_action_href": "/integrations/google",
                "next_action_label": "Open Google setup",
                "next_action_method": "get",
                "delivery_policy": "action_required_only",
                "telegram_message": "Action needed: Google Full Workspace auth is tied to a different OAuth project than the current gcloud default.",
            },
        },
    )

    report = module.probe_google_workspace_oauth(
        expected_google_email="work.tibor.girschele@gmail.com",
        observed_error="access_denied",
        probe_gcloud=True,
    )

    serialized = json.dumps(report, sort_keys=True)
    assert report["probe_ok"] is True
    assert report["status"] == "blocked_setup_required"
    assert report["missing_setup"] == ["oauth_test_user_missing_or_app_unverified", "gcloud_project_mismatch"]
    assert report["gcloud_project"] == "openclaw-concierge"
    assert report["oauth_project_id"] == "propertyquarry-498318"
    assert "work.tibor.girschele@gmail.com" not in serialized


def test_probe_google_workspace_oauth_uses_retry_action_when_test_user_already_confirmed(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-01T19:42:00Z")
    monkeypatch.setattr(
        module.google_workspace_oauth_readiness,
        "build_receipt",
        lambda **_kwargs: {
            "status": "blocked_setup_required",
            "blocker_kind": "oauth_retry_or_account_selection_required",
            "console_deep_link": "https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
            "auth_link_template": "https://myexternalbrain.com/app/actions/google/connect?return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace&expected_google_email=%3Credacted-email%3E",
            "missing_setup": ["oauth_access_retry_or_account_selection_required"],
            "expected_google_account": {"present": True, "domain": "gmail.com", "email_sha256": "abc"},
            "oauth_client": {"client_project_id": "propertyquarry-498318", "client_project_number": "95627800296"},
            "gcloud_probe": {
                "active_project": "propertyquarry-498318",
                "active_project_matches_oauth_project": True,
                "active_account_present": True,
            },
            "operator_action": {
                "user_action_required": True,
                "next_action": "retry_full_workspace_auth_with_approved_account",
                "next_action_href": "/integrations/google",
                "next_action_label": "Retry Google auth",
                "next_action_method": "get",
                "delivery_policy": "action_required_only",
                "instruction": "Retry the Full Workspace auth link and explicitly choose the approved work Google account.",
                "telegram_message": "Action needed: Google Full Workspace auth is still denied even though the work account is already approved.",
            },
        },
    )

    report = module.probe_google_workspace_oauth(
        expected_google_email="work.tibor.girschele@gmail.com",
        observed_error="access_denied",
        test_user_confirmed=True,
        probe_gcloud=True,
    )

    assert report["status"] == "blocked_setup_required"
    assert report["reason"] == "oauth_retry_or_account_selection_required"
    assert report["missing_setup"] == ["oauth_access_retry_or_account_selection_required"]
    assert report["next_action"] == "retry_full_workspace_auth_with_approved_account"
    assert "missing=oauth_access_retry_or_account_selection_required" in report["operator_text"]


def test_probe_google_workspace_oauth_reports_observed_account_mismatch_without_raw_email(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-01T19:43:00Z")
    captured: dict[str, object] = {}

    def fake_build_receipt(**kwargs):
        captured.update(kwargs)
        return {
            "status": "blocked_setup_required",
            "blocker_kind": "oauth_account_selection_mismatch",
            "console_deep_link": "https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
            "auth_link_template": "https://myexternalbrain.com/app/actions/google/connect?return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace&expected_google_email=%3Credacted-email%3E",
            "missing_setup": ["oauth_account_selection_mismatch"],
            "expected_google_account": {"present": True, "domain": "gmail.com", "email_sha256": "abc"},
            "observed_google_account": {
                "present": True,
                "domain": "gmail.com",
                "email_sha256": "def",
                "matches_expected": False,
                "raw_observed_google_email_exposed": False,
            },
            "oauth_client": {"client_project_id": "propertyquarry-498318", "client_project_number": "95627800296"},
            "gcloud_probe": {
                "active_project": "propertyquarry-498318",
                "active_project_matches_oauth_project": True,
                "active_account_present": True,
            },
            "operator_action": {
                "user_action_required": True,
                "next_action": "retry_full_workspace_auth_with_expected_account",
                "next_action_href": "/integrations/google",
                "next_action_label": "Retry Google auth",
                "next_action_method": "get",
                "delivery_policy": "action_required_only",
                "instruction": "Retry with the intended work Google account.",
                "telegram_message": "Action needed: selected account mismatch.",
            },
        }

    monkeypatch.setattr(module.google_workspace_oauth_readiness, "build_receipt", fake_build_receipt)

    report = module.probe_google_workspace_oauth(
        expected_google_email="work.tibor.girschele@gmail.com",
        observed_google_email="archon.megalon@gmail.com",
        observed_error="access_denied",
        test_user_confirmed=True,
        probe_gcloud=True,
    )

    serialized = json.dumps(report, sort_keys=True)
    assert captured["observed_google_email"] == "archon.megalon@gmail.com"
    assert report["reason"] == "oauth_account_selection_mismatch"
    assert report["missing_setup"] == ["oauth_account_selection_mismatch"]
    assert report["next_action"] == "retry_full_workspace_auth_with_expected_account"
    assert report["observed_google_email_present"] is True
    assert report["observed_google_account_matches_expected"] is False
    assert "work.tibor.girschele@gmail.com" not in serialized
    assert "archon.megalon@gmail.com" not in serialized


def test_probe_mymedia_alexa_reports_pairing_required_and_scan_blocked_by_pairing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-04T12:10:00Z")
    pairing_dir = tmp_path / "active-pairing"
    pairing_dir.mkdir()
    (pairing_dir / "storage_state.json").write_text('{"cookies":[{"name":"session"}]}', encoding="utf-8")
    (pairing_dir / "session.json").write_text(
        json.dumps(
            {
                "resume_url": "https://www.amazon.com/ap/signin",
                "otp_channel": "whatsapp",
                "phone_suffix": "419",
                "surface_kind": "waiting_for_code",
                "captured_at": "2026-07-04T12:05:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_DIR", str(pairing_dir))
    data_dir = tmp_path / "mymedia-data"
    data_dir.mkdir()
    (data_dir / "Preferences.xml").write_text(
        """<?xml version="1.0"?>
<DynamicConfiguration>
  <Label>ea-host</Label>
  <PairedUser />
  <RefreshToken />
  <UseIP4Address>87.106.22.139</UseIP4Address>
  <AllowExternalAccess>2</AllowExternalAccess>
</DynamicConfiguration>
""",
        encoding="utf-8",
    )
    (data_dir / "Messages.xml").write_text(
        """<?xml version="1.0"?>
<ArrayOfEntry>
  <Entry>
    <Value>
      <Title>Index integrity errors found</Title>
      <MessageType>Error</MessageType>
    </Value>
  </Entry>
  <Entry>
    <Value>
      <Title>Could not restore backup index as none existed, clearing index.</Title>
      <MessageType>Warning</MessageType>
    </Value>
  </Entry>
</ArrayOfEntry>
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "_docker_inspect_container_json",
        lambda *_args, **_kwargs: {
            "State": {"Running": True, "Status": "running"},
            "Mounts": [
                {"Destination": "/datadir", "Source": str(data_dir)},
            ],
        },
    )

    def _fake_api(url: str, **_kwargs):
        if url.endswith("/api/Summary"):
            return True, {"GetSummaryInfoResult": {"ConnectionStatus": 0, "Tracks": 0, "WatchFolders": 1}}, 200, ""
        if url.endswith("/api/WatchFolders"):
            return True, {"GetWatchFoldersResult": [{"Status": 0, "Errors": 0}]}, 200, ""
        if url.endswith("/api/Login"):
            return False, {}, 500, "Account not paired"
        raise AssertionError(url)

    monkeypatch.setattr(module, "_mymedia_api_json", _fake_api)

    report = module.probe_mymedia_alexa(
        container_name="mymediaalexa",
        web_base_url="http://127.0.0.1:52051",
        output_format="operator",
    )
    serialized = json.dumps(report, sort_keys=True)

    assert report["probe_ok"] is True
    assert report["ready"] is False
    assert report["status"] == "blocked_pairing_required"
    assert report["reason"] == "amazon_account_not_paired"
    assert report["next_action"] == "enter_mymedia_amazon_pairing_code"
    assert report["pairing_ready"] is False
    assert report["pairing_resume_ready"] is True
    assert report["library_scan_pending"] is True
    assert report["library_scan_blocked_by_pairing"] is True
    assert report["remote_access_mode"] == "push"
    assert report["public_ip_present"] is True
    assert report["connection_status"] == "not_connected"
    assert report["watch_folder_states"] == ["queued"]
    assert report["message_warning_count"] == 1
    assert report["message_error_count"] == 1
    assert report["pairing_artifact_cleanup_attempted"] is False
    assert report["pairing_artifact_cleanup_removed_count"] == 0
    assert "blocked_pairing_required" in str(report["operator_text"])
    assert "87.106.22.139" not in serialized
    assert "/datadir" not in serialized
    assert (pairing_dir / "storage_state.json").exists()
    assert (pairing_dir / "session.json").exists()


def test_probe_mymedia_alexa_surfaces_host_disk_pressure_without_leaking_raw_docker_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-10T03:26:00Z")
    data_dir = tmp_path / "mymedia-data"
    data_dir.mkdir()
    monkeypatch.setattr(
        module,
        "_docker_inspect_container_json",
        lambda *_args, **_kwargs: {
            "State": {
                "Running": False,
                "Status": "exited",
                "ExitCode": 137,
                "OOMKilled": False,
                "Error": (
                    "failed to set up container networking: write "
                    "/var/lib/docker/containers/demo/.tmp-hostconfig.json: no space left on device"
                ),
            },
            "Mounts": [
                {"Destination": "/datadir", "Source": str(data_dir)},
            ],
        },
    )
    monkeypatch.setattr(
        module,
        "_host_root_disk_posture",
        lambda: {
            "usage_percent": 97.0,
            "available_bytes": 22 * 1024**3,
            "available_gb": 22.0,
        },
    )
    monkeypatch.setattr(module, "_mymedia_api_json", lambda *_args, **_kwargs: (False, {}, 0, "URLError"))

    report = module.probe_mymedia_alexa(
        container_name="mymediaalexa",
        web_base_url="http://127.0.0.1:52051",
        output_format="operator",
    )
    serialized = json.dumps(report, sort_keys=True)

    assert report["probe_ok"] is True
    assert report["ready"] is False
    assert report["status"] == "blocked_runtime_unavailable"
    assert report["reason"] == "host_disk_pressure_prevented_container_start"
    assert report["next_action"] == "recover_host_disk_pressure_then_start_mymedia_alexa"
    assert report["container_exit_code"] == 137
    assert report["container_oom_killed"] is False
    assert report["container_error_kind"] == "host_disk_pressure"
    assert report["host_disk_pressure_detected"] is True
    assert report["host_root_usage_percent"] == 97.0
    assert report["host_root_available_gb"] == 22.0
    assert "container_error=host_disk_pressure" in str(report["operator_text"])
    assert "host_disk_pressure=true" in str(report["operator_text"])
    assert "no space left on device" not in serialized
    assert ".tmp-hostconfig.json" not in serialized


def test_probe_mymedia_alexa_reports_ready_without_leaking_pairing_material(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-04T12:11:00Z")
    pairing_dir = tmp_path / "stale-pairing"
    pairing_dir.mkdir()
    (pairing_dir / "storage_state.json").write_text('{"cookies":[{"name":"session"}]}', encoding="utf-8")
    (pairing_dir / "session.json").write_text(
        json.dumps(
            {
                "resume_url": "https://www.amazon.com/ap/signin",
                "otp_channel": "whatsapp",
                "phone_suffix": "419",
                "surface_kind": "waiting_for_code",
                "captured_at": "2026-07-04T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (pairing_dir / "surface.png").write_bytes(b"png")
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_DIR", str(pairing_dir))
    data_dir = tmp_path / "mymedia-data"
    data_dir.mkdir()
    (data_dir / "Preferences.xml").write_text(
        """<?xml version="1.0"?>
<DynamicConfiguration>
  <Label>ea-host</Label>
  <PairedUser>archon.megalon@gmail.com</PairedUser>
  <RefreshToken>refresh-token-secret</RefreshToken>
  <UseIP4Address>87.106.22.139</UseIP4Address>
  <AllowExternalAccess>2</AllowExternalAccess>
</DynamicConfiguration>
""",
        encoding="utf-8",
    )
    (data_dir / "Messages.xml").write_text("""<?xml version="1.0"?><ArrayOfEntry />\n""", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "_docker_inspect_container_json",
        lambda *_args, **_kwargs: {
            "State": {"Running": True, "Status": "running"},
            "Mounts": [
                {"Destination": "/datadir", "Source": str(data_dir)},
            ],
        },
    )

    def _fake_api(url: str, **_kwargs):
        if url.endswith("/api/Summary"):
            return (
                True,
                {
                    "GetSummaryInfoResult": {
                        "ConnectionStatus": 2,
                        "Tracks": 42,
                        "WatchFolders": 1,
                        "Albums": 7,
                        "Artists": 5,
                        "Genres": 3,
                    }
                },
                200,
                "",
            )
        if url.endswith("/api/WatchFolders"):
            return True, {"GetWatchFoldersResult": [{"Status": 2, "Errors": 0}]}, 200, ""
        if url.endswith("/api/Login"):
            return True, {"GetMyMediaLoginResult": "paired-user"}, 200, ""
        raise AssertionError(url)

    monkeypatch.setattr(module, "_mymedia_api_json", _fake_api)

    report = module.probe_mymedia_alexa(
        container_name="mymediaalexa",
        web_base_url="http://127.0.0.1:52051",
        output_format="json",
    )
    serialized = json.dumps(report, sort_keys=True)

    assert report["probe_ok"] is True
    assert report["ready"] is True
    assert report["status"] == "ready"
    assert report["pairing_ready"] is True
    assert report["pairing_session_pending"] is False
    assert report["pairing_resume_ready"] is False
    assert report["pairing_artifact_cleanup_attempted"] is True
    assert report["pairing_artifact_cleanup_removed_count"] == 3
    assert report["pairing_artifact_cleanup_error_count"] == 0
    assert report["connection_status"] == "connected"
    assert report["watch_folder_states"] == ["serving"]
    assert report["tracks"] == 42
    assert report["message_count"] == 0
    assert "archon.megalon@gmail.com" not in serialized
    assert "refresh-token-secret" not in serialized
    assert "87.106.22.139" not in serialized
    assert not pairing_dir.exists()


def test_probe_mymedia_alexa_prefers_wait_when_scan_is_already_progressing(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    data_dir = tmp_path / "mymedia-data"
    data_dir.mkdir()
    (data_dir / "Preferences.xml").write_text(
        """<?xml version="1.0"?>
<DynamicConfiguration>
  <RefreshToken>refresh-token-secret</RefreshToken>
  <AllowExternalAccess>2</AllowExternalAccess>
</DynamicConfiguration>
""",
        encoding="utf-8",
    )
    (data_dir / "Messages.xml").write_text("""<?xml version="1.0"?><ArrayOfEntry />\n""", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "_docker_inspect_container_json",
        lambda *_args, **_kwargs: {
            "State": {"Running": True, "Status": "running"},
            "Mounts": [{"Destination": "/datadir", "Source": str(data_dir)}],
        },
    )

    def _fake_api(url: str, **_kwargs):
        if url.endswith("/api/Summary"):
            return True, {"GetSummaryInfoResult": {"Tracks": 12, "Albums": 1, "Artists": 1, "Genres": 1, "ConnectionStatus": 2}}, 200, ""
        if url.endswith("/api/WatchFolders"):
            return True, {"GetWatchFoldersResult": [{"Status": 0, "Errors": 0}]}, 200, ""
        if url.endswith("/api/Login"):
            return True, {"GetMyMediaLoginResult": "paired-user"}, 200, ""
        raise AssertionError(url)

    monkeypatch.setattr(module, "_mymedia_api_json", _fake_api)

    report = module.probe_mymedia_alexa(
        container_name="mymediaalexa",
        web_base_url="http://127.0.0.1:52051",
        timeout_seconds=5.0,
        output_format="json",
    )

    assert report["ready"] is True
    assert report["status"] == "ready_library_scan_in_progress"
    assert report["reason"] == "mymedia_library_scan_in_progress"
    assert report["next_action"] == "wait_for_mymedia_library_scan"
    assert report["watch_folder_states"] == ["queued"]
    assert report["tracks"] == 12


def test_mymedia_public_surface_probe_classifies_cloudflare_access_redirect(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "_request_text_response",
        lambda **_kwargs: (
            302,
            {
                "Location": "https://girschele.cloudflareaccess.com/cdn-cgi/access/login/home.girschele.com",
                "WWW-Authenticate": 'Cloudflare-Access resource_metadata="https://home.girschele.com/.well-known/cloudflare-access-protected-resource/"',
                "Content-Type": "text/html; charset=UTF-8",
            },
            "",
            "",
        ),
    )

    report = module._mymedia_public_surface_probe("https://home.girschele.com", timeout_seconds=5.0)

    assert report["configured"] is True
    assert report["probe_attempted"] is True
    assert report["ready"] is True
    assert report["status"] == "access_protected"
    assert report["reason"] == ""
    assert report["access_protected"] is True
    assert report["redirect_host"] == "girschele.cloudflareaccess.com"


def test_mymedia_public_surface_probe_classifies_cloudflare_block(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "_request_text_response",
        lambda **_kwargs: (
            403,
            {"Content-Type": "text/html; charset=UTF-8"},
            "<title>Attention Required! | Cloudflare</title><h1>Sorry, you have been blocked</h1>",
            "",
        ),
    )

    report = module._mymedia_public_surface_probe("https://mymedia.girschele.com", timeout_seconds=5.0)

    assert report["configured"] is True
    assert report["probe_attempted"] is True
    assert report["ready"] is False
    assert report["status"] == "blocked_by_cloudflare"
    assert report["reason"] == "mymedia_public_console_blocked_by_cloudflare"
    assert report["cloudflare_blocked"] is True
    assert report["next_action"] == "repair_mymedia_public_console_route"


def test_mymedia_public_surface_tunnel_origin_derives_bridge_host_from_local_console_url() -> None:
    module = _module()

    assert (
        module._mymedia_public_surface_tunnel_origin("http://127.0.0.1:52051/index.html#!/setup")
        == "http://172.17.0.1:52051"
    )
    assert (
        module._mymedia_public_surface_tunnel_origin(
            "http://127.0.0.1:52051/index.html#!/setup",
            explicit_origin_url="https://internal.example.test:8443/path",
        )
        == "https://internal.example.test:8443"
    )


def test_cloudflare_expression_add_host_exception_appends_new_host_to_matching_host_set() -> None:
    module = _module()
    expression = '((cf.client.bot)) and not (http.host in {"photos.girschele.com" "home.girschele.com"})'

    updated = module._cloudflare_expression_add_host_exception(
        expression,
        required_existing_hosts=["home.girschele.com"],
        new_host="mymedia.girschele.com",
    )

    assert '"mymedia.girschele.com"' in updated
    assert '"home.girschele.com"' in updated
    assert updated.count('"mymedia.girschele.com"') == 1


def test_repair_mymedia_public_surface_repairs_route_and_reprobes(monkeypatch) -> None:
    module = _module()
    before = {
        "configured": True,
        "base_url_scope": "public",
        "probe_attempted": True,
        "ready": False,
        "status": "blocked_by_cloudflare",
        "reason": "mymedia_public_console_blocked_by_cloudflare",
        "next_action": "repair_mymedia_public_console_route",
        "next_action_href": "https://mymedia.girschele.com",
        "next_action_label": "Open public My Media URL",
        "next_action_method": "get",
    }
    after = dict(before)
    after.update(
        {
            "ready": True,
            "status": "access_protected",
            "reason": "",
            "next_action": "",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
        }
    )
    probes = iter([before, after])
    written: dict[str, object] = {}
    monkeypatch.setattr(module, "_mymedia_public_surface_probe", lambda *_args, **_kwargs: next(probes))
    monkeypatch.setattr(module, "_cloudflare_auth_ready", lambda: True)
    monkeypatch.setattr(
        module,
        "_cloudflare_lookup_zone_for_host",
        lambda hostname, **_kwargs: {
            "ok": True,
            "zone_id": "zone-1",
            "account_id": "account-1",
            "zone_name": "girschele.com",
        },
    )
    monkeypatch.setattr(
        module,
        "_cloudflare_lookup_named_tunnel",
        lambda account_id, tunnel_name, **_kwargs: {
            "ok": True,
            "tunnel_id": "tunnel-1",
            "tunnel_domain": "tunnel-1.cfargotunnel.com",
        },
    )
    monkeypatch.setattr(
        module,
        "_cloudflare_upsert_dns_record",
        lambda zone_id, **_kwargs: {"ok": True, "changed": True, "record_present": True},
    )
    monkeypatch.setattr(
        module,
        "_cloudflare_upsert_tunnel_ingress",
        lambda account_id, tunnel_id, **_kwargs: {"ok": True, "changed": True, "route_present": True},
    )
    monkeypatch.setattr(
        module,
        "_cloudflare_lookup_access_service_token",
        lambda account_id, **_kwargs: {"ok": True, "service_token_id": "token-1", "service_token_name": "CodexLiz"},
    )
    monkeypatch.setattr(
        module,
        "_cloudflare_upsert_access_app",
        lambda zone_id, **_kwargs: {"ok": True, "changed": True, "app_present": True},
    )
    monkeypatch.setattr(
        module,
        "_cloudflare_patch_private_host_block_exceptions",
        lambda zone_id, **_kwargs: {"ok": True, "changed": True, "patched_rule_count": 3},
    )
    monkeypatch.setattr(module.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_write_private_json", lambda _path, payload: written.update(dict(payload)))

    report = module.repair_mymedia_public_surface(
        web_base_url="http://127.0.0.1:52051",
        public_web_base_url="https://mymedia.girschele.com",
        timeout_seconds=5.0,
        output_format="operator",
    )

    assert report["status"] == "repaired"
    assert report["ready"] is True
    assert report["dns_changed"] is True
    assert report["tunnel_changed"] is True
    assert report["access_app_changed"] is True
    assert report["firewall_changed"] is True
    assert report["after_public_surface"]["status"] == "access_protected"
    assert "mymedia_public_surface status=repaired" in str(report["operator_text"])
    assert written["status"] == "repaired"


def test_repair_mymedia_console_api_restarts_container_and_reprobes(monkeypatch) -> None:
    module = _module()
    before = {
        "probe_ok": True,
        "ready": False,
        "status": "blocked_console_unreachable",
        "reason": "mymedia_console_api_unreachable",
        "next_action": "repair_mymedia_console_api",
        "next_action_href": "http://127.0.0.1:52051/index.html",
        "next_action_label": "Open My Media console",
        "next_action_method": "get",
        "container_running": True,
        "api_reachable": False,
    }
    after = {
        "probe_ok": True,
        "ready": False,
        "status": "blocked_connection_not_ready",
        "reason": "amazon_connection_not_ready",
        "next_action": "inspect_mymedia_amazon_connection",
        "next_action_href": "http://127.0.0.1:52051/index.html",
        "next_action_label": "Open My Media console",
        "next_action_method": "get",
        "container_running": True,
        "api_reachable": True,
    }
    probes = iter([before, after])
    written: dict[str, object] = {}
    monkeypatch.setattr(module, "probe_mymedia_alexa", lambda **_kwargs: dict(next(probes)))
    monkeypatch.setattr(module, "_docker_restart_container", lambda *_args, **_kwargs: {"ok": True, "reason": ""})
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T14:20:00Z")
    monkeypatch.setattr(module, "_write_private_json", lambda _path, payload: written.update(dict(payload)))

    report = module.repair_mymedia_console_api(
        container_name="mymediaalexa",
        web_base_url="http://127.0.0.1:52051",
        timeout_seconds=5.0,
        output_format="operator",
    )

    assert report["status"] == "repaired"
    assert report["ready"] is False
    assert report["restart_attempted"] is True
    assert report["restart_ok"] is True
    assert report["api_recovered"] is True
    assert report["next_action"] == "inspect_mymedia_amazon_connection"
    assert report["after_probe"]["status"] == "blocked_connection_not_ready"
    assert "mymedia_console_api status=repaired" in str(report["operator_text"])
    assert written["status"] == "repaired"


def test_repair_mymedia_console_api_reports_ready_without_restart_when_api_healthy(monkeypatch) -> None:
    module = _module()
    probe = {
        "probe_ok": True,
        "ready": False,
        "status": "blocked_connection_not_ready",
        "reason": "amazon_connection_not_ready",
        "next_action": "inspect_mymedia_amazon_connection",
        "next_action_href": "http://127.0.0.1:52051/index.html",
        "next_action_label": "Open My Media console",
        "next_action_method": "get",
        "container_running": True,
        "api_reachable": True,
    }
    written: dict[str, object] = {}
    monkeypatch.setattr(module, "probe_mymedia_alexa", lambda **_kwargs: dict(probe))
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T14:20:00Z")
    monkeypatch.setattr(module, "_write_private_json", lambda _path, payload: written.update(dict(payload)))

    report = module.repair_mymedia_console_api(
        container_name="mymediaalexa",
        web_base_url="http://127.0.0.1:52051",
        timeout_seconds=5.0,
        output_format="json",
    )

    assert report["status"] == "ready"
    assert report["ready"] is True
    assert report["restart_attempted"] is False
    assert report["api_recovered"] is True
    assert report["next_action"] == "inspect_mymedia_amazon_connection"
    assert written["status"] == "ready"


def test_probe_sonarr_tv_season_reports_staging_candidate_for_missing_episodes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    config_path = tmp_path / "sonarr-config.xml"
    config_path.write_text("<Config><ApiKey>abc123</ApiKey></Config>", encoding="utf-8")
    staging_root = tmp_path / "staging"
    candidate_dir = staging_root / "LEGO.Ninjago.Dragons.Rising.S02.1080p.NF.WEB-DL.DDP5.1.H.264-STRiKES"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "LEGO.Ninjago.Dragons.Rising.S02E03.Beyond.the.Phantasm.Cave.1080p.NF.WEB-DL.mkv").write_text(
        "ep3",
        encoding="utf-8",
    )
    (candidate_dir / "LEGO.Ninjago.Dragons.Rising.S02E04.Force.From.the.East.1080p.NF.WEB-DL.mkv").write_text(
        "ep4",
        encoding="utf-8",
    )

    def _fake_request(*, path: str, **_kwargs):
        if path == "/api/v3/series":
            return [
                {
                    "id": 36,
                    "title": "LEGO Ninjago: Dragons Rising",
                    "path": "/mnt/pcloud/PLEX/Requested/TV/LEGO Ninjago - Dragons Rising",
                    "seasonFolder": True,
                    "seasons": [{"seasonNumber": 2, "monitored": True}],
                }
            ]
        if path == "/api/v3/episode?seriesId=36":
            return [
                {"id": 13503, "seasonNumber": 2, "episodeNumber": 1, "hasFile": True, "episodeFileId": 1943},
                {"id": 13504, "seasonNumber": 2, "episodeNumber": 2, "hasFile": True, "episodeFileId": 1944},
                {"id": 13505, "seasonNumber": 2, "episodeNumber": 3, "hasFile": False},
                {"id": 13506, "seasonNumber": 2, "episodeNumber": 4, "hasFile": False},
            ]
        if path == "/api/v3/episodefile?seriesId=36":
            return [
                {"id": 1943, "path": "/library/LEGO.Ninjago.Dragons.Rising.S02E01.mkv", "mediaInfo": {"videoCodec": "h264"}},
                {"id": 1944, "path": "/library/LEGO.Ninjago.Dragons.Rising.S02E02.mkv", "mediaInfo": {"videoCodec": "h264"}},
            ]
        raise AssertionError(path)

    monkeypatch.setattr(module, "_sonarr_request_json_value", _fake_request)
    monkeypatch.setattr(
        module,
        "_sonarr_list_queue",
        lambda **_kwargs: [
            {
                "id": 1549244358,
                "seriesId": 36,
                "episodeId": 13505,
                "seasonNumber": 2,
                "episodeNumber": 3,
                "title": "LEGO.Ninjago.Dragons.Rising.S02E03.1080p.WEB.h264-DOLORES",
                "trackedDownloadState": "downloading",
                "errorMessage": "qBittorrent is downloading metadata",
                "added": "2026-07-01T16:08:18Z",
            }
        ],
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T14:45:00Z")
    monkeypatch.setattr(
        module,
        "_sonarr_probe_file_playability",
        lambda path, timeout_seconds: {
            "path": str(path),
            "ok": True,
            "probed": True,
            "method": "ffprobe",
            "reason": "",
            "detail": "h264",
        },
    )

    report = module.probe_sonarr_tv_season(
        series_id=36,
        season_number=2,
        sonarr_base_url="http://127.0.0.1:8989",
        sonarr_config_path=str(config_path),
        staging_root=str(staging_root),
        timeout_seconds=5.0,
        output_format="operator",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "blocked_staging_import_available"
    assert report["missing_episode_numbers"] == [3, 4]
    assert report["metadata_queue_episode_numbers"] == [3]
    assert report["selected_staging_candidate_name"] == candidate_dir.name
    assert report["selected_staging_candidate_cover_count"] == 2
    assert "staging_candidate=" in str(report["operator_text"])


def test_probe_sonarr_tv_season_ignores_invalid_staging_candidates(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    config_path = tmp_path / "sonarr-config.xml"
    config_path.write_text("<Config><ApiKey>abc123</ApiKey></Config>", encoding="utf-8")
    staging_root = tmp_path / "staging"
    invalid_file = staging_root / "LEGO.Ninjago.Dragons.Rising.S02E04.1080p.WEB.h264-DOLORES[EZTVx.to].mkv"
    invalid_file.parent.mkdir(parents=True, exist_ok=True)
    invalid_file.write_text("stub", encoding="utf-8")

    def _fake_request(*, path: str, **_kwargs):
        if path == "/api/v3/series":
            return [
                {
                    "id": 36,
                    "title": "LEGO Ninjago: Dragons Rising",
                    "path": "/mnt/pcloud/PLEX/Requested/TV/LEGO Ninjago - Dragons Rising",
                    "seasonFolder": True,
                    "seasons": [{"seasonNumber": 2, "monitored": True}],
                }
            ]
        if path == "/api/v3/episode?seriesId=36":
            return [
                {"id": 13504, "seasonNumber": 2, "episodeNumber": 4, "hasFile": False},
            ]
        if path == "/api/v3/episodefile?seriesId=36":
            return []
        raise AssertionError(path)

    monkeypatch.setattr(module, "_sonarr_request_json_value", _fake_request)
    monkeypatch.setattr(module, "_sonarr_list_queue", lambda **_kwargs: [])
    monkeypatch.setattr(
        module,
        "_sonarr_probe_file_playability",
        lambda path, timeout_seconds: {
            "path": str(path),
            "ok": False,
            "probed": True,
            "method": "ffprobe",
            "reason": "ffprobe_invalid_media",
            "detail": "EBML header parsing failed",
        },
    )

    report = module.probe_sonarr_tv_season(
        series_id=36,
        season_number=2,
        sonarr_base_url="http://127.0.0.1:8989",
        sonarr_config_path=str(config_path),
        staging_root=str(staging_root),
        timeout_seconds=5.0,
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "blocked_missing_episodes"
    assert report["selected_staging_candidate_name"] == ""
    assert report["selected_staging_candidate_cover_count"] == 0
    assert report["staging_candidate_count"] == 1


def test_probe_sonarr_tv_season_downgrades_fresh_metadata_queue_to_recovery_action(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    config_path = tmp_path / "sonarr-config.xml"
    config_path.write_text("<Config><ApiKey>abc123</ApiKey></Config>", encoding="utf-8")

    def _fake_request(*, path: str, **_kwargs):
        if path == "/api/v3/series":
            return [
                {
                    "id": 36,
                    "title": "LEGO Ninjago: Dragons Rising",
                    "path": "/mnt/pcloud/PLEX/Requested/TV/LEGO Ninjago - Dragons Rising",
                    "seasonFolder": True,
                    "seasons": [{"seasonNumber": 2, "monitored": True}],
                }
            ]
        if path == "/api/v3/episode?seriesId=36":
            return [
                {"id": 13511, "seasonNumber": 2, "episodeNumber": 9, "hasFile": False},
            ]
        if path == "/api/v3/episodefile?seriesId=36":
            return []
        raise AssertionError(path)

    monkeypatch.setattr(module, "_sonarr_request_json_value", _fake_request)
    monkeypatch.setattr(
        module,
        "_sonarr_list_queue",
        lambda **_kwargs: [
            {
                "id": 111,
                "seriesId": 36,
                "episodeId": 13511,
                "seasonNumber": 2,
                "episodeNumber": 9,
                "title": "LEGO.Ninjago.Dragons.Rising.S02E09.1080p.WEB.h264-DOLORES",
                "trackedDownloadState": "downloading",
                "errorMessage": "qBittorrent is downloading metadata",
                "added": "2026-07-05T16:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T16:05:00Z")
    monkeypatch.setattr(
        module,
        "_sonarr_probe_file_playability",
        lambda path, timeout_seconds: {
            "path": str(path),
            "ok": False,
            "probed": True,
            "method": "ffprobe",
            "reason": "ffprobe_invalid_media",
            "detail": "EBML header parsing failed",
        },
    )

    report = module.probe_sonarr_tv_season(
        series_id=36,
        season_number=2,
        sonarr_base_url="http://127.0.0.1:8989",
        sonarr_config_path=str(config_path),
        staging_root=str(tmp_path / "staging"),
        timeout_seconds=5.0,
        output_format="json",
    )

    assert report["status"] == "ready_with_recovery_action"
    assert report["reason"] == "sonarr_metadata_queue_downloading_metadata"
    assert report["next_action"] == "wait_for_download_client_or_reprobe_sonarr_tv_season"


def test_probe_sonarr_tv_season_reports_media_info_drift_when_file_is_playable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    config_path = tmp_path / "sonarr-config.xml"
    config_path.write_text("<Config><ApiKey>abc123</ApiKey></Config>", encoding="utf-8")
    episode_path = tmp_path / "LEGO.Ninjago.Dragons.Rising.S02E03.Beyond.the.Phantasm.Cave.1080p.NF.WEB-DL.mkv"
    episode_path.write_text("placeholder", encoding="utf-8")

    def _fake_request(*, path: str, **_kwargs):
        if path == "/api/v3/series":
            return [
                {
                    "id": 36,
                    "title": "LEGO Ninjago: Dragons Rising",
                    "path": "/mnt/pcloud/PLEX/Requested/TV/LEGO Ninjago - Dragons Rising",
                    "seasonFolder": True,
                    "seasons": [{"seasonNumber": 2, "monitored": True}],
                }
            ]
        if path == "/api/v3/episode?seriesId=36":
            return [
                {"id": 13505, "seasonNumber": 2, "episodeNumber": 3, "hasFile": True, "episodeFileId": 1945},
            ]
        if path == "/api/v3/episodefile?seriesId=36":
            return [
                {"id": 1945, "path": str(episode_path), "mediaInfo": None},
            ]
        raise AssertionError(path)

    monkeypatch.setattr(module, "_sonarr_request_json_value", _fake_request)
    monkeypatch.setattr(module, "_sonarr_list_queue", lambda **_kwargs: [])
    monkeypatch.setattr(
        module,
        "_sonarr_probe_file_playability",
        lambda path, timeout_seconds: {
            "path": str(path),
            "ok": True,
            "probed": True,
            "method": "ffprobe",
            "reason": "",
            "detail": "h264",
        },
    )

    report = module.probe_sonarr_tv_season(
        series_id=36,
        season_number=2,
        sonarr_base_url="http://127.0.0.1:8989",
        sonarr_config_path=str(config_path),
        staging_root=str(tmp_path / "staging"),
        timeout_seconds=5.0,
        output_format="operator",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "ready_with_recovery_action"
    assert report["ready"] is False
    assert report["media_info_missing_episode_numbers"] == [3]
    assert report["unreadable_episode_numbers"] == []
    assert report["episode_file_probe_method"] == "ffprobe"
    assert "media_info_missing=1[3]" in str(report["operator_text"])


def test_probe_sonarr_tv_season_reports_unreadable_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    config_path = tmp_path / "sonarr-config.xml"
    config_path.write_text("<Config><ApiKey>abc123</ApiKey></Config>", encoding="utf-8")
    episode_path = tmp_path / "LEGO.Ninjago.Dragons.Rising.S02E03.Beyond.the.Phantasm.Cave.1080p.NF.WEB-DL.mkv"
    episode_path.write_text("placeholder", encoding="utf-8")

    def _fake_request(*, path: str, **_kwargs):
        if path == "/api/v3/series":
            return [
                {
                    "id": 36,
                    "title": "LEGO Ninjago: Dragons Rising",
                    "path": "/mnt/pcloud/PLEX/Requested/TV/LEGO Ninjago - Dragons Rising",
                    "seasonFolder": True,
                    "seasons": [{"seasonNumber": 2, "monitored": True}],
                }
            ]
        if path == "/api/v3/episode?seriesId=36":
            return [
                {"id": 13505, "seasonNumber": 2, "episodeNumber": 3, "hasFile": True, "episodeFileId": 1945},
            ]
        if path == "/api/v3/episodefile?seriesId=36":
            return [
                {"id": 1945, "path": str(episode_path), "mediaInfo": None},
            ]
        raise AssertionError(path)

    monkeypatch.setattr(module, "_sonarr_request_json_value", _fake_request)
    monkeypatch.setattr(module, "_sonarr_list_queue", lambda **_kwargs: [])
    monkeypatch.setattr(
        module,
        "_sonarr_probe_file_playability",
        lambda path, timeout_seconds: {
            "path": str(path),
            "ok": False,
            "probed": True,
            "method": "ffprobe",
            "reason": "ffprobe_invalid_media",
            "detail": "EBML header parsing failed",
        },
    )

    report = module.probe_sonarr_tv_season(
        series_id=36,
        season_number=2,
        sonarr_base_url="http://127.0.0.1:8989",
        sonarr_config_path=str(config_path),
        staging_root=str(tmp_path / "staging"),
        timeout_seconds=5.0,
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "blocked_unreadable_episode_files"
    assert report["ready"] is False
    assert report["media_info_missing_episode_numbers"] == [3]
    assert report["unreadable_episode_numbers"] == [3]
    assert report["unreadable_episode_count"] == 1


def test_sonarr_request_command_retries_http_error_once(monkeypatch) -> None:
    module = _module()
    calls = {"count": 0}

    def _fake_request(**_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.HTTPError(
                url="http://127.0.0.1:8989/api/v3/command",
                code=400,
                msg="bad request",
                hdrs=None,
                fp=None,
            )
        return {"id": 41}

    monkeypatch.setattr(module, "_sonarr_request_json_value", _fake_request)
    monkeypatch.setattr(module, "_sonarr_wait_for_command", lambda **_kwargs: {"status": "completed"})
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    report = module._sonarr_request_command(
        base_url="http://127.0.0.1:8989",
        api_key="abc123",
        name="RefreshSeries",
        body={"seriesId": 36},
        timeout_seconds=5.0,
    )

    assert report["ok"] is True
    assert report["command_id"] == 41
    assert report["status"] == "completed"
    assert report["attempts"] == 2


def test_sonarr_request_json_value_adds_content_type_for_post(monkeypatch) -> None:
    module = _module()
    observed: dict[str, object] = {}

    def _fake_request_json_value(**kwargs):
        observed.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(module, "_request_json_value", _fake_request_json_value)

    payload = module._sonarr_request_json_value(
        base_url="http://127.0.0.1:8989",
        api_key="abc123",
        path="/api/v3/command",
        method="POST",
        body={"name": "EpisodeSearch", "episodeIds": [13505]},
        timeout_seconds=5.0,
    )

    assert payload == {"ok": True}
    assert observed["headers"]["X-Api-Key"] == "abc123"
    assert observed["headers"]["Content-Type"] == "application/json"


def test_repair_sonarr_tv_season_imports_files_rescans_and_clears_queue(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    series_root = tmp_path / "library" / "LEGO Ninjago - Dragons Rising"
    staging_root = tmp_path / "staging"
    candidate_dir = staging_root / "LEGO.Ninjago.Dragons.Rising.S02.1080p.NF.WEB-DL.DDP5.1.H.264-STRiKES"
    candidate_dir.mkdir(parents=True)
    ep3 = candidate_dir / "LEGO.Ninjago.Dragons.Rising.S02E03.Beyond.the.Phantasm.Cave.1080p.NF.WEB-DL.mkv"
    ep4 = candidate_dir / "LEGO.Ninjago.Dragons.Rising.S02E04.Force.From.the.East.1080p.NF.WEB-DL.mkv"
    ep3.write_text("ep3", encoding="utf-8")
    ep4.write_text("ep4", encoding="utf-8")
    config_path = tmp_path / "sonarr-config.xml"
    config_path.write_text("<Config><ApiKey>abc123</ApiKey></Config>", encoding="utf-8")

    pre_probe = {
        "probe_ok": True,
        "ready": False,
        "status": "blocked_staging_import_available",
        "reason": "sonarr_missing_episodes_have_staging_candidate",
        "next_action": "repair_sonarr_tv_season",
        "series_id": 36,
        "series_title": "LEGO Ninjago: Dragons Rising",
        "series_path": str(series_root),
        "season_folder": True,
        "season_number": 2,
        "missing_episode_numbers": [3, 4],
        "metadata_queue_episode_numbers": [3, 4],
        "staging_candidates": [
            {
                "name": candidate_dir.name,
                "path": str(candidate_dir),
                "cover_count": 2,
                "valid_cover_count": 2,
            }
        ],
        "selected_staging_candidate": {
            "name": candidate_dir.name,
            "path": str(candidate_dir),
            "cover_count": 2,
            "valid_cover_count": 2,
        },
    }
    post_probe = {
        "probe_ok": True,
        "ready": False,
        "status": "blocked_stale_metadata_queue",
        "reason": "sonarr_stale_metadata_queue",
        "next_action": "repair_sonarr_tv_season",
        "series_id": 36,
        "series_title": "LEGO Ninjago: Dragons Rising",
        "series_path": str(series_root),
        "season_folder": True,
        "season_number": 2,
        "have_episode_numbers": [1, 2, 3, 4],
        "missing_episode_numbers": [],
        "metadata_queue_episode_numbers": [3, 4],
        "metadata_queue_items": [
            {"id": 101, "episode_number": 3, "episode_has_file": True, "is_stale": True},
            {"id": 102, "episode_number": 4, "episode_has_file": True, "is_stale": True},
        ],
    }
    final_probe = {
        "probe_ok": True,
        "ready": True,
        "status": "ready",
        "reason": "",
        "next_action": "",
        "series_id": 36,
        "series_title": "LEGO Ninjago: Dragons Rising",
        "series_path": str(series_root),
        "season_folder": True,
        "season_number": 2,
        "have_episode_numbers": [1, 2, 3, 4],
        "missing_episode_numbers": [],
        "metadata_queue_episode_numbers": [],
        "metadata_queue_items": [],
    }
    probes = iter([pre_probe, post_probe, final_probe])
    written: dict[str, object] = {}
    delete_calls: list[list[int]] = []

    monkeypatch.setattr(module, "probe_sonarr_tv_season", lambda **_kwargs: dict(next(probes)))
    monkeypatch.setattr(module, "_read_xml_api_key", lambda _path: "abc123")
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T15:00:00Z")
    monkeypatch.setattr(module, "_write_private_json", lambda _path, payload: written.update(dict(payload)))
    monkeypatch.setattr(module, "_sonarr_request_json_value", lambda **_kwargs: {"id": 42})
    monkeypatch.setattr(module, "_sonarr_wait_for_command", lambda **_kwargs: {"status": "completed"})
    monkeypatch.setattr(
        module,
        "_sonarr_probe_file_playability",
        lambda path, timeout_seconds: {
            "path": str(path),
            "ok": True,
            "probed": True,
            "method": "ffprobe",
            "reason": "",
            "detail": "h264",
        },
    )
    monkeypatch.setattr(
        module,
        "_sonarr_delete_queue_rows",
        lambda **kwargs: delete_calls.append(list(kwargs["queue_ids"])) or {"ok": True, "removed_count": len(kwargs["queue_ids"])},
    )

    report = module.repair_sonarr_tv_season(
        series_id=36,
        season_number=2,
        sonarr_base_url="http://127.0.0.1:8989",
        sonarr_config_path=str(config_path),
        staging_root=str(staging_root),
        timeout_seconds=5.0,
        output_format="operator",
    )

    season_dir = series_root / "Season 2"
    assert report["status"] == "repaired"
    assert report["ready"] is True
    assert report["moved_file_count"] == 2
    assert report["moved_episode_numbers"] == [3, 4]
    assert report["queue_rows_removed"] == 2
    assert report["removed_queue_episode_numbers"] == [3, 4]
    assert delete_calls == [[101, 102]]
    assert (season_dir / ep3.name).exists()
    assert (season_dir / ep4.name).exists()
    assert not ep3.exists()
    assert not ep4.exists()
    assert written["status"] == "repaired"
    assert "queue_removed=2" in str(report["operator_text"])


def test_repair_sonarr_tv_season_imports_from_multiple_candidates(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    series_root = tmp_path / "library" / "LEGO Ninjago - Dragons Rising"
    staging_root = tmp_path / "staging"
    ep4_candidate = staging_root / "LEGO.Ninjago.Dragons.Rising.S02E04.1080p.WEB.h264-DOLORES[EZTVx.to].mkv"
    ep8_candidate = staging_root / "LEGO.Ninjago.Dragons.Rising.S02E08.1080p.WEB.h264-DOLORES[EZTVx.to].mkv"
    ep4_candidate.parent.mkdir(parents=True, exist_ok=True)
    ep4_candidate.write_text("ep4", encoding="utf-8")
    ep8_candidate.write_text("ep8", encoding="utf-8")
    config_path = tmp_path / "sonarr-config.xml"
    config_path.write_text("<Config><ApiKey>abc123</ApiKey></Config>", encoding="utf-8")

    pre_probe = {
        "probe_ok": True,
        "ready": False,
        "status": "blocked_staging_import_available",
        "reason": "sonarr_missing_episodes_have_staging_candidate",
        "next_action": "repair_sonarr_tv_season",
        "series_id": 36,
        "series_title": "LEGO Ninjago: Dragons Rising",
        "series_path": str(series_root),
        "season_folder": True,
        "season_number": 2,
        "missing_episode_numbers": [4, 8],
        "missing_episode_ids": [13506, 13510],
        "metadata_queue_episode_numbers": [],
        "staging_candidates": [
            {
                "name": ep4_candidate.name,
                "path": str(ep4_candidate),
                "cover_count": 1,
                "valid_cover_count": 1,
            },
            {
                "name": ep8_candidate.name,
                "path": str(ep8_candidate),
                "cover_count": 1,
                "valid_cover_count": 1,
            },
        ],
        "selected_staging_candidate": {
            "name": ep4_candidate.name,
            "path": str(ep4_candidate),
            "cover_count": 1,
            "valid_cover_count": 1,
        },
    }
    post_probe = {
        "probe_ok": True,
        "ready": True,
        "status": "ready",
        "reason": "",
        "next_action": "",
        "series_id": 36,
        "series_title": "LEGO Ninjago: Dragons Rising",
        "series_path": str(series_root),
        "season_folder": True,
        "season_number": 2,
        "have_episode_numbers": [4, 8],
        "missing_episode_numbers": [],
        "missing_episode_ids": [],
        "unreadable_episode_numbers": [],
        "metadata_queue_episode_numbers": [],
        "metadata_queue_items": [],
    }
    probes = iter([pre_probe, post_probe])
    written: dict[str, object] = {}

    monkeypatch.setattr(module, "probe_sonarr_tv_season", lambda **_kwargs: dict(next(probes)))
    monkeypatch.setattr(module, "_read_xml_api_key", lambda _path: "abc123")
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T15:00:00Z")
    monkeypatch.setattr(module, "_write_private_json", lambda _path, payload: written.update(dict(payload)))
    monkeypatch.setattr(module, "_sonarr_list_queue", lambda **_kwargs: [])
    monkeypatch.setattr(
        module,
        "_sonarr_probe_file_playability",
        lambda path, timeout_seconds: {
            "path": str(path),
            "ok": True,
            "probed": True,
            "method": "ffprobe",
            "reason": "",
            "detail": "h264",
        },
    )
    monkeypatch.setattr(module, "_sonarr_request_command", lambda **_kwargs: {"ok": True, "command_id": 41, "status": "completed", "attempts": 1})

    report = module.repair_sonarr_tv_season(
        series_id=36,
        season_number=2,
        sonarr_base_url="http://127.0.0.1:8989",
        sonarr_config_path=str(config_path),
        staging_root=str(staging_root),
        timeout_seconds=5.0,
        output_format="json",
    )

    season_dir = series_root / "Season 2"
    assert report["status"] == "repaired"
    assert report["moved_file_count"] == 2
    assert report["moved_episode_numbers"] == [4, 8]
    assert (season_dir / ep4_candidate.name).exists()
    assert (season_dir / ep8_candidate.name).exists()
    assert written["status"] == "repaired"


def test_repair_sonarr_tv_season_reports_ready_without_changes(monkeypatch) -> None:
    module = _module()
    probe = {
        "probe_ok": True,
        "ready": True,
        "status": "ready",
        "reason": "",
        "next_action": "",
        "series_id": 36,
        "series_title": "LEGO Ninjago: Dragons Rising",
        "season_number": 2,
        "missing_episode_numbers": [],
        "metadata_queue_episode_numbers": [],
        "series_path": "/mnt/pcloud/PLEX/Requested/TV/LEGO Ninjago - Dragons Rising",
        "season_folder": True,
    }
    written: dict[str, object] = {}
    monkeypatch.setattr(module, "probe_sonarr_tv_season", lambda **_kwargs: dict(probe))
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T15:00:00Z")
    monkeypatch.setattr(module, "_write_private_json", lambda _path, payload: written.update(dict(payload)))

    report = module.repair_sonarr_tv_season(
        series_id=36,
        season_number=2,
        timeout_seconds=5.0,
        output_format="json",
    )

    assert report["status"] == "ready"
    assert report["ready"] is True
    assert report["moved_file_count"] == 0
    assert report["queue_rows_removed"] == 0
    assert written["status"] == "ready"


def test_repair_sonarr_tv_season_quarantines_unreadable_file_and_requests_search(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    series_root = tmp_path / "library" / "LEGO Ninjago - Dragons Rising"
    season_dir = series_root / "Season 2"
    season_dir.mkdir(parents=True)
    bad_file = season_dir / "LEGO.Ninjago.Dragons.Rising.S02E03.Beyond.the.Phantasm.Cave.1080p.NF.WEB-DL.mkv"
    bad_file.write_text("broken", encoding="utf-8")
    config_path = tmp_path / "sonarr-config.xml"
    config_path.write_text("<Config><ApiKey>abc123</ApiKey></Config>", encoding="utf-8")

    pre_probe = {
        "probe_ok": True,
        "ready": False,
        "status": "blocked_unreadable_episode_files",
        "reason": "sonarr_unreadable_episode_files",
        "next_action": "repair_sonarr_tv_season",
        "series_id": 36,
        "series_title": "LEGO Ninjago: Dragons Rising",
        "series_path": str(series_root),
        "season_folder": True,
        "season_number": 2,
        "missing_episode_numbers": [],
        "missing_episode_ids": [],
        "media_info_missing_episode_numbers": [3],
        "unreadable_episode_numbers": [3],
        "selected_staging_candidate": {},
    }
    post_probe = {
        "probe_ok": True,
        "ready": False,
        "status": "blocked_missing_episodes",
        "reason": "sonarr_missing_episodes",
        "next_action": "search_sonarr_missing_episodes",
        "series_id": 36,
        "series_title": "LEGO Ninjago: Dragons Rising",
        "series_path": str(series_root),
        "season_folder": True,
        "season_number": 2,
        "have_episode_numbers": [1, 2],
        "missing_episode_numbers": [3],
        "missing_episode_ids": [13505],
        "unreadable_episode_numbers": [],
        "metadata_queue_episode_numbers": [],
        "metadata_queue_items": [],
    }
    final_probe = dict(post_probe)
    probes = iter([pre_probe, post_probe, final_probe])
    written: dict[str, object] = {}

    monkeypatch.setattr(module, "probe_sonarr_tv_season", lambda **_kwargs: dict(next(probes)))
    monkeypatch.setattr(module, "_read_xml_api_key", lambda _path: "abc123")
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T15:00:00Z")
    monkeypatch.setattr(module, "_write_private_json", lambda _path, payload: written.update(dict(payload)))
    monkeypatch.setattr(module, "_sonarr_list_queue", lambda **_kwargs: [])

    def _fake_request(**kwargs):
        body = dict(kwargs.get("body") or {})
        match body.get("name"):
            case "RefreshSeries":
                return {"id": 41}
            case "RescanSeries":
                return {"id": 42}
            case "EpisodeSearch":
                return {"id": 43}
        raise AssertionError(body)

    monkeypatch.setattr(module, "_sonarr_request_json_value", _fake_request)
    monkeypatch.setattr(module, "_sonarr_wait_for_command", lambda **_kwargs: {"status": "completed"})

    report = module.repair_sonarr_tv_season(
        series_id=36,
        season_number=2,
        sonarr_base_url="http://127.0.0.1:8989",
        sonarr_config_path=str(config_path),
        staging_root=str(tmp_path / "staging"),
        timeout_seconds=5.0,
        output_format="operator",
    )

    quarantine_dir = Path(str(report["quarantine_dir"]))
    assert report["status"] == "recovery_in_progress"
    assert report["ready"] is False
    assert report["quarantined_file_count"] == 1
    assert report["quarantined_episode_numbers"] == [3]
    assert report["refresh_requested"] is True
    assert report["refresh_status"] == "completed"
    assert report["rescan_requested"] is True
    assert report["rescan_status"] == "completed"
    assert report["search_requested"] is True
    assert report["search_status"] == "completed"
    assert report["search_episode_numbers"] == [3]
    assert report["next_action"] == "wait_for_download_client_or_reprobe_sonarr_tv_season"
    assert not bad_file.exists()
    assert quarantine_dir.exists()


def test_repair_sonarr_tv_season_replaces_metadata_only_queue_with_viable_release(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    config_path = tmp_path / "sonarr-config.xml"
    config_path.write_text("<Config><ApiKey>abc123</ApiKey></Config>", encoding="utf-8")

    pre_probe = {
        "probe_ok": True,
        "ready": False,
        "status": "ready_with_recovery_action",
        "reason": "sonarr_metadata_queue_downloading_metadata",
        "next_action": "wait_for_download_client_or_reprobe_sonarr_tv_season",
        "series_id": 36,
        "series_title": "LEGO Ninjago: Dragons Rising",
        "series_path": str(tmp_path / "library" / "LEGO Ninjago - Dragons Rising"),
        "season_folder": True,
        "season_number": 2,
        "missing_episode_numbers": [11],
        "missing_episode_ids": [13513],
        "metadata_queue_episode_numbers": [11],
        "metadata_queue_items": [
            {
                "id": 201,
                "episode_number": 11,
                "episode_has_file": False,
                "is_stale": False,
            }
        ],
    }
    post_probe = dict(pre_probe)
    replacement_probe = {
        "probe_ok": True,
        "ready": False,
        "status": "blocked_missing_episodes",
        "reason": "sonarr_missing_episodes",
        "next_action": "search_sonarr_missing_episodes",
        "series_id": 36,
        "series_title": "LEGO Ninjago: Dragons Rising",
        "series_path": str(tmp_path / "library" / "LEGO Ninjago - Dragons Rising"),
        "season_folder": True,
        "season_number": 2,
        "missing_episode_numbers": [11],
        "missing_episode_ids": [13513],
        "metadata_queue_episode_numbers": [],
        "metadata_queue_items": [],
    }
    probes = iter([pre_probe, post_probe, replacement_probe])
    written: dict[str, object] = {}
    queue_snapshots = iter(
        [
            [
                {
                    "id": 201,
                    "seriesId": 36,
                    "downloadId": "D6836FE76CBC4F040804284D20DBC199F342F9D2",
                    "trackedDownloadState": "downloading",
                    "errorMessage": "qBittorrent is downloading metadata",
                    "added": "2026-07-05T15:45:00Z",
                    "episode": {"id": 13513, "seasonNumber": 2, "episodeNumber": 11},
                }
            ],
            [
                {
                    "id": 301,
                    "seriesId": 36,
                    "downloadId": "AABBCCDDEEFF00112233445566778899AABBCCDD",
                    "trackedDownloadState": "downloading",
                    "errorMessage": "",
                    "added": "2026-07-05T16:16:00Z",
                    "episode": {"id": 13513, "seasonNumber": 2, "episodeNumber": 11},
                }
            ],
        ]
    )
    delete_calls: list[dict[str, object]] = []
    grab_calls: list[str] = []

    monkeypatch.setattr(module, "probe_sonarr_tv_season", lambda **_kwargs: dict(next(probes)))
    monkeypatch.setattr(module, "_read_xml_api_key", lambda _path: "abc123")
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T16:20:00Z")
    monkeypatch.setattr(module, "_write_private_json", lambda _path, payload: written.update(dict(payload)))
    monkeypatch.setattr(module, "_sonarr_list_queue", lambda **_kwargs: list(next(queue_snapshots)))
    monkeypatch.setattr(
        module,
        "_sonarr_list_releases_for_episode",
        lambda **_kwargs: [
            {
                "title": "LEGO.Ninjago.Dragons.Rising.S02E11.1080p.WEB.h264-DOLORES",
                "mappedSeasonNumber": 2,
                "mappedEpisodeNumbers": [11],
                "downloadAllowed": True,
                "rejections": ["Release in queue already meets cutoff: WEBDL-1080p v1"],
                "seeders": 1,
                "qualityWeight": 1200,
                "quality": {"quality": {"resolution": 1080}},
                "size": 948654464,
                "infoHash": "d6836fe76cbc4f040804284d20dbc199f342f9d2",
            },
            {
                "title": "LEGO Ninjago Dragons Rising S02E11 1080p HEVC x265 MeGusta EZTV",
                "mappedSeasonNumber": 2,
                "mappedEpisodeNumbers": [11],
                "downloadAllowed": True,
                "rejections": ["Release in queue already meets cutoff: WEBDL-1080p v1"],
                "seeders": 25,
                "qualityWeight": 900,
                "quality": {"quality": {"resolution": 1080}},
                "size": 340444640,
                "infoHash": "aabbccddeeff00112233445566778899aabbccdd",
            },
        ],
    )
    monkeypatch.setattr(
        module,
        "_sonarr_delete_queue_rows",
        lambda **kwargs: delete_calls.append(dict(kwargs)) or {"ok": True, "removed_count": len(kwargs["queue_ids"])},
    )
    monkeypatch.setattr(
        module,
        "_sonarr_grab_release",
        lambda **kwargs: grab_calls.append(str(kwargs["release"]["title"])) or {"ok": True, "response": {}},
    )
    monkeypatch.setattr(module, "_sonarr_request_command", lambda **_kwargs: {"ok": True, "command_id": 41, "status": "completed", "attempts": 1})

    report = module.repair_sonarr_tv_season(
        series_id=36,
        season_number=2,
        sonarr_base_url="http://127.0.0.1:8989",
        sonarr_config_path=str(config_path),
        staging_root=str(tmp_path / "staging"),
        timeout_seconds=5.0,
        output_format="json",
    )

    assert report["status"] == "recovery_in_progress"
    assert report["reason"] == "sonarr_missing_episodes_already_queued"
    assert report["next_action"] == "wait_for_download_client_or_reprobe_sonarr_tv_season"
    assert report["replacement_grab_count"] == 1
    assert report["replacement_episode_numbers"] == [11]
    assert report["search_requested"] is False
    assert report["queued_missing_episode_numbers_after"] == [11]
    assert delete_calls == [
        {
            "base_url": "http://127.0.0.1:8989",
            "api_key": "abc123",
            "queue_ids": [201],
            "timeout_seconds": 5.0,
            "blocklist": True,
            "skip_redownload": True,
        }
    ]
    assert grab_calls == ["LEGO Ninjago Dragons Rising S02E11 1080p HEVC x265 MeGusta EZTV"]
    assert written["replacement_grab_count"] == 1
    assert written["status"] == "recovery_in_progress"


def test_repair_mymedia_public_surface_uses_private_runtime_defaults_when_env_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    defaults_path = tmp_path / "mymedia-runtime-defaults.json"
    defaults_path.write_text(
        json.dumps(
            {
                "access_emails": "ops@example.test,backup@example.test",
                "cloudflare_exception_base_hosts": "home.girschele.com,photos.girschele.com",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_RUNTIME_DEFAULTS_PATH", str(defaults_path))
    monkeypatch.delenv("EA_MYMEDIA_ALEXA_ACCESS_EMAILS", raising=False)
    monkeypatch.delenv("EA_MYMEDIA_ALEXA_CLOUDFLARE_EXCEPTION_BASE_HOSTS", raising=False)
    before = {
        "configured": True,
        "base_url_scope": "public",
        "probe_attempted": True,
        "ready": False,
        "status": "blocked_by_cloudflare",
        "reason": "mymedia_public_console_blocked_by_cloudflare",
        "next_action": "repair_mymedia_public_console_route",
        "next_action_href": "https://mymedia.girschele.com",
        "next_action_label": "Open public My Media URL",
        "next_action_method": "get",
    }
    after = dict(before)
    after.update(
        {
            "ready": True,
            "status": "access_protected",
            "reason": "",
            "next_action": "",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
        }
    )
    probes = iter([before, after])
    captured: dict[str, object] = {}
    monkeypatch.setattr(module, "_mymedia_public_surface_probe", lambda *_args, **_kwargs: next(probes))
    monkeypatch.setattr(module, "_cloudflare_auth_ready", lambda: True)
    monkeypatch.setattr(
        module,
        "_cloudflare_lookup_zone_for_host",
        lambda hostname, **_kwargs: {
            "ok": True,
            "zone_id": "zone-1",
            "account_id": "account-1",
            "zone_name": "girschele.com",
        },
    )
    monkeypatch.setattr(
        module,
        "_cloudflare_lookup_named_tunnel",
        lambda account_id, tunnel_name, **_kwargs: {
            "ok": True,
            "tunnel_id": "tunnel-1",
            "tunnel_domain": "tunnel-1.cfargotunnel.com",
        },
    )
    monkeypatch.setattr(
        module,
        "_cloudflare_upsert_dns_record",
        lambda zone_id, **_kwargs: {"ok": True, "changed": False, "record_present": True},
    )
    monkeypatch.setattr(
        module,
        "_cloudflare_upsert_tunnel_ingress",
        lambda account_id, tunnel_id, **_kwargs: {"ok": True, "changed": False, "route_present": True},
    )
    monkeypatch.setattr(
        module,
        "_cloudflare_lookup_access_service_token",
        lambda account_id, **_kwargs: {"ok": True, "service_token_id": "token-1", "service_token_name": "CodexLiz"},
    )

    def _fake_access_app(zone_id, **kwargs):
        captured["access_emails_csv"] = kwargs["access_emails_csv"]
        return {"ok": True, "changed": False, "app_present": True}

    def _fake_firewall(zone_id, **kwargs):
        captured["required_existing_hosts"] = list(kwargs["required_existing_hosts"])
        return {"ok": True, "changed": False, "patched_rule_count": 0}

    monkeypatch.setattr(module, "_cloudflare_upsert_access_app", _fake_access_app)
    monkeypatch.setattr(module, "_cloudflare_patch_private_host_block_exceptions", _fake_firewall)
    monkeypatch.setattr(module.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_write_private_json", lambda *_args, **_kwargs: None)

    report = module.repair_mymedia_public_surface(
        web_base_url="http://127.0.0.1:52051",
        public_web_base_url="https://mymedia.girschele.com",
        timeout_seconds=5.0,
        output_format="json",
    )

    assert report["status"] == "ready"
    assert captured["access_emails_csv"] == "ops@example.test,backup@example.test"
    assert captured["required_existing_hosts"] == ["home.girschele.com", "photos.girschele.com"]


def test_probe_mymedia_alexa_embeds_optional_public_surface_probe(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    data_dir = tmp_path / "mymedia-data"
    data_dir.mkdir()
    (data_dir / "Preferences.xml").write_text(
        """<?xml version="1.0"?>
<DynamicConfiguration>
  <RefreshToken>refresh-token-secret</RefreshToken>
  <AllowExternalAccess>2</AllowExternalAccess>
</DynamicConfiguration>
""",
        encoding="utf-8",
    )
    (data_dir / "Messages.xml").write_text("""<?xml version="1.0"?><ArrayOfEntry />\n""", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "_docker_inspect_container_json",
        lambda *_args, **_kwargs: {
            "State": {"Running": True, "Status": "running"},
            "Mounts": [{"Destination": "/datadir", "Source": str(data_dir)}],
        },
    )

    def _fake_api(url: str, **_kwargs):
        if url.endswith("/api/Summary"):
            return True, {"GetSummaryInfoResult": {"Tracks": 12, "Albums": 1, "Artists": 1, "Genres": 1, "ConnectionStatus": 2}}, 200, ""
        if url.endswith("/api/WatchFolders"):
            return True, {"GetWatchFoldersResult": [{"Status": 4, "Errors": 0}]}, 200, ""
        if url.endswith("/api/Login"):
            return True, {"GetMyMediaLoginResult": "paired-user"}, 200, ""
        raise AssertionError(url)

    monkeypatch.setattr(module, "_mymedia_api_json", _fake_api)
    monkeypatch.setattr(
        module,
        "_mymedia_public_surface_probe",
        lambda *args, **_kwargs: {
            "configured": True,
            "base_url_scope": "public",
            "probe_attempted": True,
            "ready": False,
            "status": "blocked_by_cloudflare",
            "reason": "mymedia_public_console_blocked_by_cloudflare",
            "http_status_code": 403,
            "access_protected": False,
            "cloudflare_blocked": True,
            "redirect_host": "",
            "content_type": "text/html; charset=UTF-8",
            "next_action": "repair_mymedia_public_console_route",
            "next_action_href": "https://mymedia.girschele.com",
            "next_action_label": "Open public My Media URL",
            "next_action_method": "get",
            "source": "http.public_surface_probe",
        },
    )

    report = module.probe_mymedia_alexa(
        container_name="mymediaalexa",
        web_base_url="http://127.0.0.1:52051",
        public_web_base_url="https://mymedia.girschele.com",
        timeout_seconds=5.0,
        output_format="operator",
    )

    assert report["ready"] is True
    assert report["status"] == "ready_library_scan_in_progress"
    assert report["public_surface_configured"] is True
    assert report["public_surface_ready"] is False
    assert report["public_surface_status"] == "blocked_by_cloudflare"
    assert report["public_surface_reason"] == "mymedia_public_console_blocked_by_cloudflare"
    assert report["public_surface_http_status_code"] == 403
    assert "public_surface_status=blocked_by_cloudflare" in str(report["operator_text"])


def test_mymedia_pairing_surface_kind_classifies_setup_login_route_selection_and_waiting_states() -> None:
    module = _module()

    setup = module._mymedia_pairing_surface_kind(
        "http://127.0.0.1:52051/index.html#!/setup",
        "Welcome to My Media for Alexa. pair your server with the primary Amazon account you use on your Alexa device.",
    )
    password = module._mymedia_pairing_surface_kind(
        "https://na.account.amazon.com/ap/signin",
        "Sign in archon.megalon@gmail.com Change Password Forgot password? Sign in with a passkey",
    )
    route_selection = module._mymedia_pairing_surface_kind(
        "https://na.account.amazon.com/ap/mfa/new-otp?ie=UTF8&arb=fixture",
        "Two-Step Verification Choose where you'd like to receive or generate the code. Send OTP",
    )
    waiting = module._mymedia_pairing_surface_kind(
        "https://na.account.amazon.com/ap/mfa?ie=UTF8&arb=fixture",
        "Look on WhatsApp for a message with your security code. Two-Step Verification Enter code",
    )

    assert setup["kind"] == "setup_intro"
    assert password["kind"] == "amazon_signin"
    assert route_selection["kind"] == "mfa_route_selection"
    assert waiting["kind"] == "waiting_for_code"
    assert waiting["invalid_code"] is False


def test_mymedia_pairing_wait_for_visible_selector_retries_until_password_field_appears(monkeypatch) -> None:
    module = _module()
    state = {"tick": 0}

    class _FakeLocator:
        def __init__(self, selector: str) -> None:
            self.selector = selector

        @property
        def first(self) -> "_FakeLocator":
            return self

        def is_visible(self, timeout: int = 0) -> bool:
            return self.selector == "input#ap_password" and state["tick"] >= 1

    class _FakePage:
        def locator(self, selector: str) -> _FakeLocator:
            return _FakeLocator(selector)

        def wait_for_timeout(self, _milliseconds: int) -> None:
            state["tick"] += 1

    monkeypatch.setattr(module.time, "monotonic", lambda: state["tick"] * 0.1)

    selector = module._mymedia_pairing_wait_for_visible_selector(
        _FakePage(),
        ("input[name='password']", "input#ap_password", "input[type='password']"),
        timeout_seconds=2.0,
    )

    assert selector == "input#ap_password"


def test_mymedia_action_surface_maps_code_and_consent_recovery_to_setup_page() -> None:
    module = _module()

    code_href, code_label, code_method = module._mymedia_action_surface(
        base_url="http://127.0.0.1:52051",
        next_action="enter_mymedia_amazon_pairing_code",
    )
    consent_href, consent_label, consent_method = module._mymedia_action_surface(
        base_url="http://127.0.0.1:52051",
        next_action="approve_mymedia_amazon_consent",
    )

    assert code_href == "http://127.0.0.1:52051/index.html#!/setup"
    assert code_label == "Open My Media setup"
    assert code_method == "get"
    assert consent_href == "http://127.0.0.1:52051/index.html#!/setup"
    assert consent_label == "Open My Media setup"
    assert consent_method == "get"


def test_mymedia_action_surface_maps_wait_for_scan_to_watch_folders_page() -> None:
    module = _module()

    href, label, method = module._mymedia_action_surface(
        base_url="http://127.0.0.1:52051",
        next_action="wait_for_mymedia_library_scan",
    )

    assert href == "http://127.0.0.1:52051/index.html#!/tables"
    assert label == "Open Watch Folders"
    assert method == "get"


def test_mymedia_pairing_route_matches_channel_and_suffix() -> None:
    module = _module()

    assert module._mymedia_pairing_route_matches(
        "Send me a WhatsApp message to my number ending in 419",
        otp_channel="whatsapp",
        phone_suffix="419",
    )
    assert module._mymedia_pairing_route_matches(
        "Eine SMS an meine Telefonnummer schicken, die auf 777 endet",
        otp_channel="sms",
        phone_suffix="777",
    )
    assert module._mymedia_pairing_route_matches(
        "Text me at my number ending in 777",
        otp_channel="sms",
        phone_suffix="777",
    )
    assert module._mymedia_pairing_route_matches(
        "Unter meiner Nummer anrufen, die auf 419 endet",
        otp_channel="call",
        phone_suffix="419",
    )
    assert not module._mymedia_pairing_route_matches(
        "Send me a WhatsApp message to my number ending in 777",
        otp_channel="whatsapp",
        phone_suffix="419",
    )


def test_mymedia_pairing_route_request_issue_surfaces_cooldown_and_sms_unavailable() -> None:
    module = _module()

    cooldown = module._mymedia_pairing_route_request_issue(
        "There was a problem. Please wait at least one minute before requesting another code.",
        otp_channel="sms",
        phone_suffix="777",
    )
    assert cooldown == {
        "status": "blocked_pairing_code_request_cooldown",
        "reason": "mymedia_pairing_code_request_cooldown",
        "next_action": "wait_before_retrying_mymedia_pairing_code",
        "blockers": ["mfa_code_request_cooldown"],
    }

    unavailable = module._mymedia_pairing_route_request_issue(
        "For added security, we need to verify your phone number. We are unable to send an SMS to the phone number ending with 777 at this time.",
        otp_channel="sms",
        phone_suffix="777",
    )
    assert unavailable == {
        "status": "blocked_pairing_route_unavailable",
        "reason": "mymedia_pairing_route_unavailable",
        "next_action": "switch_mymedia_pairing_route",
        "blockers": ["mfa_route_unavailable"],
        "failed_route": "sms:*777",
    }


def test_mymedia_pairing_session_status_marks_waiting_bundle_resumable(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    pairing_dir = tmp_path / "mymedia-pairing"
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_DIR", str(pairing_dir))
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_SESSION_MAX_AGE_SECONDS", "1800")
    pairing_dir.mkdir(parents=True, exist_ok=True)
    (pairing_dir / "storage_state.json").write_text("{}", encoding="utf-8")
    (pairing_dir / "session.json").write_text(
        json.dumps(
            {
                "resume_url": "https://na.account.amazon.com/ap/cvf",
                "otp_channel": "whatsapp",
                "phone_suffix": "419",
                "surface_kind": "waiting_for_code",
                "captured_at": "2026-07-04T12:35:00Z",
            }
        ),
        encoding="utf-8",
    )

    status = module._mymedia_pairing_session_status(
        now=datetime.fromisoformat("2026-07-04T12:45:00+00:00"),
    )

    assert status["pending_surface"] is True
    assert status["resume_ready"] is True
    assert status["stale"] is False
    assert status["surface_kind"] == "waiting_for_code"
    assert status["age_seconds"] == 600


def test_mymedia_pairing_preserve_previous_actionable_handoff_restores_waiting_bundle(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    pairing_dir = tmp_path / "mymedia-pairing"
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_DIR", str(pairing_dir))
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_SESSION_MAX_AGE_SECONDS", "1800")
    pairing_dir.mkdir(parents=True, exist_ok=True)
    original_state = b'{"cookies":[{"name":"session"}]}'
    original_session = json.dumps(
        {
            "resume_url": "https://na.account.amazon.com/ap/cvf",
            "otp_channel": "whatsapp",
            "phone_suffix": "419",
            "surface_kind": "waiting_for_code",
            "site": "na.account.amazon.com",
            "current_path": "/ap/mfa",
            "captured_at": "2026-07-04T14:40:50Z",
        }
    ).encode("utf-8")
    original_screenshot = b"old-surface"
    (pairing_dir / "storage_state.json").write_bytes(original_state)
    (pairing_dir / "session.json").write_bytes(original_session)
    (pairing_dir / "surface.png").write_bytes(original_screenshot)

    snapshot = module._mymedia_pairing_capture_existing_resume_bundle(
        now=datetime.fromisoformat("2026-07-04T14:41:00+00:00")
    )
    assert snapshot["resume_ready"] is True

    (pairing_dir / "storage_state.json").write_bytes(b'{"cookies":[]}')
    (pairing_dir / "session.json").write_text(
        json.dumps(
            {
                "resume_url": "https://na.account.amazon.com/ap/mfa/new-otp",
                "otp_channel": "sms",
                "phone_suffix": "777",
                "surface_kind": "mfa_route_selection",
                "site": "na.account.amazon.com",
                "current_path": "/ap/mfa/new-otp",
                "captured_at": "2026-07-04T14:41:05Z",
            }
        ),
        encoding="utf-8",
    )
    (pairing_dir / "surface.png").write_bytes(b"new-surface")

    report = module._mymedia_pairing_preserve_previous_actionable_handoff(
        {
            "status": "blocked_pairing_route_unavailable",
            "reason": "mymedia_pairing_route_unavailable",
            "surface_kind": "mfa_route_selection",
            "selected_route": "sms:*777",
            "failed_route": "sms:*777",
            "state_written": True,
            "session_written": True,
            "screenshot_written": True,
        },
        previous_bundle=snapshot,
        web_base_url="http://127.0.0.1:52051",
        observed_at="2026-07-04T14:41:06Z",
        output_dir="",
        now=datetime.fromisoformat("2026-07-04T14:41:06+00:00"),
    )

    assert report["status"] == "waiting_for_code"
    assert report["reason"] == "mfa_code_requested"
    assert report["otp_channel"] == "whatsapp"
    assert report["phone_suffix"] == "419"
    assert report["pairing_resume_ready"] is True
    assert report["previous_actionable_handoff_preserved"] is True
    assert report["attempt_status"] == "blocked_pairing_route_unavailable"
    assert report["attempt_failed_route"] == "sms:*777"
    assert report["source"] == "mymedia_setup.saved_session_preserved"
    assert (pairing_dir / "storage_state.json").read_bytes() == original_state
    assert json.loads((pairing_dir / "session.json").read_text(encoding="utf-8"))["surface_kind"] == "waiting_for_code"
    assert (pairing_dir / "surface.png").read_bytes() == original_screenshot


def test_provider_display_name_uses_storage_free_catalog(monkeypatch) -> None:
    module = _module()
    module._catalog_provider_registry.cache_clear()
    seen: dict[str, object] = {}

    class _State:
        display_name = "Pushbullet"

    class _Registry:
        def binding_state(self, provider_key: str):
            seen["provider_key"] = provider_key
            return _State()

    monkeypatch.setattr(module, "ProviderRegistryService", _Registry)

    try:
        assert module._provider_display_name("pushbullet") == "Pushbullet"
        assert seen["provider_key"] == "pushbullet"
    finally:
        module._catalog_provider_registry.cache_clear()


def test_probe_provider_prefers_runtime_container_state(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_runtime_container_provider_state",
        lambda provider_key, **_kwargs: (
            {
                "ok": True,
                "provider_key": provider_key,
                "display_name": "Teable",
                "state": "configured",
                "status": "enabled",
                "enabled": True,
                "executable": False,
                "health_state": "pass",
                "capabilities": ["operator_projection"],
                "updated_at": "2026-08-12T04:00:00Z",
            },
            "ea-api",
            "",
        ),
    )

    report = module.probe_provider("teable", output_format="json")

    assert report["status"] == "configured"
    assert report["source"] == "runtime_container_exec:ea-api:provider_registry.binding_state"
    assert report["raw"]["health_state"] == "pass"
    assert report["raw"]["runtime_fallback_reason"] == ""
    assert report["raw"]["raw_credentials_exposed"] is False


def test_probe_provider_tough_tongue_uses_read_only_balance_probe(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "probe_tough_tongue_balance",
        lambda **_kwargs: {
            "provider_key": "tough_tongue",
            "display_name": "Tough Tongue AI",
            "status": "ready",
            "remaining": 400.0,
            "unit": "available_minutes",
            "refresh_at": "2026-08-14T12:00:00Z",
            "observed_at": "2026-08-14T12:01:00Z",
            "account_label": "Tier 4",
            "source": "tough_tongue_public_api:GET /balance",
            "probe_ok": True,
            "ready": True,
            "reason": "",
            "next_action": "",
            "raw": {"raw_credentials_exposed": False},
        },
    )

    report = module.probe_provider("ToughTongueAI.com", output_format="operator")

    assert report["provider_key"] == "tough_tongue"
    assert report["status"] == "ready"
    assert report["remaining"] == 400.0
    assert report["source"] == "tough_tongue_public_api:GET /balance"
    assert "remaining=400.0 available_minutes" in report["operator_text"]
    assert report["raw"]["raw_credentials_exposed"] is False


def test_probe_provider_falls_back_to_catalog_without_bootstrapping_database(monkeypatch) -> None:
    module = _module()
    module._catalog_provider_registry.cache_clear()
    monkeypatch.setattr(
        module,
        "_runtime_container_provider_state",
        lambda provider_key, **_kwargs: ({}, "ea-api", "runtime_container_exec_exit_1"),
    )

    def _database_bootstrap_forbidden(*_args, **_kwargs):
        raise AssertionError("generic provider fallback must not bootstrap the application database")

    monkeypatch.setattr(module, "build_container", _database_bootstrap_forbidden)
    try:
        report = module.probe_provider("teable", output_format="json")
    finally:
        module._catalog_provider_registry.cache_clear()

    assert report["source"] == "host_catalog_fallback:provider_registry.binding_state"
    assert report["raw"]["runtime_container"] == "ea-api"
    assert report["raw"]["runtime_fallback_reason"] == "runtime_container_exec_exit_1"
    assert report["raw"]["raw_credentials_exposed"] is False


def test_trigger_mymedia_amazon_pairing_dry_run_reports_operator_safe_handoff(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-04T12:30:00Z")
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "pairing_ready": False,
            "status": "blocked_pairing_required",
        },
    )

    report = module.trigger_mymedia_amazon_pairing(
        web_base_url="http://127.0.0.1:52051",
        otp_channel="whatsapp",
        phone_suffix="419",
        dry_run=True,
        output_format="operator",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "dry_run"
    assert report["next_action"] == "request_mymedia_pairing_code"
    assert report["otp_channel"] == "whatsapp"
    assert report["phone_suffix"] == "419"
    assert "mymedia_pairing status=dry_run" in str(report["operator_text"])


def test_trigger_mymedia_amazon_pairing_uses_private_runtime_defaults_when_env_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    defaults_path = tmp_path / "mymedia-runtime-defaults.json"
    defaults_path.write_text(
        json.dumps(
            {
                "amazon_otp_channel": "sms",
                "amazon_phone_suffix": "777",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_RUNTIME_DEFAULTS_PATH", str(defaults_path))
    monkeypatch.delenv("EA_MYMEDIA_ALEXA_AMAZON_OTP_CHANNEL", raising=False)
    monkeypatch.delenv("EA_MYMEDIA_ALEXA_AMAZON_PHONE_SUFFIX", raising=False)
    monkeypatch.delenv("AMAZON_OTP_CHANNEL", raising=False)
    monkeypatch.delenv("AMAZON_OTP_SUFFIX", raising=False)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-04T12:30:00Z")
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "pairing_ready": False,
            "status": "blocked_pairing_required",
        },
    )

    report = module.trigger_mymedia_amazon_pairing(
        web_base_url="http://127.0.0.1:52051",
        dry_run=True,
        output_format="json",
    )

    assert report["status"] == "dry_run"
    assert report["otp_channel"] == "sms"
    assert report["phone_suffix"] == "777"


def test_send_mymedia_amazon_pairing_telegram_reuses_saved_waiting_session(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    pairing_dir = tmp_path / "mymedia-pairing"
    pairing_dir.mkdir(parents=True, exist_ok=True)
    (pairing_dir / "storage_state.json").write_text("{}", encoding="utf-8")
    (pairing_dir / "session.json").write_text(
        json.dumps(
            {
                "resume_url": "https://na.account.amazon.com/ap/cvf",
                "otp_channel": "sms",
                "phone_suffix": "419",
                "surface_kind": "waiting_for_code",
                "site": "na.account.amazon.com",
                "current_path": "/ap/mfa",
                "captured_at": "2026-07-04T13:35:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_DIR", str(pairing_dir))
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_SESSION_MAX_AGE_SECONDS", "1800")
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-04T13:40:00Z")
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "pairing_ready": False,
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
        },
    )
    sent: dict[str, object] = {}

    def _fake_send_telegram(*, principal_id: str, text: str, dry_run: bool, timeout_seconds: float) -> dict[str, object]:
        sent.update(
            {
                "principal_id": principal_id,
                "text": text,
                "dry_run": dry_run,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {
            "sent": True,
            "reason": "sent",
            "principal_id": principal_id,
            "message_count": 1,
            "chat_ref_present": True,
            "chat_ref_sha256": "abc123",
        }

    monkeypatch.setattr(module, "send_telegram", _fake_send_telegram)
    monkeypatch.setattr(
        module,
        "trigger_mymedia_amazon_pairing",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should reuse saved handoff")),
    )

    report = module.send_mymedia_amazon_pairing_telegram(
        web_base_url="http://127.0.0.1:52051",
        otp_channel="sms",
        phone_suffix="419",
        telegram_principal_id="cf-email:tibor.girschele@gmail.com",
        output_format="operator",
        telegram_operator_streams="media",
    )

    assert report["status"] == "waiting_for_code"
    assert report["next_action"] == "enter_mymedia_amazon_pairing_code"
    assert report["pairing_resume_ready"] is True
    assert report["telegram_sent"] is True
    assert report["source"] == "mymedia_setup.saved_session"
    assert sent["principal_id"] == "cf-email:tibor.girschele@gmail.com"
    assert "Reply in Codex with the current 6-digit code" in str(sent["text"])
    assert "mymedia_pairing status=waiting_for_code" in str(report["operator_text"])


def test_send_mymedia_amazon_pairing_telegram_prefers_saved_session_over_env_default_route(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    pairing_dir = tmp_path / "mymedia-pairing"
    pairing_dir.mkdir(parents=True, exist_ok=True)
    (pairing_dir / "storage_state.json").write_text("{}", encoding="utf-8")
    (pairing_dir / "session.json").write_text(
        json.dumps(
            {
                "resume_url": "https://na.account.amazon.com/ap/cvf",
                "otp_channel": "sms",
                "phone_suffix": "419",
                "surface_kind": "waiting_for_code",
                "site": "na.account.amazon.com",
                "current_path": "/ap/mfa",
                "captured_at": "2026-07-04T13:35:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_DIR", str(pairing_dir))
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_SESSION_MAX_AGE_SECONDS", "1800")
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_AMAZON_OTP_CHANNEL", "whatsapp")
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-04T13:40:00Z")
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "pairing_ready": False,
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
        },
    )
    monkeypatch.setattr(
        module,
        "trigger_mymedia_amazon_pairing",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not retrigger when a fresh saved session exists")),
    )
    monkeypatch.setattr(
        module,
        "send_telegram",
        lambda **kwargs: {
            "sent": True,
            "reason": "sent",
            "principal_id": kwargs["principal_id"],
            "message_count": 1,
            "chat_ref_present": True,
            "chat_ref_sha256": "ghi789",
        },
    )

    report = module.send_mymedia_amazon_pairing_telegram(
        web_base_url="http://127.0.0.1:52051",
        telegram_principal_id="cf-email:tibor.girschele@gmail.com",
        output_format="json",
        telegram_operator_streams="media",
    )

    assert report["status"] == "waiting_for_code"
    assert report["otp_channel"] == "sms"
    assert report["pairing_resume_ready"] is True
    assert report["source"] == "mymedia_setup.saved_session"


def test_send_mymedia_amazon_pairing_telegram_dry_run_reports_delivery_readiness(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    pairing_dir = tmp_path / "mymedia-pairing"
    pairing_dir.mkdir(parents=True, exist_ok=True)
    (pairing_dir / "storage_state.json").write_text("{}", encoding="utf-8")
    (pairing_dir / "session.json").write_text(
        json.dumps(
            {
                "resume_url": "https://na.account.amazon.com/ap/cvf",
                "otp_channel": "whatsapp",
                "phone_suffix": "419",
                "surface_kind": "waiting_for_code",
                "site": "na.account.amazon.com",
                "current_path": "/ap/mfa",
                "captured_at": "2026-07-04T13:35:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_DIR", str(pairing_dir))
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_SESSION_MAX_AGE_SECONDS", "1800")
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-04T13:40:00Z")
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "pairing_ready": False,
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
        },
    )

    def _fake_send_telegram(*, principal_id: str, text: str, dry_run: bool, timeout_seconds: float) -> dict[str, object]:
        assert principal_id == "cf-email:tibor.girschele@gmail.com"
        assert dry_run is True
        assert "6-digit code" in text
        return {
            "sent": False,
            "reason": "dry_run",
            "ready": True,
            "principal_id": principal_id,
            "chat_ref_present": True,
            "chat_ref_sha256": "chatsha",
            "bot_key": "default",
            "bot_handle": "ea_concierge_bot",
            "delivery_transport": "telegram_bot",
            "runtime_container": "ea-api",
        }

    monkeypatch.setattr(module, "send_telegram", _fake_send_telegram)

    report = module.send_mymedia_amazon_pairing_telegram(
        web_base_url="http://127.0.0.1:52051",
        telegram_principal_id="cf-email:tibor.girschele@gmail.com",
        dry_run=True,
        output_format="json",
        telegram_operator_streams="media",
    )

    assert report["status"] == "waiting_for_code"
    assert report["source"] == "mymedia_setup.saved_session"
    assert report["telegram_sent"] is False
    assert report["telegram_reason"] == "dry_run"
    assert report["telegram_delivery"]["ready"] is True
    assert report["telegram_delivery"]["delivery_transport"] == "telegram_bot"


def test_send_mymedia_amazon_pairing_telegram_suppresses_media_handoff_by_default(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    pairing_dir = tmp_path / "mymedia-pairing"
    pairing_dir.mkdir(parents=True, exist_ok=True)
    (pairing_dir / "storage_state.json").write_text("{}", encoding="utf-8")
    (pairing_dir / "session.json").write_text(
        json.dumps(
            {
                "resume_url": "https://na.account.amazon.com/ap/cvf",
                "otp_channel": "whatsapp",
                "phone_suffix": "419",
                "surface_kind": "waiting_for_code",
                "site": "na.account.amazon.com",
                "current_path": "/ap/mfa",
                "captured_at": "2026-07-04T13:35:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_DIR", str(pairing_dir))
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_SESSION_MAX_AGE_SECONDS", "1800")
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-04T13:40:00Z")
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "pairing_ready": False,
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
        },
    )
    monkeypatch.setattr(
        module,
        "send_telegram",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("telegram send should stay suppressed")),
    )

    report = module.send_mymedia_amazon_pairing_telegram(
        web_base_url="http://127.0.0.1:52051",
        telegram_principal_id="cf-email:tibor.girschele@gmail.com",
        dry_run=True,
        output_format="json",
    )

    assert report["status"] == "waiting_for_code"
    assert report["telegram_sent"] is False
    assert report["telegram_reason"] == "operator_stream_not_allowed"
    assert report["telegram_delivery"]["readiness_status"] == "suppressed_by_stream_policy"
    assert report["telegram_delivery"]["delivery_transport"] == "telegram_bot"
    assert report["allowed_operator_streams"] == ["office_loop", "office_setup", "recovery"]


def test_probe_mymedia_pairing_telegram_readiness_reports_ready_dry_run_without_live_send(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-04T14:10:00Z")

    def _fake_send_mymedia_amazon_pairing_telegram(
        *,
        telegram_principal_id: str,
        dry_run: bool,
        timeout_seconds: float,
        output_format: str,
        output_dir: str = "",
        **_kwargs,
    ) -> dict[str, object]:
        assert telegram_principal_id == "principal-1"
        assert dry_run is True
        assert timeout_seconds == 7.0
        assert output_format == "json"
        assert output_dir == ""
        return {
            "probe_ok": True,
            "ready": False,
            "status": "waiting_for_code",
            "reason": "mfa_code_requested",
            "surface_kind": "waiting_for_code",
            "site": "na.account.amazon.com",
            "otp_channel": "whatsapp",
            "phone_suffix": "419",
            "pairing_resume_ready": True,
            "pairing_session_pending": True,
            "pairing_session_stale": False,
            "pairing_session_age_seconds": 95,
            "observed_at": "2026-07-04T14:09:30Z",
            "telegram_delivery": {
                "sent": False,
                "reason": "dry_run",
                "ready": True,
                "readiness_probe_ok": True,
                "readiness_status": "ready",
                "readiness_reason": "",
                "principal_id": "principal-1",
                "chat_ref_present": True,
                "chat_ref_sha256": "h" * 64,
                "bot_handle": "tibor_concierge_bot",
                "delivery_transport": "telegram_bot",
            },
        }

    monkeypatch.setattr(module, "send_mymedia_amazon_pairing_telegram", _fake_send_mymedia_amazon_pairing_telegram)

    report = module.probe_mymedia_pairing_telegram_readiness(
        principal_id="principal-1",
        timeout_seconds=7.0,
        output_format="json",
        telegram_operator_streams="media",
    )

    assert report["probe_ok"] is True
    assert report["ready"] is True
    assert report["status"] == "ready"
    assert report["reason"] == ""
    assert report["next_action"] == ""
    assert report["surface_kind"] == "waiting_for_code"
    assert report["telegram_delivery_ready"] is True
    assert report["chat_ref_sha256"] == "h" * 64
    assert report["source"] == "mymedia_pairing.telegram_dry_run"


def test_probe_mymedia_pairing_telegram_readiness_surfaces_transport_repair_action(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-04T14:10:00Z")

    def _fake_send_mymedia_amazon_pairing_telegram(
        *,
        telegram_principal_id: str,
        dry_run: bool,
        timeout_seconds: float,
        output_format: str,
        output_dir: str = "",
        **_kwargs,
    ) -> dict[str, object]:
        assert telegram_principal_id == "principal-1"
        assert dry_run is True
        assert timeout_seconds == 7.0
        assert output_format == "json"
        assert output_dir == ""
        return {
            "probe_ok": True,
            "ready": False,
            "status": "waiting_for_code",
            "reason": "mfa_code_requested",
            "surface_kind": "waiting_for_code",
            "site": "na.account.amazon.com",
            "otp_channel": "whatsapp",
            "phone_suffix": "419",
            "pairing_resume_ready": True,
            "pairing_session_pending": True,
            "observed_at": "2026-07-04T14:09:30Z",
            "telegram_delivery": {
                "sent": False,
                "reason": "dry_run",
                "ready": False,
                "readiness_probe_ok": True,
                "readiness_status": "blocked",
                "readiness_reason": "telegram_binding_not_found",
                "next_action": "connect_telegram_identity_binding",
                "next_action_href": "/integrations/telegram",
                "next_action_label": "Connect Telegram",
                "next_action_method": "get",
                "principal_id": "principal-1",
                "chat_ref_present": False,
                "chat_ref_sha256": "",
                "bot_handle": "tibor_concierge_bot",
                "delivery_transport": "telegram_bot",
            },
        }

    monkeypatch.setattr(module, "send_mymedia_amazon_pairing_telegram", _fake_send_mymedia_amazon_pairing_telegram)

    report = module.probe_mymedia_pairing_telegram_readiness(
        principal_id="principal-1",
        timeout_seconds=7.0,
        output_format="json",
        telegram_operator_streams="media",
    )

    assert report["probe_ok"] is True
    assert report["ready"] is False
    assert report["status"] == "blocked"
    assert report["reason"] == "telegram_binding_not_found"
    assert report["next_action"] == "connect_telegram_identity_binding"
    assert report["next_action_href"] == "/integrations/telegram"
    assert report["next_action_label"] == "Connect Telegram"
    assert report["next_action_method"] == "get"
    assert report["telegram_delivery_ready"] is False
    assert report["chat_ref_present"] is False


def test_send_mymedia_amazon_pairing_telegram_reuses_saved_consent_session(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    pairing_dir = tmp_path / "mymedia-pairing"
    pairing_dir.mkdir(parents=True, exist_ok=True)
    (pairing_dir / "storage_state.json").write_text("{}", encoding="utf-8")
    (pairing_dir / "session.json").write_text(
        json.dumps(
            {
                "resume_url": "https://www.amazon.com/ap/oa",
                "otp_channel": "sms",
                "phone_suffix": "419",
                "surface_kind": "consent_required",
                "site": "www.amazon.com",
                "current_path": "/ap/oa",
                "captured_at": "2026-07-04T13:35:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_DIR", str(pairing_dir))
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_SESSION_MAX_AGE_SECONDS", "1800")
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-04T13:40:00Z")
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "pairing_ready": False,
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
        },
    )
    sent: dict[str, object] = {}

    def _fake_send_telegram(*, principal_id: str, text: str, dry_run: bool, timeout_seconds: float) -> dict[str, object]:
        sent.update({"principal_id": principal_id, "text": text})
        return {
            "sent": True,
            "reason": "sent",
            "principal_id": principal_id,
            "message_count": 1,
            "chat_ref_present": True,
            "chat_ref_sha256": "def456",
        }

    monkeypatch.setattr(module, "send_telegram", _fake_send_telegram)
    monkeypatch.setattr(
        module,
        "trigger_mymedia_amazon_pairing",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should reuse saved consent handoff")),
    )

    report = module.send_mymedia_amazon_pairing_telegram(
        web_base_url="http://127.0.0.1:52051",
        otp_channel="sms",
        phone_suffix="419",
        telegram_principal_id="cf-email:tibor.girschele@gmail.com",
        output_format="json",
        telegram_operator_streams="media",
    )

    assert report["status"] == "consent_required"
    assert report["next_action"] == "approve_mymedia_amazon_consent"
    assert report["telegram_sent"] is True
    assert "waiting for Amazon consent" in str(sent["text"])


def test_send_mymedia_amazon_pairing_telegram_falls_back_to_fresh_trigger(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-04T13:41:00Z")
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "pairing_ready": False,
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
        },
    )
    monkeypatch.setattr(
        module,
        "_mymedia_pairing_session_status",
        lambda output_dir="", now=None: {
            "resume_ready": False,
            "pending_surface": False,
            "otp_channel": "",
            "phone_suffix": "",
        },
    )
    captured: dict[str, object] = {}

    def _fake_trigger(**kwargs) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "probe_ok": True,
            "ready": False,
            "status": "waiting_for_code",
            "reason": "mfa_code_requested",
            "next_action": "enter_mymedia_amazon_pairing_code",
            "surface_kind": "waiting_for_code",
            "site": "na.account.amazon.com",
            "otp_channel": "sms",
            "phone_suffix": "419",
            "code_entry_ready": True,
            "state_written": True,
            "telegram_sent": True,
            "observed_at": "2026-07-04T13:41:00Z",
            "source": "mymedia_setup.playwright",
        }

    monkeypatch.setattr(module, "trigger_mymedia_amazon_pairing", _fake_trigger)

    report = module.send_mymedia_amazon_pairing_telegram(
        web_base_url="http://127.0.0.1:52051",
        otp_channel="sms",
        phone_suffix="419",
        telegram_principal_id="cf-email:tibor.girschele@gmail.com",
        output_format="json",
        telegram_operator_streams="media",
    )

    assert captured["send_telegram_to_principal"] == "cf-email:tibor.girschele@gmail.com"
    assert captured["otp_channel"] == "sms"
    assert captured["phone_suffix"] == "419"
    assert report["status"] == "waiting_for_code"
    assert report["telegram_sent"] is True


def test_probe_mymedia_alexa_promotes_pending_pairing_session_to_code_entry_action(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-04T12:40:00Z")
    data_dir = tmp_path / "mymedia-data"
    data_dir.mkdir()
    (data_dir / "Preferences.xml").write_text(
        """
<Preferences>
  <AllowExternalAccess>2</AllowExternalAccess>
  <PublicIpAddress>203.0.113.20</PublicIpAddress>
</Preferences>
""".strip(),
        encoding="utf-8",
    )
    (data_dir / "Messages.xml").write_text("<Messages />", encoding="utf-8")
    pairing_dir = tmp_path / "mymedia-pairing"
    pairing_dir.mkdir()
    (pairing_dir / "storage_state.json").write_text("{}", encoding="utf-8")
    (pairing_dir / "session.json").write_text(
        json.dumps(
            {
                "resume_url": "https://na.account.amazon.com/ap/cvf",
                "otp_channel": "whatsapp",
                "phone_suffix": "419",
                "surface_kind": "waiting_for_code",
                "captured_at": "2026-07-04T12:35:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_DIR", str(pairing_dir))
    monkeypatch.setenv("EA_MYMEDIA_ALEXA_PAIRING_SESSION_MAX_AGE_SECONDS", "86400")
    monkeypatch.setattr(
        module,
        "_docker_inspect_container_json",
        lambda *_args, **_kwargs: {
            "State": {"Running": True, "Status": "running"},
            "Mounts": [{"Destination": "/datadir", "Source": str(data_dir)}],
        },
    )

    def _fake_api(url: str, **_kwargs):
        if url.endswith("/api/Summary"):
            return True, {"GetSummaryInfoResult": {"Tracks": 0, "Albums": 0, "Artists": 0, "Genres": 0, "ConnectionStatus": 0}}, 200, ""
        if url.endswith("/api/WatchFolders"):
            return True, {"GetWatchFoldersResult": [{"Status": 0}]}, 200, ""
        if url.endswith("/api/Login"):
            return False, {}, 401, "HTTPError:401"
        raise AssertionError(url)

    monkeypatch.setattr(module, "_mymedia_api_json", _fake_api)

    report = module.probe_mymedia_alexa(
        container_name="mymediaalexa",
        web_base_url="http://127.0.0.1:52051",
        timeout_seconds=5.0,
        output_format="json",
    )

    assert report["status"] == "blocked_pairing_required"
    assert report["next_action"] == "enter_mymedia_amazon_pairing_code"
    assert report["pairing_session_pending"] is True
    assert report["pairing_resume_ready"] is True
    assert report["pairing_session_surface_kind"] == "waiting_for_code"
    assert report["privacy"]["raw_pairing_resume_url_exposed"] is False


def test_rescan_mymedia_library_requests_console_api_and_returns_wait_state(monkeypatch) -> None:
    module = _module()
    reports = [
        {
            "probe_ok": True,
            "ready": False,
            "status": "blocked_library_scan_pending",
            "reason": "mymedia_library_scan_pending",
            "next_action": "rescan_mymedia_library",
            "next_action_href": "http://127.0.0.1:52051/index.html#!/tables",
            "next_action_label": "Open Watch Folders",
            "next_action_method": "get",
            "container_name": "mymediaalexa",
            "container_running": True,
            "api_reachable": True,
            "pairing_ready": True,
            "watch_folder_count": 1,
            "watch_folder_states": ["queued"],
            "tracks": 0,
            "library_scan_pending": True,
            "library_scan_blocked_by_pairing": False,
        },
        {
            "probe_ok": True,
            "ready": False,
            "status": "blocked_library_scan_pending",
            "reason": "mymedia_library_scan_pending",
            "next_action": "rescan_mymedia_library",
            "next_action_href": "http://127.0.0.1:52051/index.html#!/tables",
            "next_action_label": "Open Watch Folders",
            "next_action_method": "get",
            "container_name": "mymediaalexa",
            "container_running": True,
            "api_reachable": True,
            "pairing_ready": True,
            "watch_folder_count": 1,
            "watch_folder_states": ["queued"],
            "tracks": 0,
            "library_scan_pending": True,
            "library_scan_blocked_by_pairing": False,
        },
    ]
    monkeypatch.setattr(module, "probe_mymedia_alexa", lambda **_kwargs: reports.pop(0))

    def _fake_api(url: str, **kwargs):
        assert url == "http://127.0.0.1:52051/api/Rescan"
        assert kwargs["method"] == "POST"
        assert kwargs["body"] == {"clearHistory": False}
        return True, {}, 200, ""

    monkeypatch.setattr(module, "_mymedia_api_json", _fake_api)

    report = module.rescan_mymedia_library(
        web_base_url="http://127.0.0.1:52051",
        clear_history=False,
        timeout_seconds=5.0,
        output_format="operator",
    )

    assert report["probe_ok"] is True
    assert report["ready"] is False
    assert report["status"] == "scan_requested"
    assert report["reason"] == "mymedia_library_scan_requested"
    assert report["next_action"] == "wait_for_mymedia_library_scan"
    assert report["request_accepted"] is True
    assert report["http_status_code"] == 200
    assert report["watch_folder_count"] == 1
    assert report["tracks"] == 0
    assert report["library_scan_pending"] is True
    assert report["pre_probe_status"] == "blocked_library_scan_pending"
    assert report["post_probe_status"] == "blocked_library_scan_pending"
    assert "mymedia_rescan status=scan_requested" in str(report["operator_text"])


def test_rescan_mymedia_library_refuses_when_pairing_is_missing(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
            "next_action": "complete_amazon_pairing_for_mymedia",
            "next_action_href": "http://127.0.0.1:52051/index.html#!/setup",
            "next_action_label": "Open My Media setup",
            "next_action_method": "get",
            "container_name": "mymediaalexa",
            "container_running": True,
            "api_reachable": True,
            "pairing_ready": False,
            "watch_folder_count": 1,
            "watch_folder_states": ["queued"],
            "tracks": 0,
            "library_scan_pending": True,
            "library_scan_blocked_by_pairing": True,
        },
    )

    def _unexpected_api(*_args, **_kwargs):
        raise AssertionError("rescan API should not be called when pairing is missing")

    monkeypatch.setattr(module, "_mymedia_api_json", _unexpected_api)

    report = module.rescan_mymedia_library(
        web_base_url="http://127.0.0.1:52051",
        timeout_seconds=5.0,
        output_format="json",
    )

    assert report["probe_ok"] is False
    assert report["request_accepted"] is False
    assert report["status"] == "blocked_pairing_required"
    assert report["reason"] == "amazon_account_not_paired"
    assert report["next_action"] == "complete_amazon_pairing_for_mymedia"


def test_probe_operator_readiness_aggregates_components_without_raw_secrets(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T15:00:00Z")
    monkeypatch.setattr(
        module,
        "probe_telegram_readiness",
        lambda principal_id, timeout_seconds=None, output_format="json": {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "principal_id": principal_id,
            "binding_id": "binding-1",
            "binding_status": "enabled",
            "chat_ref_present": True,
            "chat_ref_sha256": "a" * 64,
            "bot_key": "default",
            "bot_handle": "ea_concierge_bot",
            "bot_token_present": True,
            "raw_chat_id": "123456789",
            "raw_bot_token": "telegram-token",
            "observed_at": "2026-06-29T14:55:00Z",
            "source": "telegram_probe",
        },
    )
    monkeypatch.setattr(module, "_default_google_workspace_expected_email", lambda: "work.tibor.girschele@gmail.com")
    monkeypatch.setattr(
        module,
        "probe_google_workspace_oauth",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "ready_retry_required",
            "reason": "oauth_retry_or_account_selection_required",
            "scope_bundle": "full_workspace",
            "expected_google_email_present": True,
            "expected_google_domain": "gmail.com",
            "observed_google_email_present": True,
            "observed_google_domain": "gmail.com",
            "observed_google_account_matches_expected": True,
            "next_action": "retry_full_workspace_auth_with_approved_account",
            "next_action_href": "/integrations/google",
            "next_action_label": "Retry Google auth",
            "next_action_method": "get",
            "console_deep_link": "https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
            "missing_setup": ["oauth_access_retry_or_account_selection_required"],
            "observed_at": "2026-06-29T14:55:00Z",
            "source": "google_oauth_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_pushbullet_delivery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "blocked_setup_required",
            "reason": "pushbullet_client_missing:default,pushbullet_token_missing:elisabeth",
            "account_label": "default->elisabeth",
            "account_label_basis": "default_client_ref",
            "required_client_keys": ["default", "elisabeth"],
            "configured_required_client_count": 1,
            "token_present_required_client_count": 0,
            "missing_client_keys": ["default"],
            "missing_token_keys": ["elisabeth"],
            "next_action": "create_missing_pushbullet_access_tokens",
            "next_action_href": "https://www.pushbullet.com/#settings/account",
            "next_action_label": "Open Pushbullet account settings",
            "next_action_method": "get",
            "observed_at": "2026-06-29T14:55:00Z",
            "source": "pushbullet_probe",
            "raw_email_exposed": False,
            "raw_token_exposed": False,
        },
    )
    monkeypatch.setattr(
        module,
        "probe_onemin_direct_refresh_posture",
        lambda **_kwargs: {
            "probe_ok": True,
            "checked": True,
            "ready": False,
            "status": "rate_limited",
            "reason": "cloudflare_rate_limited",
            "next_action": "resume_onemin_direct_refresh_after_cooldown",
            "receipt_name": "onemin_direct_refresh_live_guardrails.json",
            "selected_account_count": 1,
            "pending_account_count": 1,
            "owner_row_count": 74,
            "attempted_count": 1,
            "current_run_refreshed_count": 0,
            "refreshed_count": 0,
            "error_count": 1,
            "rate_limited": True,
            "controls": {
                "batch_size": 1,
                "batch_backoff_seconds": 1.0,
                "max_rate_limit_sleep_seconds": 120.0,
                "continue_on_rate_limit": True,
                "refresh_transport": "direct_provider_api",
                "proxy_mode": "direct_no_ui_proxy",
                "controls_inferred_from_defaults": False,
                "single_account_batch_mode": True,
            },
            "telegram_delivery": {
                "checked": False,
                "sent": False,
                "reason": "",
                "ready": False,
                "message_count": 0,
            },
            "observed_at": "2026-06-29T14:55:00Z",
            "source": "private_receipt:onemin_direct_refresh_live_guardrails.json",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_whatsapp_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "blocked",
            "reason": "sidecar_not_ready",
            "next_action": "restore_whatsapp_web_session_sidecar_readiness",
            "effective_session_ref": "tibor-wa-web",
            "sidecar_status": "qr_required",
            "sidecar_qr_required": True,
            "sidecar_qr_present": True,
            "sidecar_qr_age_seconds": 42,
            "sidecar_qr_fresh": True,
            "processor_container_enabled": True,
            "state_fresh": True,
            "raw_qr": "raw-secret-qr",
            "observed_at": "2026-06-29T14:55:01Z",
            "source": "whatsapp_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_whatsapp_pairing",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "available",
            "next_action": "scan_whatsapp_web_qr",
            "session_ref": "tibor-wa-web",
            "sidecar_status": "qr_required",
            "qr_present": True,
            "qr_required": True,
            "qr_age_seconds": 40,
            "qr_fresh": True,
            "next_action_href": "http://127.0.0.1:8098/sessions/tibor-wa-web/pair",
            "next_action_label": "Open WhatsApp pairing",
            "next_action_method": "get",
            "pair_url": "https://wa-web.test/sessions/tibor-wa-web/pair",
            "qr_svg_url": "https://wa-web.test/sessions/tibor-wa-web/qr.svg",
            "qr_svg_path": "/docker/EA/.runtime/whatsapp-pairing/tibor-wa-web.svg",
            "pair_url_scope": "host_local",
            "observed_at": "2026-06-29T14:55:02Z",
            "source": "whatsapp_pairing_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_teable_recovery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "verify_status": "pass",
            "local_status": "pass",
            "table_id": "tbl-secret-id",
            "table_id_sha256": "b" * 64,
            "table_id_present": True,
            "expected_rows": 535,
            "same_hash": 535,
            "root_restore_count": 420,
            "local_restore_count": 100,
            "service_restore_count": 9,
            "referenced_file_restore_count": 6,
            "observed_at": "2026-06-29T14:55:03Z",
            "source": "teable_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
            "next_action": "complete_amazon_pairing_then_rescan_library",
            "container_name": "mymediaalexa",
            "container_running": True,
            "api_reachable": True,
            "pairing_ready": False,
            "connection_status": "not_connected",
            "remote_access_mode": "push",
            "public_ip_present": True,
            "watch_folder_count": 1,
            "watch_folder_states": ["queued"],
            "tracks": 0,
            "library_scan_pending": True,
            "library_scan_blocked_by_pairing": True,
            "message_error_count": 1,
            "observed_at": "2026-06-29T14:55:03Z",
            "source": "mymedia_probe",
        },
    )
    proactive_artifact_probe_calls = {"count": 0}
    def _probe_proactive_route(**kwargs):
        assert kwargs["include_artifact_probe"] is False
        return {
            "probe_ok": True,
            "status": "ready_with_recovery_action",
            "next_action": "scan_whatsapp_web_qr",
            "principal_id": "principal-1",
            "runtime_service": "ea-proactive-ooda",
            "delivery_route_ready": True,
            "selected_channel": "telegram",
            "selected_transport": "telegram",
            "selected_by": "tool_runtime_binding",
            "available_channels": ["telegram"],
            "blocking_reason": "whatsapp_web_session_not_ready:qr_required",
            "approval_capture_surface_ready": False,
            "approval_capture_surface_pending_count": 0,
            "artifact_probe": {
                "probe_ok": True,
                "status": "ok",
                "runtime_service": "ea-proactive-ooda",
                "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "approval_callback_dir_exists": True,
                "approval_callback_dir_writable": True,
                "approval_callback_record_count": 1,
                "approval_callback_live_pending_count": 0,
                "approval_callback_stale_pending_count": 0,
                "current_packet_live_pending_count": 0,
                "current_packet_callback_latest_status": "",
                "approval_outcome_matches_current_packet": False,
                "stage_packet": {"private": "large-private-payload"},
                "observed_at": "2026-06-29T14:55:05Z",
                "source": "proactive_artifacts_probe",
            },
            "route_report": {"raw": "large-private-payload"},
            "observed_at": "2026-06-29T14:55:04Z",
            "source": "proactive_route_probe",
        }

    monkeypatch.setattr(module, "probe_proactive_route", _probe_proactive_route)

    def _unexpected_proactive_artifacts_probe(**_kwargs):
        proactive_artifact_probe_calls["count"] += 1
        raise AssertionError("probe_proactive_artifacts should be reused from proactive_route")

    monkeypatch.setattr(module, "probe_proactive_artifacts", _unexpected_proactive_artifacts_probe)

    report = module.probe_operator_readiness(
        args=_args(session_ref="tibor-wa-web"),
        telegram_principal_id="principal-1",
        proactive_principal_id="principal-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        receipt_path="/data/provider-ledger/proactive_ooda_latest_run.generated.json",
        timeout_seconds=7.0,
        output_format="operator",
    )
    serialized = json.dumps(report, sort_keys=True)

    assert proactive_artifact_probe_calls["count"] == 0
    assert report["contract_name"] == "ea.operator_readiness.v1"
    assert report["probe_ok"] is True
    assert report["ready"] is False
    assert report["status"] == "ready_with_actions"
    assert report["component_count"] == 10
    assert [item["key"] for item in report["components"]] == [
        "telegram",
        "google_workspace_oauth",
        "pushbullet",
        "teable_recovery",
        "mymedia_alexa",
        "proactive_route",
        "proactive_artifacts",
        "onemin_direct_refresh",
        "whatsapp",
        "whatsapp_pairing",
    ]
    assert report["blocked_count"] == 2
    assert report["attention_required_count"] == 3
    telegram_component = next(item for item in report["components"] if item["key"] == "telegram")
    assert telegram_component["details"]["principal_id_present"] is True
    assert telegram_component["details"]["binding_id_present"] is True
    pushbullet_component = next(item for item in report["components"] if item["key"] == "pushbullet")
    assert pushbullet_component["details"]["account_label_present"] is True
    assert pushbullet_component["details"]["account_label_basis"] == "default_client_ref"
    assert pushbullet_component["details"]["required_client_count"] == 2
    assert pushbullet_component["details"]["missing_client_count"] == 1
    assert pushbullet_component["details"]["missing_token_count"] == 1
    onemin_component = next(item for item in report["components"] if item["key"] == "onemin_direct_refresh")
    assert onemin_component["details"]["receipt_name"] == "onemin_direct_refresh_live_guardrails.json"
    assert onemin_component["details"]["control_batch_size"] == 1
    assert onemin_component["details"]["control_refresh_transport"] == "direct_provider_api"
    assert onemin_component["details"]["control_proxy_mode"] == "direct_no_ui_proxy"
    assert onemin_component["details"]["rate_limited"] is True
    whatsapp_component = next(item for item in report["components"] if item["key"] == "whatsapp")
    assert whatsapp_component["details"]["effective_session_ref_present"] is True
    whatsapp_pairing_component = next(item for item in report["components"] if item["key"] == "whatsapp_pairing")
    assert whatsapp_pairing_component["details"]["session_ref_present"] is True
    assert str(whatsapp_pairing_component["details"]["next_action_href"]).endswith("/integrations/whatsapp")
    assert whatsapp_pairing_component["details"]["qr_svg_path"] == "host-local-file:redacted"
    assert any(
        item["component_key"] == "google_workspace_oauth"
        and item["component_label"] == "Google Workspace OAuth"
        and item["action"] == "retry_full_workspace_auth_with_approved_account"
        and item["reason"] == "oauth_retry_or_account_selection_required"
        for item in report["next_actions"]
    )
    assert any(
        item["component_key"] == "pushbullet"
        and item["component_label"] == "Pushbullet operator delivery"
        and item["action"] == "create_missing_pushbullet_access_tokens"
        and item["reason"] == "pushbullet_client_missing,pushbullet_token_missing"
        for item in report["supplemental_next_actions"]
    )
    assert any(
        item["component_key"] == "whatsapp_pairing"
        and item["component_label"] == "WhatsApp Web pairing recovery"
        and item["action"] == "scan_whatsapp_web_qr"
        and item["reason"] == ""
        and str(item["href"]).endswith("/integrations/whatsapp")
        for item in report["supplemental_next_actions"]
    )
    assert any(
        item["component_key"] == "mymedia_alexa"
        and item["component_label"] == "My Media for Alexa"
        and item["action"] == "complete_amazon_pairing_then_rescan_library"
        and item["reason"] == "amazon_account_not_paired"
        for item in report["next_actions"]
    )
    assert any(
        item["component_key"] == "onemin_direct_refresh"
        and item["component_label"] == "1min.AI direct refresh posture"
        and item["action"] == "resume_onemin_direct_refresh_after_cooldown"
        and item["reason"] == "cloudflare_rate_limited"
        and item["href"] == "https://myexternalbrain.com/admin/goals"
        and item["label"] == "Open goals"
        and item["method"] == "get"
        for item in report["supplemental_next_actions"]
    )
    assert not any(
        item["component_key"] == "whatsapp" and item["action"] == "scan_whatsapp_web_qr"
        for item in report["next_actions"]
    )
    assert "operator_readiness status=ready_with_actions" in str(report["operator_text"])
    assert (
        "states=telegram:ready,google_workspace_oauth:ready_retry_required,"
        "mymedia_alexa:blocked_pairing_required,proactive_route:ready,proactive_artifacts:ok"
        in str(report["operator_text"])
    )
    assert (
        "supplemental_states=pushbullet:blocked_setup_required,onemin_direct_refresh:rate_limited,"
        "whatsapp_pairing:available"
        in str(report["operator_text"])
    )
    assert "next=google_workspace_oauth:retry_full_workspace_auth_with_approved_account" in str(report["operator_text"])
    assert "raw-secret-qr" not in serialized
    assert "123456789" not in serialized
    assert "telegram-token" not in serialized
    assert "tbl-secret-id" not in serialized
    assert "principal-1" not in serialized
    assert "binding-1" not in serialized
    assert "elisabeth" not in serialized
    assert "tibor-wa-web" not in serialized
    assert "http://127.0.0.1:8098/sessions/tibor-wa-web/pair" not in serialized
    assert "/docker/EA/.runtime/whatsapp-pairing/tibor-wa-web.svg" not in serialized
    assert "https://wa-web.test/sessions/tibor-wa-web/pair" not in serialized
    assert "large-private-payload" not in serialized


def test_probe_operator_readiness_falls_back_to_direct_artifacts_probe_when_route_omits_artifact_probe(monkeypatch) -> None:
    module = _module()
    _patch_onemin_direct_refresh_ready(monkeypatch, module)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-10T03:10:00Z")
    monkeypatch.setattr(
        module,
        "probe_telegram_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-10T03:09:50Z",
            "source": "telegram_probe",
        },
    )
    monkeypatch.setattr(module, "_default_google_workspace_expected_email", lambda: "work.tibor.girschele@gmail.com")
    monkeypatch.setattr(
        module,
        "probe_google_workspace_oauth",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "pass",
            "observed_at": "2026-07-10T03:09:50Z",
            "source": "google_oauth_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_pushbullet_delivery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready_live_verified",
            "observed_at": "2026-07-10T03:09:50Z",
            "source": "pushbullet_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_whatsapp_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-10T03:09:51Z",
            "source": "whatsapp_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_teable_recovery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-10T03:09:51Z",
            "source": "teable_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-10T03:09:51Z",
            "source": "mymedia_probe",
        },
    )
    def _probe_proactive_route(**kwargs):
        assert kwargs["include_artifact_probe"] is False
        return {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "principal_id": "principal-1",
            "runtime_service": "ea-proactive-ooda",
            "delivery_route_ready": True,
            "selected_channel": "telegram",
            "selected_transport": "telegram",
            "selected_by": "tool_runtime_binding",
            "available_channels": ["telegram"],
            "approval_capture_surface_ready": True,
            "approval_capture_surface_pending_count": 0,
            "observed_at": "2026-07-10T03:09:52Z",
            "source": "proactive_route_probe",
        }

    monkeypatch.setattr(module, "probe_proactive_route", _probe_proactive_route)
    proactive_artifact_probe_calls = {"count": 0}

    def _probe_proactive_artifacts(**_kwargs):
        assert _kwargs["prefer_host_runtime"] is True
        proactive_artifact_probe_calls["count"] += 1
        return {
            "probe_ok": True,
            "ready": True,
            "status": "ok",
            "runtime_service": "ea-proactive-ooda",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 2,
            "approval_callback_live_pending_count": 0,
            "approval_callback_stale_pending_count": 0,
            "current_packet_live_pending_count": 0,
            "current_packet_callback_latest_status": "approved",
            "approval_outcome_matches_current_packet": True,
            "observed_at": "2026-07-10T03:09:53Z",
            "source": "proactive_artifacts_probe",
        }

    monkeypatch.setattr(module, "probe_proactive_artifacts", _probe_proactive_artifacts)

    report = module.probe_operator_readiness(
        args=_args(session_ref="tibor-wa-web"),
        telegram_principal_id="principal-1",
        proactive_principal_id="principal-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        receipt_path="/data/provider-ledger/proactive_ooda_latest_run.generated.json",
        timeout_seconds=7.0,
        include_pairing=False,
        output_format="json",
    )

    assert proactive_artifact_probe_calls["count"] == 1
    proactive_artifacts = next(item for item in report["components"] if item["key"] == "proactive_artifacts")
    assert proactive_artifacts["status"] == "ok"
    assert proactive_artifacts["details"]["approval_callback_record_count"] == 2
    assert proactive_artifacts["source"] == "proactive_artifacts_probe"


def test_probe_operator_readiness_includes_optional_sonarr_target(monkeypatch) -> None:
    module = _module()
    _patch_onemin_direct_refresh_ready(monkeypatch, module)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T15:07:30Z")
    monkeypatch.setattr(
        module,
        "probe_telegram_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-05T15:07:20Z",
            "source": "telegram_probe",
        },
    )
    monkeypatch.setattr(module, "_default_google_workspace_expected_email", lambda: "work.tibor.girschele@gmail.com")
    monkeypatch.setattr(
        module,
        "probe_google_workspace_oauth",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "pass",
            "observed_at": "2026-07-05T15:07:20Z",
            "source": "google_oauth_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_pushbullet_delivery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready_live_verified",
            "observed_at": "2026-07-05T15:07:20Z",
            "source": "pushbullet_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_whatsapp_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-05T15:07:21Z",
            "source": "whatsapp_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_teable_recovery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-05T15:07:21Z",
            "source": "teable_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-05T15:07:21Z",
            "source": "mymedia_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_sonarr_tv_season",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "blocked_staging_import_available",
            "reason": "sonarr_missing_episodes_have_staging_candidate",
            "next_action": "repair_sonarr_tv_season",
            "series_id": 36,
            "series_title": "LEGO Ninjago: Dragons Rising",
            "series_monitored": True,
            "season_number": 2,
            "season_monitored": True,
            "season_episode_count": 20,
            "season_episode_file_count": 15,
            "missing_episode_numbers": [3, 4, 5, 6, 8],
            "metadata_queue_count": 0,
            "metadata_queue_episode_numbers": [],
            "stale_metadata_queue_count": 0,
            "staging_candidate_count": 1,
            "selected_staging_candidate_name": "LEGO.Ninjago.Dragons.Rising.S02.1080p.NF.WEB-DL.DDP5.1.H.264-STRiKES",
            "selected_staging_candidate_cover_count": 5,
            "observed_at": "2026-07-05T15:07:22Z",
            "source": "sonarr.api+filesystem",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-05T15:07:23Z",
            "source": "proactive_route_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ok",
            "observed_at": "2026-07-05T15:07:23Z",
            "source": "proactive_artifacts_probe",
        },
    )

    report = module.probe_operator_readiness(
        args=_args(session_ref="tibor-wa-web"),
        telegram_principal_id="principal-1",
        proactive_principal_id="principal-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        receipt_path="/data/provider-ledger/proactive_ooda_latest_run.generated.json",
        timeout_seconds=7.0,
        include_pairing=False,
        sonarr_series_id=36,
        sonarr_season_number=2,
        output_format="json",
    )

    keys = [item["key"] for item in report["components"]]
    assert keys == [
        "telegram",
        "google_workspace_oauth",
        "pushbullet",
        "teable_recovery",
        "mymedia_alexa",
        "sonarr_tv_season",
        "proactive_route",
        "proactive_artifacts",
        "onemin_direct_refresh",
        "whatsapp",
    ]
    assert report["sonarr_target_enabled"] is True
    assert report["sonarr_target_series_id"] == 36
    assert report["sonarr_target_series_title"] == ""
    assert report["sonarr_target_season_number"] == 2
    sonarr_component = next(item for item in report["components"] if item["key"] == "sonarr_tv_season")
    assert sonarr_component["ready"] is False
    assert sonarr_component["status"] == "blocked_staging_import_available"
    assert sonarr_component["details"]["missing_episode_numbers"] == [3, 4, 5, 6, 8]
    assert sonarr_component["details"]["selected_staging_candidate_cover_count"] == 5
    assert any(
        item["component_key"] == "sonarr_tv_season"
        and item["action"] == "repair_sonarr_tv_season"
        and item["reason"] == "sonarr_missing_episodes_have_staging_candidate"
        for item in report["next_actions"]
    )
    assert report["status"] == "ready_with_actions"
    assert report["blocked_count"] == 1


def test_probe_operator_readiness_includes_mymedia_pairing_telegram_component_when_resume_is_waiting(
    monkeypatch,
) -> None:
    module = _module()
    _patch_onemin_direct_refresh_ready(monkeypatch, module)
    monkeypatch.setattr(
        module,
        "probe_telegram_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-04T14:12:00Z",
            "source": "telegram_probe",
        },
    )
    monkeypatch.setattr(module, "_default_google_workspace_expected_email", lambda: "work.tibor.girschele@gmail.com")
    monkeypatch.setattr(
        module,
        "probe_google_workspace_oauth",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "pass",
            "observed_at": "2026-07-04T14:12:01Z",
            "source": "google_oauth_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_pushbullet_delivery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready_live_verified",
            "observed_at": "2026-07-04T14:12:01Z",
            "source": "pushbullet_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_whatsapp_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-04T14:12:02Z",
            "source": "whatsapp_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_teable_recovery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-04T14:12:03Z",
            "source": "teable_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
            "next_action": "enter_mymedia_amazon_pairing_code",
            "pairing_resume_ready": True,
            "pairing_session_pending": True,
            "pairing_session_surface_kind": "waiting_for_code",
            "container_name": "mymediaalexa",
            "container_running": True,
            "api_reachable": True,
            "pairing_ready": False,
            "connection_status": "not_connected",
            "remote_access_mode": "push",
            "public_ip_present": True,
            "watch_folder_count": 1,
            "watch_folder_states": ["queued"],
            "tracks": 0,
            "library_scan_pending": True,
            "library_scan_blocked_by_pairing": True,
            "observed_at": "2026-07-04T14:12:03Z",
            "source": "mymedia_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_mymedia_pairing_telegram_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "principal_id": "principal-1",
            "surface_kind": "waiting_for_code",
            "site": "na.account.amazon.com",
            "otp_channel": "whatsapp",
            "phone_suffix": "419",
            "pairing_resume_ready": True,
            "pairing_session_pending": True,
            "delivery_transport": "telegram_bot",
            "telegram_delivery_ready": True,
            "bot_handle": "tibor_concierge_bot",
            "chat_ref_present": True,
            "chat_ref_sha256": "z" * 64,
            "observed_at": "2026-07-04T14:12:04Z",
            "source": "mymedia_pairing.telegram_dry_run",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-04T14:12:05Z",
            "source": "proactive_route_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ok",
            "observed_at": "2026-07-04T14:12:06Z",
            "source": "proactive_artifacts_probe",
        },
    )

    report = module.probe_operator_readiness(
        args=_args(session_ref="tibor-wa-web"),
        telegram_principal_id="principal-1",
        proactive_principal_id="principal-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        receipt_path="/data/provider-ledger/proactive_ooda_latest_run.generated.json",
        timeout_seconds=7.0,
        include_pairing=True,
        output_format="json",
    )

    keys = [item["key"] for item in report["components"]]
    assert keys == [
        "telegram",
        "google_workspace_oauth",
        "pushbullet",
        "teable_recovery",
        "mymedia_alexa",
        "proactive_route",
        "proactive_artifacts",
        "onemin_direct_refresh",
        "whatsapp",
        "mymedia_pairing_telegram",
    ]
    pairing_component = next(item for item in report["components"] if item["key"] == "mymedia_pairing_telegram")
    assert pairing_component["ready"] is True
    assert pairing_component["status"] == "ready"
    assert pairing_component["reason"] == ""
    assert pairing_component["details"]["delivery_transport"] == "telegram_bot"
    assert pairing_component["details"]["chat_ref_sha256"] == "z" * 64
    assert not any(item["component_key"] == "mymedia_pairing_telegram" for item in report["next_actions"])
    assert any(item["component_key"] == "mymedia_alexa" for item in report["next_actions"])


def test_operator_readiness_component_counts_stream_suppressed_mymedia_handoff_as_non_blocking() -> None:
    module = _module()

    assert (
        module._operator_readiness_component_counts_as_blocked(
            {
                "key": "mymedia_pairing_telegram",
                "probe_ok": True,
                "ready": False,
                "status": "suppressed_by_stream_policy",
            }
        )
        is False
    )
    assert (
        module._operator_readiness_component_counts_as_blocked(
            {
                "key": "onemin_direct_refresh",
                "probe_ok": True,
                "ready": False,
                "status": "rate_limited",
            }
        )
        is False
    )


def test_probe_operator_readiness_skips_mymedia_pairing_telegram_when_pairing_disabled(monkeypatch) -> None:
    module = _module()
    _patch_onemin_direct_refresh_ready(monkeypatch, module)
    monkeypatch.setattr(
        module,
        "probe_telegram_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-04T14:12:00Z",
            "source": "telegram_probe",
        },
    )
    monkeypatch.setattr(module, "_default_google_workspace_expected_email", lambda: "work.tibor.girschele@gmail.com")
    monkeypatch.setattr(
        module,
        "probe_google_workspace_oauth",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "pass",
            "observed_at": "2026-07-04T14:12:01Z",
            "source": "google_oauth_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_pushbullet_delivery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready_live_verified",
            "observed_at": "2026-07-04T14:12:01Z",
            "source": "pushbullet_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_whatsapp_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-04T14:12:02Z",
            "source": "whatsapp_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_teable_recovery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-04T14:12:03Z",
            "source": "teable_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "blocked_pairing_required",
            "reason": "amazon_account_not_paired",
            "next_action": "enter_mymedia_amazon_pairing_code",
            "pairing_resume_ready": True,
            "pairing_session_pending": True,
            "pairing_session_surface_kind": "waiting_for_code",
            "container_name": "mymediaalexa",
            "container_running": True,
            "api_reachable": True,
            "pairing_ready": False,
            "connection_status": "not_connected",
            "remote_access_mode": "push",
            "public_ip_present": True,
            "watch_folder_count": 1,
            "watch_folder_states": ["queued"],
            "tracks": 0,
            "library_scan_pending": True,
            "library_scan_blocked_by_pairing": True,
            "observed_at": "2026-07-04T14:12:03Z",
            "source": "mymedia_probe",
        },
    )

    def _unexpected_pairing_probe(**_kwargs):
        raise AssertionError("mymedia pairing telegram probe should be skipped when include_pairing is false")

    monkeypatch.setattr(module, "probe_mymedia_pairing_telegram_readiness", _unexpected_pairing_probe)
    monkeypatch.setattr(
        module,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-04T14:12:05Z",
            "source": "proactive_route_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ok",
            "observed_at": "2026-07-04T14:12:06Z",
            "source": "proactive_artifacts_probe",
        },
    )

    report = module.probe_operator_readiness(
        args=_args(session_ref="tibor-wa-web"),
        telegram_principal_id="principal-1",
        proactive_principal_id="principal-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        receipt_path="/data/provider-ledger/proactive_ooda_latest_run.generated.json",
        timeout_seconds=7.0,
        include_pairing=False,
        output_format="json",
    )

    keys = [item["key"] for item in report["components"]]
    assert keys == [
        "telegram",
        "google_workspace_oauth",
        "pushbullet",
        "teable_recovery",
        "mymedia_alexa",
        "proactive_route",
        "proactive_artifacts",
        "onemin_direct_refresh",
        "whatsapp",
    ]
    assert not any(item["component_key"] == "mymedia_pairing_telegram" for item in report["next_actions"])
    assert any(item["component_key"] == "mymedia_alexa" for item in report["next_actions"])


def test_probe_operator_readiness_suppresses_next_action_noise_from_ready_proactive_route(monkeypatch) -> None:
    module = _module()
    _patch_onemin_direct_refresh_ready(monkeypatch, module)
    monkeypatch.setattr(
        module,
        "probe_telegram_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-01T21:40:00Z",
            "source": "telegram_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_whatsapp_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-01T21:40:01Z",
            "source": "whatsapp_probe",
        },
    )
    monkeypatch.setattr(module, "_default_google_workspace_expected_email", lambda: "work.tibor.girschele@gmail.com")
    monkeypatch.setattr(
        module,
        "probe_google_workspace_oauth",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "pass",
            "observed_at": "2026-07-01T21:40:01Z",
            "source": "google_oauth_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_pushbullet_delivery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready_live_verified",
            "observed_at": "2026-07-01T21:40:01Z",
            "source": "pushbullet_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_teable_recovery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-01T21:40:02Z",
            "source": "teable_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-01T21:40:02Z",
            "source": "mymedia_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "next_action": "inspect_proactive_delivery_route",
            "principal_id": "principal-1",
            "runtime_service": "ea-proactive-ooda",
            "delivery_route_ready": True,
            "selected_channel": "telegram",
            "selected_transport": "telegram",
            "selected_by": "tool_runtime_binding",
            "available_channels": ["telegram"],
            "approval_capture_surface_ready": False,
            "approval_capture_surface_pending_count": 0,
            "observed_at": "2026-07-01T21:40:03Z",
            "source": "proactive_route_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ok",
            "runtime_service": "ea-proactive-ooda",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_live_pending_count": 0,
            "approval_callback_stale_pending_count": 0,
            "current_packet_live_pending_count": 0,
            "approval_outcome_matches_current_packet": False,
            "observed_at": "2026-07-01T21:40:04Z",
            "source": "proactive_artifacts_probe",
        },
    )

    report = module.probe_operator_readiness(
        args=_args(session_ref="tibor-wa-web"),
        telegram_principal_id="principal-1",
        proactive_principal_id="principal-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        receipt_path="/data/provider-ledger/proactive_ooda_latest_run.generated.json",
        timeout_seconds=7.0,
        include_pairing=False,
        output_format="operator",
    )

    assert report["status"] == "ready"
    assert report["ready"] is True
    assert report["attention_required_count"] == 0
    assert report["next_actions"] == []
    assert "next=" not in str(report["operator_text"])


def test_probe_operator_readiness_suppresses_next_action_noise_from_ready_mymedia_background_scan(monkeypatch) -> None:
    module = _module()
    _patch_onemin_direct_refresh_ready(monkeypatch, module)
    monkeypatch.setattr(
        module,
        "probe_telegram_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-01T21:40:00Z",
            "source": "telegram_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_whatsapp_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-01T21:40:01Z",
            "source": "whatsapp_probe",
        },
    )
    monkeypatch.setattr(module, "_default_google_workspace_expected_email", lambda: "work.tibor.girschele@gmail.com")
    monkeypatch.setattr(
        module,
        "probe_google_workspace_oauth",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "pass",
            "observed_at": "2026-07-01T21:40:01Z",
            "source": "google_oauth_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_pushbullet_delivery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready_live_verified",
            "observed_at": "2026-07-01T21:40:01Z",
            "source": "pushbullet_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_teable_recovery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-01T21:40:02Z",
            "source": "teable_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready_library_scan_in_progress",
            "reason": "mymedia_library_scan_in_progress",
            "next_action": "wait_for_mymedia_library_scan",
            "next_action_href": "http://127.0.0.1:52051/index.html#!/tables",
            "next_action_label": "Open Watch Folders",
            "next_action_method": "get",
            "tracks": 42,
            "watch_folder_count": 1,
            "watch_folder_states": ["indexing"],
            "library_scan_pending": True,
            "observed_at": "2026-07-01T21:40:02Z",
            "source": "mymedia_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "principal_id": "principal-1",
            "runtime_service": "ea-proactive-ooda",
            "delivery_route_ready": True,
            "selected_channel": "telegram",
            "selected_transport": "telegram",
            "selected_by": "tool_runtime_binding",
            "available_channels": ["telegram"],
            "approval_capture_surface_ready": True,
            "approval_capture_surface_pending_count": 0,
            "observed_at": "2026-07-01T21:40:03Z",
            "source": "proactive_route_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ok",
            "runtime_service": "ea-proactive-ooda",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_live_pending_count": 0,
            "approval_callback_stale_pending_count": 0,
            "current_packet_live_pending_count": 0,
            "current_packet_callback_latest_status": "approved",
            "approval_outcome_matches_current_packet": True,
            "observed_at": "2026-07-01T21:40:03Z",
            "source": "proactive_artifacts_probe",
        },
    )

    report = module.probe_operator_readiness(
        args=_args(session_ref="tibor-wa-web"),
        telegram_principal_id="principal-1",
        proactive_principal_id="principal-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        receipt_path="/data/provider-ledger/proactive_ooda_latest_run.generated.json",
        timeout_seconds=7.0,
        include_pairing=False,
        output_format="json",
    )

    mymedia_component = next(item for item in report["components"] if item["key"] == "mymedia_alexa")
    assert mymedia_component["ready"] is True
    assert mymedia_component["status"] == "ready_library_scan_in_progress"
    assert mymedia_component["details"]["tracks"] == 42
    assert report["blocked_count"] == 0
    assert report["attention_required_count"] == 0
    assert report["status"] == "ready"
    assert not any(item["component_key"] == "mymedia_alexa" for item in report["next_actions"])


def test_probe_operator_readiness_reports_google_runtime_config_gap_without_replaying_stale_receipt(monkeypatch) -> None:
    module = _module()
    _patch_onemin_direct_refresh_ready(monkeypatch, module)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-02T21:00:00Z")
    monkeypatch.setattr(module, "_default_google_workspace_expected_email", lambda: "")
    monkeypatch.setattr(
        module,
        "probe_telegram_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-02T20:59:00Z",
            "source": "telegram_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_google_workspace_oauth_receipt",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "ready_retry_required",
            "reason": "oauth_retry_or_account_selection_required",
            "scope_bundle": "full_workspace",
            "expected_google_email_present": True,
            "expected_google_domain": "gmail.com",
            "observed_google_email_present": True,
            "observed_google_domain": "gmail.com",
            "observed_google_account_matches_expected": True,
            "missing_setup": ["oauth_access_retry_or_account_selection_required"],
            "user_action_required": True,
            "next_action": "retry_full_workspace_auth_with_approved_account",
            "next_action_href": "/integrations/google",
            "next_action_label": "Retry Google auth",
            "next_action_method": "get",
            "console_deep_link": "https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
            "observed_at": "2026-07-02T18:30:00Z",
            "source": "published_receipt:/docker/EA/.codex-studio/published/ea_google_workspace_oauth_readiness.generated.json",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_pushbullet_delivery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready_live_verified",
            "observed_at": "2026-07-02T20:58:01Z",
            "source": "pushbullet_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_whatsapp_readiness",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-02T20:58:02Z",
            "source": "whatsapp_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_teable_recovery",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-02T20:58:03Z",
            "source": "teable_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_mymedia_alexa",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-02T20:58:03Z",
            "source": "mymedia_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "observed_at": "2026-07-02T20:58:04Z",
            "source": "proactive_route_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": True,
            "status": "ok",
            "observed_at": "2026-07-02T20:58:05Z",
            "source": "proactive_artifacts_probe",
        },
    )

    report = module.probe_operator_readiness(
        args=_args(session_ref="tibor-wa-web"),
        telegram_principal_id="principal-1",
        proactive_principal_id="principal-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        receipt_path="/data/provider-ledger/proactive_ooda_latest_run.generated.json",
        timeout_seconds=7.0,
        include_pairing=False,
        output_format="json",
    )

    google_component = next(item for item in report["components"] if item["key"] == "google_workspace_oauth")
    assert google_component["status"] == "blocked_setup_required"
    assert google_component["reason"] == "expected_google_email_missing"
    assert google_component["source"] == "ea_live_ops.aggregate"
    assert google_component["details"]["runtime_expected_google_email_present"] is False
    assert google_component["details"]["last_receipt_status"] == "ready_retry_required"
    assert google_component["details"]["last_receipt_source"].startswith("published_receipt:")
    assert google_component["details"]["last_receipt_fresh"] is False
    assert int(google_component["details"]["last_receipt_age_seconds"]) > 7200
    assert report["next_actions"][0]["component_key"] == "google_workspace_oauth"
    assert report["next_actions"][0]["action"] == "set_google_workspace_expected_email_and_refresh_receipt"


def test_main_probe_operator_readiness_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="probe-operator-readiness",
            format="operator",
            telegram_principal_id="principal-1",
            proactive_principal_id="principal-1",
            compose_file="/docker/EA/docker-compose.yml",
            runtime_service="ea-proactive-ooda",
            receipt_path="",
            include_proactive=True,
            include_pairing=True,
            sonarr_series_id=36,
            sonarr_series_title="",
            sonarr_season_number=2,
            timeout_seconds=5.0,
        ),
    )

    def _fake_probe_operator_readiness(**kwargs):
        assert kwargs["telegram_principal_id"] == "principal-1"
        assert kwargs["proactive_principal_id"] == "principal-1"
        assert kwargs["sonarr_series_id"] == 36
        assert kwargs["sonarr_series_title"] == ""
        assert kwargs["sonarr_season_number"] == 2
        assert kwargs["timeout_seconds"] == 5.0
        assert kwargs["output_format"] == "operator"
        return {"probe_ok": True, "operator_text": "operator readiness ok"}

    monkeypatch.setattr(module, "probe_operator_readiness", _fake_probe_operator_readiness)

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "operator readiness ok"


def test_main_probe_mymedia_alexa_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="probe-mymedia-alexa",
            format="operator",
            container_name="mymediaalexa",
            web_base_url="http://127.0.0.1:52051",
            timeout_seconds=5.0,
        ),
    )

    def _fake_probe_mymedia_alexa(**kwargs):
        assert kwargs["container_name"] == "mymediaalexa"
        assert kwargs["web_base_url"] == "http://127.0.0.1:52051"
        assert kwargs["timeout_seconds"] == 5.0
        assert kwargs["output_format"] == "operator"
        return {"probe_ok": True, "operator_text": "mymedia ok"}

    monkeypatch.setattr(module, "probe_mymedia_alexa", _fake_probe_mymedia_alexa)

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "mymedia ok"


def test_main_rescan_mymedia_library_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="rescan-mymedia-library",
            format="operator",
            web_base_url="http://127.0.0.1:52051",
            clear_history=False,
            timeout_seconds=5.0,
        ),
    )

    def _fake_rescan(**kwargs):
        assert kwargs["web_base_url"] == "http://127.0.0.1:52051"
        assert kwargs["clear_history"] is False
        assert kwargs["timeout_seconds"] == 5.0
        assert kwargs["output_format"] == "operator"
        return {"probe_ok": True, "operator_text": "mymedia rescan ok"}

    monkeypatch.setattr(module, "rescan_mymedia_library", _fake_rescan)

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "mymedia rescan ok"


def test_main_repair_mymedia_public_surface_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="repair-mymedia-public-surface",
            format="operator",
            web_base_url="http://127.0.0.1:52051",
            public_web_base_url="https://mymedia.girschele.com",
            public_tunnel_origin_url="",
            timeout_seconds=5.0,
        ),
    )

    def _fake_repair(**kwargs):
        assert kwargs["web_base_url"] == "http://127.0.0.1:52051"
        assert kwargs["public_web_base_url"] == "https://mymedia.girschele.com"
        assert kwargs["public_tunnel_origin_url"] == ""
        assert kwargs["timeout_seconds"] == 5.0
        assert kwargs["output_format"] == "operator"
        return {"ready": True, "operator_text": "mymedia public surface repaired"}

    monkeypatch.setattr(module, "repair_mymedia_public_surface", _fake_repair)

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "mymedia public surface repaired"


def test_main_repair_mymedia_console_api_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="repair-mymedia-console-api",
            format="operator",
            container_name="mymediaalexa",
            web_base_url="http://127.0.0.1:52051",
            timeout_seconds=5.0,
        ),
    )

    def _fake_repair(**kwargs):
        assert kwargs["container_name"] == "mymediaalexa"
        assert kwargs["web_base_url"] == "http://127.0.0.1:52051"
        assert kwargs["timeout_seconds"] == 5.0
        assert kwargs["output_format"] == "operator"
        return {"status": "repaired", "operator_text": "mymedia console api repaired"}

    monkeypatch.setattr(module, "repair_mymedia_console_api", _fake_repair)

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "mymedia console api repaired"


def test_main_repair_sonarr_tv_season_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="repair-sonarr-tv-season",
            format="operator",
            series_id=36,
            series_title="",
            season_number=2,
            sonarr_base_url="http://127.0.0.1:8989",
            sonarr_config_path="/docker/arr-v2/sonarr/config.xml",
            staging_root="/mnt/pcloud/staging/downloads",
            timeout_seconds=5.0,
        ),
    )

    def _fake_repair(**kwargs):
        assert kwargs["series_id"] == 36
        assert kwargs["series_title"] == ""
        assert kwargs["season_number"] == 2
        assert kwargs["sonarr_base_url"] == "http://127.0.0.1:8989"
        assert kwargs["sonarr_config_path"] == "/docker/arr-v2/sonarr/config.xml"
        assert kwargs["staging_root"] == "/mnt/pcloud/staging/downloads"
        assert kwargs["timeout_seconds"] == 5.0
        assert kwargs["output_format"] == "operator"
        return {"status": "repaired", "operator_text": "sonarr tv season repaired"}

    monkeypatch.setattr(module, "repair_sonarr_tv_season", _fake_repair)

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "sonarr tv season repaired"


def test_main_trigger_mymedia_amazon_pairing_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="trigger-mymedia-amazon-pairing",
            format="operator",
            web_base_url="http://127.0.0.1:52051",
            setup_url="",
            otp_channel="whatsapp",
            phone_suffix="419",
            telegram_principal_id="principal-1",
            send_telegram=False,
            dry_run=True,
            timeout_seconds=5.0,
            output_dir="",
        ),
    )

    def _fake_trigger(**kwargs):
        assert kwargs["web_base_url"] == "http://127.0.0.1:52051"
        assert kwargs["otp_channel"] == "whatsapp"
        assert kwargs["phone_suffix"] == "419"
        assert kwargs["dry_run"] is True
        assert kwargs["timeout_seconds"] == 5.0
        assert kwargs["output_format"] == "operator"
        return {"probe_ok": True, "operator_text": "mymedia pairing waiting"}

    monkeypatch.setattr(module, "trigger_mymedia_amazon_pairing", _fake_trigger)

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "mymedia pairing waiting"


def test_main_submit_mymedia_amazon_pairing_code_emits_json(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="submit-mymedia-amazon-pairing-code",
            otp_code="123456",
            format="json",
            web_base_url="http://127.0.0.1:52051",
            timeout_seconds=8.0,
            output_dir="",
        ),
    )
    monkeypatch.setattr(
        module,
        "submit_mymedia_amazon_pairing_code",
        lambda **kwargs: {
            "probe_ok": True,
            "status": "paired_library_pending",
            "next_action": "rescan_mymedia_library",
            "otp_code_used": kwargs["otp_code"],
        },
    )

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "paired_library_pending"
    assert payload["next_action"] == "rescan_mymedia_library"
    assert payload["otp_code_used"] == "123456"


def test_repair_whatsapp_action_processor_starts_existing_container_without_recreating_sidecar(monkeypatch) -> None:
    module = _module()
    readiness_reports = [
        {
            "probe_ok": True,
            "status": "blocked",
            "ready": False,
            "reason": "state_file_container_probe_unavailable",
            "next_action": "start_or_repair_whatsapp_action_processor_container",
            "processor_container_enabled": False,
            "sidecar_status": "qr_required",
        },
        {
            "probe_ok": True,
            "status": "blocked",
            "ready": False,
            "reason": "sidecar_not_ready",
            "next_action": "restore_whatsapp_web_session_sidecar_readiness",
            "processor_container_enabled": True,
            "sidecar_status": "qr_required",
            "state_fresh": True,
        },
    ]
    monkeypatch.setattr(module, "probe_whatsapp_readiness", lambda **_kwargs: readiness_reports.pop(0))
    calls: list[list[str]] = []

    def _fake_run(command, **_kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    report = module.repair_whatsapp_action_processor(
        compose_file="/docker/EA/docker-compose.whatsapp-web-session.yml",
        service="ea-whatsapp-web-action-processor",
    )

    assert report["status"] == "repaired_with_actions"
    assert report["repaired"] is True
    assert report["ready"] is False
    assert report["next_action"] == "scan_whatsapp_web_qr"
    assert report["processor_container_enabled"] is True
    assert report["fallback_attempted"] is False
    assert calls == [
        [
            "docker",
            "compose",
            "-f",
            "/docker/EA/docker-compose.whatsapp-web-session.yml",
            "start",
            "ea-whatsapp-web-action-processor",
        ]
    ]


def test_repair_whatsapp_action_processor_falls_back_to_no_deps_up_when_start_fails(monkeypatch) -> None:
    module = _module()
    readiness_reports = [
        {
            "probe_ok": True,
            "status": "blocked",
            "ready": False,
            "reason": "state_file_container_probe_unavailable",
            "next_action": "start_or_repair_whatsapp_action_processor_container",
            "processor_container_enabled": False,
            "sidecar_status": "qr_required",
        },
        {
            "probe_ok": True,
            "status": "ready",
            "ready": True,
            "reason": "",
            "next_action": "",
            "processor_container_enabled": True,
            "sidecar_status": "ready",
            "state_fresh": True,
        },
    ]
    monkeypatch.setattr(module, "probe_whatsapp_readiness", lambda **_kwargs: readiness_reports.pop(0))
    calls: list[list[str]] = []

    def _fake_run(command, **_kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=1 if len(calls) == 1 else 0, stdout="container id", stderr="docker warning")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    report = module.repair_whatsapp_action_processor(
        compose_file="/docker/EA/docker-compose.whatsapp-web-session.yml",
        service="ea-whatsapp-web-action-processor",
    )

    assert report["status"] == "repaired"
    assert report["repaired"] is True
    assert report["ready"] is True
    assert report["start_exit_code"] == 1
    assert report["fallback_attempted"] is True
    assert report["fallback_exit_code"] == 0
    assert report["fallback_stdout_present"] is True
    assert report["fallback_stderr_present"] is True
    assert calls[1] == [
        "docker",
        "compose",
        "-f",
        "/docker/EA/docker-compose.whatsapp-web-session.yml",
        "up",
        "-d",
        "--no-deps",
        "ea-whatsapp-web-action-processor",
    ]


def test_probe_proactive_route_normalizes_live_runtime_route_status(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", "1")
    receipt_paths: list[str] = []
    route_commands: list[list[str]] = []

    def _fake_exec_json(*, command: list[str], **_kwargs):
        if command[:2] == ["python", "-c"]:
            return (
                0,
                {
                    "probe_ok": True,
                    "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/20260626T180300Z-sent-abc123.json",
                },
                '{"probe_ok":true}',
                "",
            )
        if "/app/scripts/verify_proactive_ooda.py" in command:
            route_commands.append(list(command))
            return (
                0,
                {
                    "ok": True,
                    "delivery_route": {
                        "ready": True,
                        "route_error": "whatsapp_web_session_not_ready:qr_required",
                        "recovery_hint": "Scan the WhatsApp Web QR code and re-activate the session before preferring WhatsApp again.",
                        "next_action": "scan_whatsapp_web_qr",
                        "selected_channel": "telegram",
                        "selected_transport": "telegram",
                        "selected_by": "tool_runtime_binding",
                        "available_channels": ["telegram"],
                    },
                    "delivery_guard": {"delivery_state": "eligible"},
                },
                '{"ok":true}',
                "",
            )
        if "/app/scripts/verify_proactive_ooda_live_receipt.py" in command:
            if "--receipt-path" in command:
                receipt_paths.extend(command[command.index("--receipt-path") + 1 : command.index("--receipt-path") + 2])
            return (
                0,
                {
                    "ok": True,
                    "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/20260626T180300Z-sent-abc123.json",
                    "notification_status": "sent",
                    "delivery_channel": "telegram",
                    "delivery_next_action": "",
                    "delivery_route_error": "",
                    "delivery_recovery_hint": "",
                    "errors": [],
                },
                '{"ok":true}',
                "",
            )
        raise AssertionError(command)

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-26T18:05:00Z")

    report = module.probe_proactive_route(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "ready_with_recovery_action"
    assert report["principal_id"] == "exec-1"
    assert report["source"] == "docker_compose_exec"
    assert report["runtime_service"] == "ea-proactive-ooda"
    assert report["observed_at"] == "2026-06-26T18:05:00Z"
    assert report["delivery_route_ready"] is True
    assert report["selected_channel"] == "telegram"
    assert report["selected_transport"] == "telegram"
    assert report["selected_by"] == "tool_runtime_binding"
    assert report["available_channels"] == ["telegram"]
    assert report["blocking_reason"] == "whatsapp_web_session_not_ready:qr_required"
    assert report["next_action"] == "scan_whatsapp_web_qr"
    assert report["next_action_href"] == "https://myexternalbrain.com/integrations/whatsapp"
    assert report["next_action_label"] == "Open WhatsApp pairing"
    assert report["next_action_method"] == "get"
    assert report["live_receipt_checked"] is True
    assert report["live_receipt"]["ok"] is True
    assert receipt_paths == []
    assert report["live_receipt"]["receipt_path"] == "/data/provider-ledger/proactive_ooda_run_receipts/20260626T180300Z-sent-abc123.json"
    assert "--delivery-route-mode" in route_commands[0]
    assert route_commands[0][route_commands[0].index("--delivery-route-mode") + 1] == "lightweight"


def test_probe_proactive_route_reports_unarmed_deferred_runtime(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", "1")

    def _fake_exec_json(*, command: list[str], **_kwargs):
        if command[:2] == ["python", "-c"]:
            return (
                0,
                {
                    "probe_ok": True,
                    "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                    "current_packet_live_pending_count": 1,
                },
                '{"probe_ok":true}',
                "",
            )
        if "/app/scripts/verify_proactive_ooda.py" in command:
            return (
                0,
                {
                    "ok": True,
                    "delivery_route": {
                        "ready": True,
                        "route_error": "",
                        "recovery_hint": "",
                        "next_action": "",
                        "selected_channel": "telegram",
                        "selected_transport": "telegram",
                        "selected_by": "tool_runtime_binding",
                        "available_channels": ["telegram"],
                    },
                    "delivery_guard": {
                        "delivery_state": "deferred",
                        "deferred_reason": "deferred_by_unarmed_send",
                        "armed_send": False,
                    },
                },
                '{"ok":true}',
                "",
            )
        if "/app/scripts/verify_proactive_ooda_live_receipt.py" in command:
            return (
                0,
                {
                    "ok": False,
                    "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                    "notification_status": "deferred",
                    "delivery_channel": "",
                    "delivery_next_action": "",
                    "delivery_route_error": "",
                    "delivery_recovery_hint": "",
                    "errors": ["receipt_missing"],
                },
                '{"ok":false}',
                "",
            )
        raise AssertionError(command)

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-28T14:32:00Z")

    report = module.probe_proactive_route(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "deferred"
    assert report["blocking_reason"] == "deferred_by_unarmed_send"
    assert report["next_action"] == "arm_proactive_send_for_live_delivery"
    assert report["delivery_route_ready"] is True
    assert report["selected_channel"] == "telegram"


def test_probe_proactive_route_prefers_approval_followthrough_when_surface_is_live(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", "1")

    def _fake_exec_json(*, command: list[str], **_kwargs):
        if command[:2] == ["python", "-c"]:
            return (
                0,
                {
                    "probe_ok": True,
                    "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/20260628T122109_024304_0000-sent-a4eb56dcf249.json",
                    "current_packet_live_pending_count": 1,
                    "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
                },
                '{"probe_ok":true}',
                "",
            )
        if "/app/scripts/verify_proactive_ooda.py" in command:
            return (
                0,
                {
                    "ok": True,
                    "delivery_route": {
                        "ready": True,
                        "route_error": "",
                        "recovery_hint": "",
                        "next_action": "",
                        "selected_channel": "telegram",
                        "selected_transport": "telegram",
                        "selected_by": "tool_runtime_binding",
                        "available_channels": ["telegram"],
                    },
                    "delivery_guard": {"delivery_state": "eligible"},
                },
                '{"ok":true}',
                "",
            )
        if "/app/scripts/verify_proactive_ooda_live_receipt.py" in command:
            return (
                0,
                {
                    "ok": True,
                    "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/20260628T122109_024304_0000-sent-a4eb56dcf249.json",
                    "notification_status": "sent",
                    "delivery_channel": "telegram",
                    "delivery_next_action": "",
                    "delivery_route_error": "",
                    "delivery_recovery_hint": "",
                    "errors": [],
                },
                '{"ok":true}',
                "",
            )
        raise AssertionError(command)

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-28T13:15:00Z")

    report = module.probe_proactive_route(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "ready"
    assert report["approval_capture_surface_ready"] is True
    assert report["approval_capture_surface_pending_count"] == 1
    assert report["next_action"] == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    assert report["next_action_href"] == "https://myexternalbrain.com/admin/proactive-ooda/approval"
    assert report["next_action_label"] == "Record packet verdict"
    assert report["next_action_method"] == "get"


def test_probe_proactive_route_skips_workspace_source_for_route_readiness(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", "1")
    seen_verify_command: list[str] = []

    def _fake_exec_json(*, command: list[str], **_kwargs):
        if command[:2] == ["python", "-c"]:
            return (
                0,
                {
                    "probe_ok": True,
                    "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                },
                '{"probe_ok":true}',
                "",
            )
        if "/app/scripts/verify_proactive_ooda.py" in command:
            seen_verify_command.extend(command)
            if "--skip-workspace-source" in command:
                return (
                    0,
                    {
                        "ok": True,
                        "delivery_route": {
                            "ready": True,
                            "route_error": "",
                            "recovery_hint": "",
                            "next_action": "",
                            "selected_channel": "telegram",
                            "selected_transport": "telegram",
                            "selected_by": "tool_runtime_binding",
                            "available_channels": ["telegram"],
                        },
                        "delivery_guard": {"delivery_state": "eligible"},
                        "stage_packets": {"ready": True, "errors": []},
                        "safe_work_results": {"ready": True, "errors": []},
                    },
                    '{"ok":true}',
                    "",
                )
            return (
                0,
                {
                    "ok": False,
                    "errors": ["google_workspace_signal_source_unhealthy:google_oauth_invalid_grant"],
                    "delivery_route": {
                        "ready": True,
                        "route_error": "",
                        "recovery_hint": "",
                        "next_action": "",
                        "selected_channel": "telegram",
                        "selected_transport": "telegram",
                        "selected_by": "tool_runtime_binding",
                        "available_channels": ["telegram"],
                    },
                    "delivery_guard": {"delivery_state": "eligible"},
                    "stage_packets": {"ready": True, "errors": []},
                    "safe_work_results": {"ready": True, "errors": []},
                },
                '{"ok":false}',
                "",
            )
        if "/app/scripts/verify_proactive_ooda_live_receipt.py" in command:
            return (
                0,
                {
                    "ok": False,
                    "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                    "notification_status": "missing",
                    "delivery_channel": "",
                    "delivery_next_action": "",
                    "delivery_route_error": "",
                    "delivery_recovery_hint": "",
                    "errors": ["receipt_missing"],
                },
                '{"ok":false}',
                "",
            )
        raise AssertionError(command)

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-28T14:35:00Z")

    report = module.probe_proactive_route(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "ready"
    assert report["blocking_reason"] == ""
    assert report["next_action"] == "inspect_proactive_delivery_route"
    assert report["next_action_href"] == ""
    assert report["next_action_label"] == ""
    assert report["next_action_method"] == ""
    assert "--skip-workspace-source" in seen_verify_command


def test_probe_proactive_route_can_explicitly_prefer_host_python_exec(monkeypatch) -> None:
    module = _module()
    seen: list[list[str]] = []

    def _fake_host_exec_json(*, command: list[str], **_kwargs):
        seen.append(list(command))
        if command[1].endswith("verify_proactive_ooda.py"):
            return (
                0,
                {
                    "ok": True,
                    "delivery_route": {
                        "ready": True,
                        "route_error": "",
                        "recovery_hint": "",
                        "next_action": "",
                        "selected_channel": "telegram",
                        "selected_transport": "telegram",
                        "selected_by": "tool_runtime_binding",
                        "available_channels": ["telegram"],
                    },
                    "delivery_guard": {"delivery_state": "eligible"},
                },
                '{"ok":true}',
                "",
            )
        if command[1].endswith("verify_proactive_ooda_live_receipt.py"):
            return (
                0,
                {
                    "ok": True,
                    "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                    "notification_status": "sent",
                    "delivery_channel": "telegram",
                    "delivery_next_action": "",
                    "delivery_route_error": "",
                    "delivery_recovery_hint": "",
                    "errors": [],
                },
                '{"ok":true}',
                "",
            )
        raise AssertionError(command)

    monkeypatch.setenv("DATABASE_URL", "postgresql://ea:test@localhost/ea")
    monkeypatch.setenv("EA_LIVE_OPS_PREFER_HOST_RUNTIME_PROACTIVE_PROBE", "1")
    monkeypatch.delenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", raising=False)
    monkeypatch.setattr(module, "_docker_cli_available", lambda: True)
    monkeypatch.setattr(module, "_host_python_exec_json", _fake_host_exec_json)
    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "current_packet_live_pending_count": 1,
        },
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T11:04:00Z")

    report = module.probe_proactive_route(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "ready"
    assert report["source"] == "host_python_exec"
    assert report["approval_capture_surface_ready"] is True
    assert any(command[1].endswith("verify_proactive_ooda.py") for command in seen)
    assert any(command[1].endswith("verify_proactive_ooda_live_receipt.py") for command in seen)


def test_probe_proactive_route_downgrades_live_receipt_timeout_to_recovery_action_when_route_is_ready(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", "1")

    def _fake_exec_json(*, command: list[str], **_kwargs):
        if command[:2] == ["python", "-c"]:
            return (
                0,
                {
                    "probe_ok": True,
                    "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                    "current_packet_live_pending_count": 1,
                },
                '{"probe_ok":true}',
                "",
            )
        if "/app/scripts/verify_proactive_ooda.py" in command:
            return (
                0,
                {
                    "ok": True,
                    "delivery_route": {
                        "ready": True,
                        "route_error": "",
                        "recovery_hint": "",
                        "next_action": "",
                        "selected_channel": "telegram",
                        "selected_transport": "telegram",
                        "selected_by": "tool_runtime_binding",
                        "available_channels": ["telegram"],
                    },
                    "delivery_guard": {"delivery_state": "eligible"},
                },
                '{"ok":true}',
                "",
            )
        if "/app/scripts/verify_proactive_ooda_live_receipt.py" in command:
            return (
                124,
                {
                    "ok": False,
                    "timed_out": True,
                    "reason": "TimeoutExpired:7s",
                    "timeout_seconds": 7.0,
                },
                "",
                "timed out",
            )
        raise AssertionError(command)

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T15:20:00Z")

    report = module.probe_proactive_route(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        timeout_seconds=7.0,
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "ready_with_recovery_action"
    assert report["delivery_route_ready"] is True
    assert report["blocking_reason"] == "live_receipt_probe_timed_out"
    assert report["next_action"] == "repair_proactive_runtime_inputs"
    assert report["live_receipt_checked"] is True
    assert report["live_receipt"]["timed_out"] is True


def test_probe_proactive_route_checks_live_receipt_before_artifact_probe(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", "1")
    call_order: list[str] = []

    def _fake_exec_json(*, command: list[str], **_kwargs):
        if "/app/scripts/verify_proactive_ooda.py" in command:
            call_order.append("route")
            return (
                0,
                {
                    "ok": True,
                    "delivery_route": {
                        "ready": True,
                        "route_error": "",
                        "recovery_hint": "",
                        "next_action": "",
                        "selected_channel": "telegram",
                        "selected_transport": "telegram",
                        "selected_by": "tool_runtime_binding",
                        "available_channels": ["telegram"],
                    },
                    "delivery_guard": {"delivery_state": "eligible"},
                },
                '{"ok":true}',
                "",
            )
        if "/app/scripts/verify_proactive_ooda_live_receipt.py" in command:
            call_order.append("live_receipt")
            return (
                0,
                {
                    "ok": True,
                    "errors": [],
                    "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                    "notification_status": "skipped_no_items",
                    "delivery_channel": "",
                    "delivery_message_count": 0,
                    "telegram_message_count": 0,
                    "delivery_route_error": "",
                    "delivery_recovery_hint": "",
                    "delivery_next_action": "",
                    "generated_at": "2026-07-06T03:47:00Z",
                },
                '{"ok":true}',
                "",
            )
        if command[:2] == ["python", "-c"]:
            call_order.append("artifact")
            return (
                124,
                {
                    "ok": False,
                    "timed_out": True,
                    "reason": "TimeoutExpired:7s",
                    "timeout_seconds": 7.0,
                },
                "",
                "artifact probe timed out",
            )
        raise AssertionError(command)

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-06T03:47:00Z")

    report = module.probe_proactive_route(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        timeout_seconds=7.0,
        output_format="json",
    )

    assert call_order == ["route", "live_receipt", "artifact"]
    assert report["probe_ok"] is True
    assert report["status"] == "ready"
    assert report["delivery_route_ready"] is True
    assert report["next_action"] == ""
    assert report["live_receipt_checked"] is True
    assert report["live_receipt"]["ok"] is True
    assert report["artifact_probe"]["probe_ok"] is False
    assert report["artifact_probe"]["blocking_reason"] == "runtime_artifact_probe_timed_out:TimeoutExpired:7s"


def test_probe_proactive_route_can_skip_artifact_probe(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", "1")
    call_order: list[str] = []

    def _fake_exec_json(*, command: list[str], **_kwargs):
        if "/app/scripts/verify_proactive_ooda.py" in command:
            call_order.append("route")
            return (
                0,
                {
                    "ok": True,
                    "delivery_route": {
                        "ready": True,
                        "route_error": "",
                        "recovery_hint": "",
                        "next_action": "",
                        "selected_channel": "telegram",
                        "selected_transport": "telegram",
                        "selected_by": "tool_runtime_binding",
                        "available_channels": ["telegram"],
                    },
                    "delivery_guard": {"delivery_state": "eligible"},
                },
                '{"ok":true}',
                "",
            )
        if "/app/scripts/verify_proactive_ooda_live_receipt.py" in command:
            call_order.append("live_receipt")
            return (
                0,
                {
                    "ok": True,
                    "errors": [],
                    "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                    "notification_status": "skipped_no_items",
                    "delivery_channel": "",
                    "delivery_message_count": 0,
                    "telegram_message_count": 0,
                    "delivery_route_error": "",
                    "delivery_recovery_hint": "",
                    "delivery_next_action": "",
                    "generated_at": "2026-07-06T03:47:00Z",
                },
                '{"ok":true}',
                "",
            )
        if command[:2] == ["python", "-c"]:
            call_order.append("artifact")
            raise AssertionError("artifact probe should be skipped")
        raise AssertionError(command)

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-06T03:47:00Z")

    report = module.probe_proactive_route(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        timeout_seconds=7.0,
        include_artifact_probe=False,
        output_format="json",
    )

    assert call_order == ["route", "live_receipt"]
    assert report["probe_ok"] is True
    assert report["status"] == "ready"
    assert report["delivery_route_ready"] is True
    assert report["live_receipt_checked"] is True
    assert report["artifact_probe"] == {}


def test_probe_proactive_route_surfaces_followthrough_recovery_when_live_receipt_chain_failed(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", "1")

    def _fake_exec_json(*, command: list[str], **_kwargs):
        if command[:2] == ["python", "-c"]:
            return (
                0,
                {
                    "probe_ok": True,
                    "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                },
                '{"probe_ok":true}',
                "",
            )
        if "/app/scripts/verify_proactive_ooda.py" in command:
            return (
                0,
                {
                    "ok": True,
                    "delivery_route": {
                        "ready": True,
                        "route_error": "",
                        "recovery_hint": "",
                        "next_action": "",
                        "selected_channel": "telegram",
                        "selected_transport": "telegram",
                        "selected_by": "tool_runtime_binding",
                        "available_channels": ["telegram"],
                    },
                    "delivery_guard": {"delivery_state": "eligible"},
                },
                '{"ok":true}',
                "",
            )
        if "/app/scripts/verify_proactive_ooda_live_receipt.py" in command:
            return (
                0,
                {
                    "ok": False,
                    "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                    "notification_status": "sent",
                    "delivery_channel": "telegram",
                    "delivery_next_action": "repair_proactive_operator_runtime_posture",
                    "delivery_route_error": "",
                    "delivery_recovery_hint": "",
                    "errors": ["followthrough_status_not_ok"],
                },
                '{"ok":false}',
                "",
            )
        raise AssertionError(command)

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-06T10:22:00Z")

    report = module.probe_proactive_route(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "ready_with_recovery_action"
    assert report["blocking_reason"] == "followthrough_status_not_ok"
    assert report["next_action"] == "repair_proactive_operator_runtime_posture"
    assert report["next_action_href"] == "https://myexternalbrain.com/admin/goals"


def test_probe_proactive_artifacts_reads_runtime_bundle(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", "1")

    def _fake_exec_json(*, command: list[str], **_kwargs):
        assert command[:2] == ["python", "-c"]
        return (
            0,
            {
                "probe_ok": True,
                "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
                "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "action_required_only_quiet_receipt_path": (
                    "/data/provider-ledger/proactive_ooda_run_receipts/20260629T090000-deferred-quiet.json"
                ),
                "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
                "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
                "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
                "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
                "approval_callback_dir_exists": True,
                "approval_callback_dir_writable": True,
                "approval_callback_record_count": 2,
                "approval_callback_pending_count": 1,
                "approval_callback_recorded_count": 1,
                "current_packet_callback_record_count": 1,
                "current_packet_callback_pending_count": 1,
                "current_packet_callback_recorded_count": 0,
                "current_packet_live_callback_record_count": 1,
                "current_packet_live_pending_count": 1,
                "current_packet_callback_latest_status": "pending",
                "current_packet_callback_latest_expired": False,
                "current_packet_callback_latest_created_at": "2026-06-26T18:00:00Z",
                "current_packet_callback_latest_expires_at": "2099-01-01T00:00:00Z",
                "current_packet_callback_latest_age_seconds": 3600,
                "current_packet_callback_latest_seconds_until_expiry": 1000,
                "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-1.json",
                "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-1.json",
                "run_receipt": {"notification_status": "sent"},
                "action_required_only_quiet_receipt": {
                    "notification_status": "deferred",
                    "error_code": "no_user_action_required",
                    "item_count": 1,
                    "telegram_message_ids": [],
                    "delivery_message_ids": [],
                },
                "stage_packet": {
                    "schema": "proactive_ooda.stage_packet.v1",
                    "packet_ref": "stage_packet:pkt-1",
                    "observe": "Review the staged shortlist.",
                    "decide": "Decide whether EA should proceed.",
                    "act": "Keep the action staged.",
                    "stage": {"kind": "approval_packet", "summary": "One staged shortlist candidate ready."},
                },
                "safe_work_result": {
                    "schema": "proactive_ooda.safe_work_result.v1",
                    "result_ref": "safe_work_result:res-1",
                    "summary": "One staged shortlist candidate ready.",
                    "approval_prompt": "Approve this staged shortlist candidate.",
                    "staged_action_url": "https://example.test/vendor-a",
                    "recommended_option_or_draft": {
                        "kind": "shortlist_candidate",
                        "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
                    },
                    "shortlist": [{"label": "Vendor A"}],
                },
                "approval_outcome": {"schema": "ea.proactive_ooda_approval_outcome.v1", "status": "accepted_redacted"},
            },
            '{"probe_ok":true}',
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-26T20:10:00Z")

    report = module.probe_proactive_artifacts(
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "ok"
    assert report["observed_at"] == "2026-06-26T20:10:00Z"
    assert report["run_receipt_path"] == "/data/provider-ledger/proactive_ooda_latest_run.generated.json"
    assert report["action_required_only_quiet_receipt_path"].endswith("deferred-quiet.json")
    assert report["action_required_only_quiet_receipt"]["error_code"] == "no_user_action_required"
    assert report["approval_outcome_path"] == "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json"
    assert report["approval_callback_dir"] == "/data/provider-ledger/proactive_ooda_approval_callbacks"
    assert report["approval_callback_dir_writable"] is True
    assert report["approval_callback_record_count"] == 2
    assert report["current_packet_callback_record_count"] == 1
    assert report["current_packet_live_pending_count"] == 1
    assert report["current_packet_callback_latest_status"] == "pending"
    assert report["current_packet_callback_latest_created_at"] == "2026-06-26T18:00:00Z"
    assert report["current_packet_callback_latest_expires_at"] == "2099-01-01T00:00:00Z"
    assert report["current_packet_callback_latest_age_seconds"] == 3600
    assert report["current_packet_callback_latest_seconds_until_expiry"] == 1000
    assert report["stage_packet_path"].endswith("pkt-1.json")
    assert report["safe_work_result_path"].endswith("res-1.json")
    assert report["run_receipt"]["notification_status"] == "sent"
    assert report["approval_outcome"]["status"] == "accepted_redacted"
    assert report["approval_outcome_matches_current_packet"] is False
    assert report["current_packet"]["status"] == "pending_approval"
    assert report["current_packet"]["packet_ref"] == "stage_packet:pkt-1"
    assert report["current_packet"]["decide"] == "Decide whether EA should proceed."
    assert report["current_packet"]["recommended_label"] == "Vendor A"
    assert report["current_packet"]["staged_action_url"] == "https://example.test/vendor-a"


def test_probe_proactive_artifacts_reports_timed_out_payload(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", "1")

    monkeypatch.setattr(
        module,
        "_docker_compose_exec_json",
        lambda **_kwargs: (
            124,
            {"ok": False, "timed_out": True, "reason": "TimeoutExpired:7s", "timeout_seconds": 7.0},
            "",
            "stalled",
        ),
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-01T13:00:00Z")

    report = module.probe_proactive_artifacts(
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        timeout_seconds=7.0,
        output_format="json",
    )

    assert report["probe_ok"] is False
    assert report["status"] == "probe_failed"
    assert report["timed_out"] is True
    assert report["timeout_seconds"] == 7.0
    assert report["blocking_reason"] == "runtime_artifact_probe_timed_out:TimeoutExpired:7s"
    assert report["stderr_excerpt"] == "stalled"


def test_probe_proactive_artifacts_uses_in_process_fallback_without_docker_cli(monkeypatch) -> None:
    module = _module()

    def _unexpected_exec_json(**_kwargs):
        raise AssertionError("docker compose exec should not run for in-process fallback")

    monkeypatch.setenv("EA_ROLE", "api")
    monkeypatch.setattr(module, "_docker_cli_available", lambda: False)
    monkeypatch.setattr(module, "_docker_compose_exec_json", _unexpected_exec_json)
    monkeypatch.setattr(
        module,
        "_probe_proactive_artifacts_in_process_payload",
        lambda **_kwargs: {
            "probe_ok": True,
            "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "action_required_only_quiet_receipt_path": "",
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "approval_callback_raw_pending_count": 1,
            "approval_callback_live_pending_count": 1,
            "approval_callback_unexpired_pending_count": 1,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_expired_pending_count": 0,
            "approval_callback_stale_pending_count": 0,
            "approval_callback_recorded_count": 0,
            "approval_callback_expired_count": 0,
            "approval_callback_superseded_count": 0,
            "approval_callback_terminal_count": 0,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_raw_pending_count": 1,
            "current_packet_callback_expired_pending_count": 0,
            "current_packet_callback_stale_pending_count": 0,
            "current_packet_callback_recorded_count": 0,
            "current_packet_callback_expired_count": 0,
            "current_packet_callback_superseded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
            "current_packet_callback_latest_created_at": "2026-06-30T08:00:00Z",
            "current_packet_callback_latest_expires_at": "2099-01-01T00:00:00Z",
            "current_packet_callback_latest_age_seconds": 10,
            "current_packet_callback_latest_seconds_until_expiry": 999,
            "current_packet_callback_outcome": {},
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-live.json",
            "run_receipt": {"notification_status": "sent"},
            "action_required_only_quiet_receipt": {},
            "stage_packet": {"packet_ref": "stage_packet:pkt-live"},
            "safe_work_result": {"result_ref": "safe_work_result:res-live"},
            "approval_outcome": {},
        },
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-30T08:10:00Z")

    report = module.probe_proactive_artifacts(
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["source"] == "in_process_runtime"
    assert report["observed_at"] == "2026-06-30T08:10:00Z"
    assert report["current_packet_live_pending_count"] == 1


def test_probe_proactive_artifacts_uses_docker_exec_even_when_database_url_is_present(monkeypatch) -> None:
    module = _module()

    monkeypatch.setenv("DATABASE_URL", "postgresql://ea:test@localhost/ea")
    monkeypatch.delenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", raising=False)
    monkeypatch.delenv("EA_LIVE_OPS_PREFER_HOST_RUNTIME_PROACTIVE_PROBE", raising=False)
    monkeypatch.setattr(module, "_docker_cli_available", lambda: True)
    observed: dict[str, object] = {}

    def _fake_exec_json(**_kwargs):
        observed["called"] = True
        return (
            0,
            {
                "probe_ok": True,
                "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
                "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "action_required_only_quiet_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/quiet.json",
                "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
                "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
                "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
                "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
                "approval_callback_dir_exists": True,
                "approval_callback_dir_writable": True,
                "approval_callback_record_count": 1,
                "approval_callback_pending_count": 1,
                "approval_callback_raw_pending_count": 1,
                "approval_callback_live_pending_count": 1,
                "approval_callback_unexpired_pending_count": 1,
                "approval_callback_noncurrent_pending_count": 0,
                "approval_callback_expired_pending_count": 0,
                "approval_callback_stale_pending_count": 0,
                "approval_callback_recorded_count": 0,
                "approval_callback_expired_count": 0,
                "approval_callback_superseded_count": 0,
                "approval_callback_terminal_count": 0,
                "current_packet_callback_record_count": 1,
                "current_packet_callback_pending_count": 1,
                "current_packet_callback_raw_pending_count": 1,
                "current_packet_callback_expired_pending_count": 0,
                "current_packet_callback_stale_pending_count": 0,
                "current_packet_callback_recorded_count": 0,
                "current_packet_callback_expired_count": 0,
                "current_packet_callback_superseded_count": 0,
                "current_packet_live_callback_record_count": 1,
                "current_packet_live_pending_count": 1,
                "current_packet_callback_latest_status": "pending",
                "current_packet_callback_latest_expired": False,
                "current_packet_callback_latest_created_at": "2026-07-05T11:03:00Z",
                "current_packet_callback_latest_expires_at": "2099-01-01T00:00:00Z",
                "current_packet_callback_latest_age_seconds": 60,
                "current_packet_callback_latest_seconds_until_expiry": 999999,
                "current_packet_callback_outcome": {},
                "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json",
                "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-live.json",
                "artifact_filter_reason": "",
                "flat_search_enabled": False,
                "run_receipt": {"notification_status": "sent"},
                "action_required_only_quiet_receipt": {"notification_status": "deferred"},
                "stage_packet": {"packet_ref": "stage_packet:pkt-live"},
                "safe_work_result": {"result_ref": "safe_work_result:res-live"},
                "approval_outcome": {},
            },
            "{\"probe_ok\": true}",
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(
        module,
        "_probe_proactive_artifacts_in_process_payload",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("in-process payload should not be used here")),
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T11:04:00Z")

    report = module.probe_proactive_artifacts(
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert observed["called"] is True
    assert report["source"] == "docker_compose_exec"
    assert report["current_packet_live_pending_count"] == 1
    assert report["action_required_only_quiet_receipt_path"].endswith("quiet.json")


def test_probe_proactive_artifacts_can_explicitly_prefer_host_runtime(monkeypatch) -> None:
    module = _module()

    def _unexpected_exec_json(**_kwargs):
        raise AssertionError("docker compose exec should not run when host runtime probing is explicitly requested")

    monkeypatch.setenv("DATABASE_URL", "postgresql://ea:test@localhost/ea")
    monkeypatch.setenv("EA_LIVE_OPS_PREFER_HOST_RUNTIME_PROACTIVE_PROBE", "1")
    monkeypatch.delenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", raising=False)
    monkeypatch.setattr(module, "_docker_cli_available", lambda: True)
    monkeypatch.setattr(module, "_docker_compose_exec_json", _unexpected_exec_json)
    monkeypatch.setattr(
        module,
        "_probe_proactive_artifacts_in_process_payload",
        lambda **_kwargs: {
            "probe_ok": True,
            "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "action_required_only_quiet_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/quiet.json",
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "approval_callback_raw_pending_count": 1,
            "approval_callback_live_pending_count": 1,
            "approval_callback_unexpired_pending_count": 1,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_expired_pending_count": 0,
            "approval_callback_stale_pending_count": 0,
            "approval_callback_recorded_count": 0,
            "approval_callback_expired_count": 0,
            "approval_callback_superseded_count": 0,
            "approval_callback_terminal_count": 0,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_raw_pending_count": 1,
            "current_packet_callback_expired_pending_count": 0,
            "current_packet_callback_stale_pending_count": 0,
            "current_packet_callback_recorded_count": 0,
            "current_packet_callback_expired_count": 0,
            "current_packet_callback_superseded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
            "current_packet_callback_latest_created_at": "2026-07-05T11:03:00Z",
            "current_packet_callback_latest_expires_at": "2099-01-01T00:00:00Z",
            "current_packet_callback_latest_age_seconds": 60,
            "current_packet_callback_latest_seconds_until_expiry": 999999,
            "current_packet_callback_outcome": {},
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-live.json",
            "artifact_filter_reason": "",
            "flat_search_enabled": False,
            "run_receipt": {"notification_status": "sent"},
            "action_required_only_quiet_receipt": {"notification_status": "deferred"},
            "stage_packet": {"packet_ref": "stage_packet:pkt-live"},
            "safe_work_result": {"result_ref": "safe_work_result:res-live"},
            "approval_outcome": {},
        },
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T11:04:00Z")

    report = module.probe_proactive_artifacts(
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["source"] == "in_process_runtime"
    assert report["current_packet_live_pending_count"] == 1


def test_probe_proactive_artifacts_can_prefer_host_runtime_via_argument(monkeypatch) -> None:
    module = _module()

    def _unexpected_exec_json(**_kwargs):
        raise AssertionError("docker compose exec should not run when host runtime probing is requested by argument")

    monkeypatch.setenv("DATABASE_URL", "postgresql://ea:test@localhost/ea")
    monkeypatch.delenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", raising=False)
    monkeypatch.delenv("EA_LIVE_OPS_PREFER_HOST_RUNTIME_PROACTIVE_PROBE", raising=False)
    monkeypatch.setattr(module, "_docker_cli_available", lambda: True)
    monkeypatch.setattr(module, "_docker_compose_exec_json", _unexpected_exec_json)
    monkeypatch.setattr(
        module,
        "_probe_proactive_artifacts_in_process_payload",
        lambda **_kwargs: {
            "probe_ok": True,
            "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "action_required_only_quiet_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/quiet.json",
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 0,
            "approval_callback_raw_pending_count": 0,
            "approval_callback_live_pending_count": 0,
            "approval_callback_unexpired_pending_count": 0,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_expired_pending_count": 0,
            "approval_callback_stale_pending_count": 0,
            "approval_callback_recorded_count": 1,
            "approval_callback_expired_count": 0,
            "approval_callback_superseded_count": 0,
            "approval_callback_terminal_count": 1,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 0,
            "current_packet_callback_raw_pending_count": 0,
            "current_packet_callback_expired_pending_count": 0,
            "current_packet_callback_stale_pending_count": 0,
            "current_packet_callback_recorded_count": 1,
            "current_packet_callback_expired_count": 0,
            "current_packet_callback_superseded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 0,
            "current_packet_callback_latest_status": "approved",
            "current_packet_callback_latest_expired": False,
            "current_packet_callback_latest_created_at": "2026-07-05T11:03:00Z",
            "current_packet_callback_latest_expires_at": "2099-01-01T00:00:00Z",
            "current_packet_callback_latest_age_seconds": 60,
            "current_packet_callback_latest_seconds_until_expiry": 999999,
            "current_packet_callback_outcome": {},
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-live.json",
            "artifact_filter_reason": "",
            "flat_search_enabled": False,
            "run_receipt": {"notification_status": "sent"},
            "action_required_only_quiet_receipt": {"notification_status": "deferred"},
            "stage_packet": {"packet_ref": "stage_packet:pkt-live"},
            "safe_work_result": {"result_ref": "safe_work_result:res-live"},
            "approval_outcome": {},
        },
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-05T11:04:00Z")

    report = module.probe_proactive_artifacts(
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="json",
        prefer_host_runtime=True,
    )

    assert report["probe_ok"] is True
    assert report["source"] == "in_process_runtime"
    assert report["current_packet_live_pending_count"] == 0


def test_probe_proactive_action_required_quiet_creates_sanitized_report(monkeypatch) -> None:
    module = _module()
    seen: dict[str, object] = {}

    def _fake_exec_json(*, command: list[str], **_kwargs):
        seen["command"] = list(command)
        return (
            0,
            {
                "probe_ok": True,
                "status": "quiet_receipt_created",
                "runner_returncode": 0,
                "runner_payload_seen": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_action_required_quiet_probe.generated.json",
                "archive_path": "/data/provider-ledger/proactive_ooda_run_receipts/20260702T090000-deferred-proof.json",
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "item_count": 1,
                "dry_run": False,
                "message_count": 0,
                "telegram_message_count": 0,
                "delivery_message_count": 0,
                "action_required_delivery_only": True,
                "telegram_notification_suppressed": True,
                "quiet_receipt_proves_action_required_only": True,
                "raw_signal_exposed": False,
                "raw_notification_text_exposed": False,
                "raw_credentials_exposed": False,
            },
            '{"probe_ok":true}',
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-02T09:00:00Z")

    report = module.probe_proactive_action_required_quiet(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "quiet_receipt_created"
    assert report["observed_at"] == "2026-07-02T09:00:00Z"
    assert report["notification_status"] == "deferred"
    assert report["error_code"] == "no_user_action_required"
    assert report["message_count"] == 0
    assert report["telegram_notification_suppressed"] is True
    assert report["quiet_receipt_proves_action_required_only"] is True
    assert report["raw_signal_exposed"] is False
    assert report["raw_notification_text_exposed"] is False
    assert report["raw_credentials_exposed"] is False
    command = list(seen["command"])
    assert command[:2] == ["python", "-c"]
    runtime_code = str(command[2])
    assert "'--armed-send'" in runtime_code
    assert "'--no-stage-packets'" in runtime_code
    assert "'--no-safe-work-results'" in runtime_code
    assert "'--no-teable-sync'" in runtime_code


def test_probe_proactive_action_required_quiet_reports_failed_payload(monkeypatch) -> None:
    module = _module()

    def _fake_exec_json(*, command: list[str], **_kwargs):
        assert command[:2] == ["python", "-c"]
        return (
            2,
            {
                "probe_ok": False,
                "runner_returncode": 2,
                "notification_status": "deferred",
                "error_code": "deferred_by_quiet_hours",
                "item_count": 1,
                "message_count": 0,
                "quiet_receipt_proves_action_required_only": False,
                "stderr_excerpt": "blocked",
            },
            '{"probe_ok":false}',
            "blocked",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-02T09:05:00Z")

    report = module.probe_proactive_action_required_quiet(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="operator",
    )

    assert report["probe_ok"] is False
    assert report["status"] == "probe_failed"
    assert report["blocking_reason"] == "runtime_quiet_delivery_probe_failed:exit_2"
    assert report["stderr_excerpt"] == "blocked"
    assert "quiet=false" in str(report["operator_text"])


def test_current_packet_summary_ignores_mismatched_approval_outcome() -> None:
    module = _module()
    current = module._proactive_current_packet_summary(
        stage_packet={"packet_ref": "stage_packet:pkt-1", "stage": {"kind": "research_packet"}},
        safe_work_result={"result_ref": "safe_work_result:res-1", "status": "staged_for_user_decision"},
        approval_outcome={
            "approval_outcome_recorded": True,
            "status": "recorded_not_accepted",
            "packet_ref_sha256": "0" * 64,
            "staged_artifact_sha256": "1" * 64,
        },
        current_packet_live_pending_count=0,
        current_packet_callback_record_count=0,
        current_packet_callback_latest_status="",
    )

    assert current["status"] == "staged"
    assert current["approval_outcome_matches_current_packet"] is False


def test_current_packet_summary_applies_matching_approval_outcome() -> None:
    module = _module()
    current = module._proactive_current_packet_summary(
        stage_packet={"packet_ref": "stage_packet:pkt-1", "stage": {"kind": "research_packet"}},
        safe_work_result={"result_ref": "safe_work_result:res-1", "status": "staged_for_user_decision"},
        approval_outcome={
            "approval_outcome_recorded": True,
            "status": "accepted_redacted",
            "packet_ref_sha256": module._sha256_text("stage_packet:pkt-1"),
            "staged_artifact_sha256": module._sha256_text("safe_work_result:res-1"),
        },
        current_packet_live_pending_count=0,
        current_packet_callback_record_count=0,
        current_packet_callback_latest_status="",
    )

    assert current["status"] == "accepted_redacted"
    assert current["approval_outcome_matches_current_packet"] is True


def test_probe_proactive_artifacts_operator_format_reports_approval_outcome_presence(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", "1")

    def _fake_exec_json(*, command: list[str], **_kwargs):
        assert command[:2] == ["python", "-c"]
        return (
            0,
            {
                "probe_ok": True,
                "run_receipt": {"notification_status": "sent"},
                "stage_packet": {"schema": "proactive_ooda.stage_packet.v1"},
                "safe_work_result": {"schema": "proactive_ooda.safe_work_result.v1"},
                "approval_outcome": {"schema": "ea.proactive_ooda_approval_outcome.v1"},
                "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
                "approval_callback_dir_writable": True,
                "approval_callback_record_count": 1,
                "current_packet_callback_record_count": 1,
                "current_packet_live_pending_count": 1,
                "current_packet_callback_latest_status": "pending",
                "stage_packet": {
                    "packet_ref": "stage_packet:pkt-1",
                    "decide": "Decide whether EA should proceed.",
                    "stage": {"kind": "approval_packet", "summary": "One staged shortlist candidate ready."},
                },
                "safe_work_result": {
                    "result_ref": "safe_work_result:res-1",
                    "staged_action_url": "https://example.test/vendor-a",
                    "recommended_option_or_draft": {
                        "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
                    },
                },
            },
            '{"probe_ok":true}',
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-26T20:10:00Z")

    report = module.probe_proactive_artifacts(
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="operator",
    )

    assert report["probe_ok"] is True
    assert "approval_outcome=true" in str(report["operator_text"])
    assert "approval_outcome_current=false" in str(report["operator_text"])
    assert "approval_surface=true" in str(report["operator_text"])
    assert "callback_records=1" in str(report["operator_text"])
    assert "current_packet_callbacks=1" in str(report["operator_text"])
    assert "current_packet_live_pending=1" in str(report["operator_text"])
    assert "packet_status=pending_approval" in str(report["operator_text"])
    assert "recommend=Vendor A" in str(report["operator_text"])


def test_probe_proactive_approval_capture_reports_ready_without_raw_callback_identity(monkeypatch) -> None:
    module = _module()

    def _fake_exec_json(*, command: list[str], **_kwargs):
        assert command[:2] == ["python", "-c"]
        assert "_approval_callback_principal_candidates" in command[2]
        return (
            0,
            {
                "ok": True,
                "callback_dir_exists": True,
                "callback_record_count": 4,
                "current_packet_ref_sha256": "a" * 64,
                "current_staged_artifact_ref_sha256": "b" * 64,
                "current_packet_refs_present": True,
                "current_packet_callback_record_count": 1,
                "current_packet_live_pending_count": 1,
                "current_packet_callback_latest_status": "pending",
                "current_packet_callback_latest_expired": False,
                "current_packet_callback_latest_age_seconds": 91,
                "current_packet_callback_latest_seconds_until_expiry": 1200,
                "callback_principal_hash_present": True,
                "candidate_principal_hash_count": 3,
                "principal_match_ready": True,
                "telegram_binding_ready": True,
                "telegram_blocking_reason": "",
                "telegram_chat_ref_present": True,
                "telegram_chat_ref_sha256": "c" * 64,
                "telegram_bot_key_present": True,
                "telegram_bot_token_present": True,
                "raw_callback_token": "callback-token-secret",
                "raw_principal_id": "cf-email:tibor.girschele@example.test",
                "raw_chat_ref": "123456789",
                "raw_packet_ref": "stage_packet:pkt-1",
                "raw_staged_artifact_ref": "safe_work_result:res-1",
            },
            '{"ok":true}',
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T14:30:00Z")

    report = module.probe_proactive_approval_capture(
        principal_id="cf-email:tibor.girschele@example.test",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="operator",
    )
    serialized = json.dumps(report, sort_keys=True)

    assert report["probe_ok"] is True
    assert report["ready"] is True
    assert report["status"] == "ready"
    assert report["principal_match_ready"] is True
    assert report["telegram_binding_ready"] is True
    assert report["current_packet_live_pending_count"] == 1
    assert report["candidate_principal_hash_count"] == 3
    assert report["next_action"] == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    assert "proactive_approval_capture status=ready" in str(report["operator_text"])
    assert "principal_match=true" in str(report["operator_text"])
    assert "telegram_ready=true" in str(report["operator_text"])
    assert "callback-token-secret" not in serialized
    assert "cf-email:tibor.girschele@example.test" not in serialized
    assert "123456789" not in serialized
    assert "stage_packet:pkt-1" not in serialized
    assert "safe_work_result:res-1" not in serialized


def test_probe_proactive_approval_capture_blocks_on_principal_mismatch_risk(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_docker_compose_exec_json",
        lambda **_kwargs: (
            0,
            {
                "ok": True,
                "callback_dir_exists": True,
                "callback_record_count": 1,
                "current_packet_ref_sha256": "a" * 64,
                "current_staged_artifact_ref_sha256": "b" * 64,
                "current_packet_refs_present": True,
                "current_packet_callback_record_count": 1,
                "current_packet_live_pending_count": 1,
                "current_packet_callback_latest_status": "pending",
                "current_packet_callback_latest_expired": False,
                "current_packet_callback_latest_age_seconds": 120,
                "current_packet_callback_latest_seconds_until_expiry": 600,
                "callback_principal_hash_present": True,
                "candidate_principal_hash_count": 2,
                "principal_match_ready": False,
                "telegram_binding_ready": True,
                "telegram_blocking_reason": "",
                "telegram_chat_ref_present": True,
                "telegram_bot_key_present": True,
                "telegram_bot_token_present": True,
            },
            "",
            "",
        ),
    )

    report = module.probe_proactive_approval_capture(
        principal_id="local-user",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="operator",
    )

    assert report["probe_ok"] is True
    assert report["ready"] is False
    assert report["status"] == "blocked"
    assert report["blocking_reason"] == "approval_callback_principal_mismatch_risk"
    assert report["next_action"] == "repair_proactive_approval_principal_aliases"
    assert "principal_match=false" in str(report["operator_text"])
    assert "reason=approval_callback_principal_mismatch_risk" in str(report["operator_text"])


def test_probe_proactive_approval_capture_maps_missing_telegram_token(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_docker_compose_exec_json",
        lambda **_kwargs: (
            0,
            {
                "ok": True,
                "callback_dir_exists": True,
                "callback_record_count": 1,
                "current_packet_refs_present": True,
                "current_packet_callback_record_count": 1,
                "current_packet_live_pending_count": 1,
                "current_packet_callback_latest_status": "pending",
                "callback_principal_hash_present": True,
                "candidate_principal_hash_count": 2,
                "principal_match_ready": True,
                "telegram_binding_ready": False,
                "telegram_blocking_reason": "telegram_bot_token_missing",
                "telegram_chat_ref_present": True,
                "telegram_bot_key_present": True,
                "telegram_bot_token_present": False,
            },
            "",
            "",
        ),
    )

    report = module.probe_proactive_approval_capture(
        principal_id="local-user",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
    )

    assert report["ready"] is False
    assert report["blocking_reason"] == "telegram_bot_token_missing"
    assert report["next_action"] == "configure_telegram_bot_token"


def test_probe_proactive_approval_capture_infers_current_refs_from_unique_live_pending_callback(
    monkeypatch, tmp_path: Path
) -> None:
    module = _module()
    callback_dir = tmp_path / "approval-callbacks"
    callback_dir.mkdir(parents=True, exist_ok=True)
    live_packet_ref = "stage_packet:live-pkt-1"
    live_artifact_ref = "safe_work_result:live-res-1"
    principal_id = "cf-email:tibor.girschele@example.test"
    principal_hash = module._hash_text(principal_id)  # noqa: SLF001
    (callback_dir / "pending.json").write_text(
        json.dumps(
            {
                "packet_ref": live_packet_ref,
                "staged_artifact_ref": live_artifact_ref,
                "status": "pending",
                "created_at": "2026-07-05T08:47:17Z",
                "expires_at": "2099-01-01T00:00:00Z",
                "principal_id_hash": principal_hash,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "_proactive_runtime_bundle_snapshot",
        lambda: (
            {},
            {
                "stage_packet": {"packet_ref": "stage_packet:historical-browse-proof"},
                "safe_work_result": {"result_ref": "safe_work_result:historical-browse-proof"},
                "approval_callback_dir": callback_dir,
            },
        ),
    )
    monkeypatch.setattr(module, "build_container", lambda: SimpleNamespace(tool_runtime=object()))

    from app.services import proactive_ooda_telegram_approval as approval_mod
    from app.services import telegram_delivery as telegram_mod

    monkeypatch.setattr(
        approval_mod,
        "_approval_callback_principal_candidates",
        lambda **_kwargs: (principal_id,),
    )
    monkeypatch.setattr(
        telegram_mod,
        "resolve_primary_telegram_binding",
        lambda *_args, **_kwargs: SimpleNamespace(
            auth_metadata_json={"default_chat_ref": "123456789", "bot_key": "default"},
            external_account_ref="123456789",
        ),
    )
    monkeypatch.setattr(telegram_mod, "_telegram_bot_registry", lambda: {"default": {"token": "telegram-token"}})

    payload = module._probe_proactive_approval_capture_in_process_payload(principal_id=principal_id)  # noqa: SLF001

    assert payload["ok"] is True
    assert payload["current_packet_refs_present"] is True
    assert payload["current_packet_ref_sha256"] == module._hash_text(live_packet_ref)  # noqa: SLF001
    assert payload["current_staged_artifact_ref_sha256"] == module._hash_text(live_artifact_ref)  # noqa: SLF001
    assert payload["current_packet_callback_record_count"] == 1
    assert payload["current_packet_live_pending_count"] == 1
    assert payload["current_packet_callback_latest_status"] == "pending"
    assert payload["callback_principal_hash_present"] is True
    assert payload["candidate_principal_hash_count"] == 1
    assert payload["principal_match_ready"] is True
    assert payload["telegram_binding_ready"] is True
    assert payload["telegram_chat_ref_present"] is True
    assert payload["telegram_bot_token_present"] is True


def test_probe_proactive_approval_capture_uses_in_process_fallback_without_docker_cli(monkeypatch) -> None:
    module = _module()

    def _unexpected_exec_json(**_kwargs):
        raise AssertionError("docker compose exec should not run for in-process fallback")

    monkeypatch.setenv("EA_ROLE", "api")
    monkeypatch.setattr(module, "_docker_cli_available", lambda: False)
    monkeypatch.setattr(module, "_docker_compose_exec_json", _unexpected_exec_json)
    monkeypatch.setattr(
        module,
        "_probe_proactive_approval_capture_in_process_payload",
        lambda principal_id: {
            "ok": True,
            "callback_dir_exists": True,
            "callback_record_count": 1,
            "current_packet_ref_sha256": "packet-hash",
            "current_staged_artifact_ref_sha256": "artifact-hash",
            "current_packet_refs_present": True,
            "current_packet_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
            "current_packet_callback_latest_age_seconds": 30,
            "current_packet_callback_latest_seconds_until_expiry": 3600,
            "callback_principal_hash_present": True,
            "candidate_principal_hash_count": 1,
            "principal_match_ready": True,
            "telegram_binding_ready": True,
            "telegram_blocking_reason": "",
            "telegram_chat_ref_present": True,
            "telegram_chat_ref_sha256": "chat-hash",
            "telegram_bot_key_present": True,
            "telegram_bot_token_present": True,
            "privacy": {
                "raw_callback_token_exposed": False,
                "raw_principal_id_exposed": False,
                "raw_chat_ref_exposed": False,
                "raw_packet_ref_exposed": False,
                "raw_staged_artifact_ref_exposed": False,
            },
        },
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-30T08:12:00Z")

    report = module.probe_proactive_approval_capture(
        principal_id="principal-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["ready"] is True
    assert report["source"] == "in_process_runtime:proactive_approval_capture"
    assert report["current_packet_live_pending_count"] == 1


def test_cleanup_proactive_approval_callbacks_dry_run_reports_stale_counts_without_mutation(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 20,
            "approval_callback_raw_pending_count": 4,
            "approval_callback_live_pending_count": 1,
            "approval_callback_stale_pending_count": 3,
            "approval_callback_noncurrent_pending_count": 3,
            "approval_callback_expired_pending_count": 0,
            "approval_callback_expired_count": 0,
            "approval_callback_superseded_count": 9,
            "current_packet_live_pending_count": 1,
        },
    )
    monkeypatch.setattr(
        module,
        "_docker_compose_exec_json",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("dry-run must not mutate runtime callbacks")),
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T13:00:00Z")

    report = module.cleanup_proactive_approval_callbacks(output_format="operator")

    assert report["status"] == "dry_run"
    assert report["mutated"] is False
    assert report["would_expire_count"] == 0
    assert report["would_supersede_count"] == 3
    assert report["before"]["stale_pending_count"] == 3
    assert "would_supersede=3" in str(report["operator_text"])


def test_cleanup_proactive_approval_callbacks_dry_run_reports_clean_when_no_stale_callbacks(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 20,
            "approval_callback_raw_pending_count": 1,
            "approval_callback_live_pending_count": 1,
            "approval_callback_stale_pending_count": 0,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_expired_pending_count": 0,
            "approval_callback_expired_count": 0,
            "approval_callback_superseded_count": 12,
            "current_packet_live_pending_count": 1,
        },
    )
    monkeypatch.setattr(
        module,
        "_docker_compose_exec_json",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("clean dry-run must not mutate runtime callbacks")),
    )

    report = module.cleanup_proactive_approval_callbacks(output_format="operator")

    assert report["status"] == "clean"
    assert report["mutated"] is False
    assert report["would_expire_count"] == 0
    assert report["would_supersede_count"] == 0
    assert report["next_action"] == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    assert "status=clean" in str(report["operator_text"])


def test_cleanup_proactive_approval_callbacks_execute_calls_runtime_cleanup_and_reprobes(monkeypatch) -> None:
    module = _module()
    probes = [
        {
            "probe_ok": True,
            "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 20,
            "approval_callback_raw_pending_count": 4,
            "approval_callback_live_pending_count": 1,
            "approval_callback_stale_pending_count": 3,
            "approval_callback_noncurrent_pending_count": 3,
            "approval_callback_expired_pending_count": 0,
            "approval_callback_expired_count": 0,
            "approval_callback_superseded_count": 9,
            "current_packet_live_pending_count": 1,
        },
        {
            "probe_ok": True,
            "approval_callback_record_count": 20,
            "approval_callback_raw_pending_count": 1,
            "approval_callback_live_pending_count": 1,
            "approval_callback_stale_pending_count": 0,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_expired_pending_count": 0,
            "approval_callback_expired_count": 0,
            "approval_callback_superseded_count": 12,
            "current_packet_live_pending_count": 1,
        },
    ]

    def _fake_probe(**_kwargs):
        return probes.pop(0)

    def _fake_exec_json(*, command: list[str], **_kwargs):
        assert command[:2] == ["python", "-c"]
        assert "expire_stale_proactive_ooda_telegram_approval_callbacks" in command[2]
        payload = json.loads(command[3])
        assert payload == {
            "callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
            "supersede_noncurrent": True,
        }
        return (
            0,
            {
                "status": "ok",
                "inspected_count": 20,
                "expired_count": 0,
                "superseded_count": 3,
                "skipped_count": 17,
                "error_count": 0,
                "active_packet_ref_sha256": "a" * 64,
                "active_staged_artifact_ref_sha256": "b" * 64,
            },
            '{"status":"ok"}',
            "",
        )

    monkeypatch.setattr(module, "probe_proactive_artifacts", _fake_probe)
    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T13:00:00Z")

    report = module.cleanup_proactive_approval_callbacks(execute=True, output_format="operator")

    assert report["status"] == "cleaned"
    assert report["mutated"] is True
    assert report["superseded_count"] == 3
    assert report["before"]["stale_pending_count"] == 3
    assert report["after"]["stale_pending_count"] == 0
    assert report["active_packet_ref_sha256"] == "a" * 64
    assert "stale_after=0" in str(report["operator_text"])


def test_cleanup_proactive_approval_callbacks_execute_uses_in_process_fallback(monkeypatch) -> None:
    module = _module()
    probes = [
        {
            "probe_ok": True,
            "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 20,
            "approval_callback_raw_pending_count": 4,
            "approval_callback_live_pending_count": 1,
            "approval_callback_stale_pending_count": 3,
            "approval_callback_noncurrent_pending_count": 2,
            "approval_callback_expired_pending_count": 1,
            "approval_callback_expired_count": 0,
            "approval_callback_superseded_count": 9,
            "current_packet_live_pending_count": 1,
        },
        {
            "probe_ok": True,
            "approval_callback_record_count": 20,
            "approval_callback_raw_pending_count": 1,
            "approval_callback_live_pending_count": 1,
            "approval_callback_stale_pending_count": 0,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_expired_pending_count": 0,
            "approval_callback_expired_count": 1,
            "approval_callback_superseded_count": 11,
            "current_packet_live_pending_count": 1,
        },
    ]
    captured: dict[str, object] = {}

    def _fake_probe(**_kwargs):
        return probes.pop(0)

    def _fake_cleanup(**kwargs):
        captured.update(kwargs)
        return {
            "status": "ok",
            "inspected_count": 20,
            "expired_count": 1,
            "superseded_count": 2,
            "skipped_count": 17,
            "error_count": 0,
            "active_packet_ref_sha256": "a" * 64,
            "active_staged_artifact_ref_sha256": "b" * 64,
        }

    monkeypatch.setenv("EA_ROLE", "api")
    monkeypatch.setattr(module, "_docker_cli_available", lambda: False)
    monkeypatch.setattr(
        module,
        "_docker_compose_exec_json",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("docker compose exec should not run for in-process cleanup")),
    )
    monkeypatch.setattr(module, "probe_proactive_artifacts", _fake_probe)
    monkeypatch.setattr(module, "expire_stale_proactive_ooda_telegram_approval_callbacks", _fake_cleanup)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-30T08:20:00Z")

    report = module.cleanup_proactive_approval_callbacks(execute=True, output_format="operator")

    assert report["status"] == "cleaned"
    assert report["source"] == "in_process_runtime:proactive_callback_cleanup"
    assert report["expired_count"] == 1
    assert report["superseded_count"] == 2
    assert report["before"]["stale_pending_count"] == 3
    assert report["after"]["stale_pending_count"] == 0
    assert captured["state_path"] == "/data/provider-ledger/proactive_ooda_notified.json"
    assert captured["receipt_path"] == "/data/provider-ledger/proactive_ooda_latest_run.generated.json"
    assert captured["callback_dir"] == "/data/provider-ledger/proactive_ooda_approval_callbacks"
    assert captured["supersede_noncurrent"] is True
    assert "status=cleaned" in str(report["operator_text"])


def test_probe_proactive_gmail_draft_reports_live_google_blocker(monkeypatch) -> None:
    module = _module()

    def _fake_exec_json(*, command: list[str], **_kwargs):
        assert command[:2] == ["python", "-c"]
        return (
            0,
            {
                "status": "blocked",
                "principal_id": "cf-email:tibor.girschele@gmail.com",
                "packet_ref": "stage_packet:packet-1",
                "staged_artifact_ref": "safe_work_result:result-1",
                "source_observation_id": "obs-1",
                "action": "save_gmail_draft",
                "work_type": "draft",
                "reason": "google_oauth_account_mismatch",
                "subject": "Inquiry: chimney sweep",
                "google_binding_id": "binding-1",
                "google_binding_principal_id": "cf-email:tibor.girschele@gmail.com",
                "google_account_email": "manfred.hoza@gmail.com",
                "expected_google_account_email": "tibor.girschele@gmail.com",
                "google_token_status": "reauth_required",
                "google_reauth_required_reason": "google_oauth_invalid_grant",
                "google_gmail_draft_scope_present": True,
                "google_account_count": 1,
                "execution_observation_present": True,
                "execution_status": "executed",
                "execution_saved_at": "2026-06-28T18:09:00Z",
                "recipient_email_sha256_present": True,
                "gmail_draft_id_sha256_present": True,
                "gmail_message_id_sha256_present": True,
                "draft_folder_url_sha256_present": True,
                "raw_execution_payload_exposed": False,
                "telegram_primary_binding_principal_id": "cf-email:tibor.girschele@gmail.com",
                "telegram_primary_chat_id": "246813579",
                "telegram_proactive_chat_id": "246813579",
                "next_action_surface": {
                    "href": "https://myexternalbrain.com/app/actions/google/connect?scope_bundle=full_workspace&expected_google_email=tibor.girschele%40gmail.com",
                    "label": "Reconnect Google",
                    "method": "get",
                },
            },
            '{"status":"blocked"}',
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-28T18:10:00Z")

    report = module.probe_proactive_gmail_draft(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "blocked"
    assert report["blocking_reason"] == "google_oauth_account_mismatch"
    assert report["next_action"] == "reauthorize_google_workspace_binding"
    assert report["next_action_label"] == "Reconnect Google"
    assert report["google_account_email"] == "manfred.hoza@gmail.com"
    assert report["expected_google_account_email"] == "tibor.girschele@gmail.com"
    assert report["execution_observation_present"] is True
    assert report["execution_status"] == "executed"
    assert report["recipient_email_hash_present"] is True
    assert report["gmail_draft_id_hash_present"] is True
    assert report["gmail_message_id_hash_present"] is True
    assert report["draft_folder_url_hash_present"] is True
    assert report["raw_execution_payload_exposed"] is False
    assert report["telegram_primary_chat_id"] == "246813579"
    assert report["telegram_proactive_chat_id"] == "246813579"


def test_record_proactive_approval_dry_run_uses_current_runtime_packet(monkeypatch) -> None:
    module = _module()
    commands: list[list[str]] = []

    def _fake_exec_json(*, command: list[str], **_kwargs):
        commands.append(command)
        assert command[:2] == ["python", "-c"]
        return (
            0,
            {
                "probe_ok": True,
                "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/20260628T122109_024304_0000-sent-a4eb56dcf249.json",
                "stage_packet": {
                    "packet_ref": "stage_packet:pkt-live",
                    "approval": {"required": True},
                    "stage": {"payload": {"approval_url": "https://example.test/candidate"}},
                },
                "safe_work_result": {
                    "result_ref": "safe_work_result:res-live",
                    "status": "staged_for_user_decision",
                    "approval": {"required": True},
                    "approval_prompt": "Approve this staged candidate.",
                    "staged_action_url": "https://example.test/candidate",
                },
                "approval_outcome": {},
                "current_packet_live_pending_count": 1,
            },
            '{"probe_ok":true}',
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-28T13:25:00Z")

    report = module.record_proactive_approval(
        principal_id="exec-1",
        outcome="approved",
        evidence="Approved after review.",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        dry_run=True,
        output_format="json",
    )

    assert report["recorded"] is False
    assert report["reason"] == "dry_run"
    assert report["packet_ref_sha256"] == module._hash_text("stage_packet:pkt-live")
    assert report["staged_artifact_ref_sha256"] == module._hash_text("safe_work_result:res-live")
    assert report["current_packet_refs_present"] is True
    assert report["approval_capture_surface_ready"] is True
    assert report["telegram_approval_surface_ready"] is True
    assert report["manual_outcome_capture_ready"] is True
    assert report["current_packet_approval_request_recordable"] is True
    assert report["approval_capture_surface_pending_count"] == 1
    assert report["privacy"]["raw_packet_ref_exposed"] is False
    assert report["privacy"]["raw_artifact_probe_exposed"] is False
    assert "artifact_probe" not in report
    assert "stage_packet:pkt-live" not in json.dumps(report, sort_keys=True)
    assert "safe_work_result:res-live" not in json.dumps(report, sort_keys=True)
    assert "Approved after review." not in json.dumps(report, sort_keys=True)
    assert len(commands) == 1


def test_record_proactive_approval_dry_run_reports_manual_capture_ready_without_raw_refs(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "stage_packet": {
                "packet_ref": "stage_packet:pkt-mirror",
                "approval": {"required": True},
                "stage": {"payload": {"approval_url": "https://example.test/candidate"}},
            },
            "safe_work_result": {
                "result_ref": "safe_work_result:res-mirror",
                "status": "staged_for_user_decision",
                "approval": {"required": True},
                "approval_prompt": "Approve this staged candidate.",
                "staged_action_url": "https://example.test/candidate",
            },
            "current_packet": {"status": "staged", "approval_outcome_matches_current_packet": False},
            "approval_outcome": {},
            "current_packet_live_pending_count": 0,
        },
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-01T01:45:00Z")

    report = module.record_proactive_approval(
        principal_id="exec-1",
        outcome="deferred",
        evidence="Dry-run only; no approval granted.",
        actor="codex",
        source_kind="operator_dry_run",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        dry_run=True,
        output_format="json",
    )
    serialized = json.dumps(report, sort_keys=True)

    assert report["recorded"] is False
    assert report["reason"] == "dry_run"
    assert report["approval_capture_surface_ready"] is True
    assert report["telegram_approval_surface_ready"] is False
    assert report["manual_outcome_capture_ready"] is True
    assert report["current_packet_approval_request_recordable"] is True
    assert report["approval_outcome_matches_current_packet"] is False
    assert report["packet_ref_sha256"] == module._hash_text("stage_packet:pkt-mirror")
    assert report["staged_artifact_ref_sha256"] == module._hash_text("safe_work_result:res-mirror")
    assert "stage_packet:pkt-mirror" not in serialized
    assert "safe_work_result:res-mirror" not in serialized
    assert "Dry-run only" not in serialized
    assert "artifact_probe" not in report


def test_record_proactive_approval_executes_finalize_in_runtime(monkeypatch) -> None:
    module = _module()
    commands: list[list[str]] = []

    def _fake_exec_json(*, command: list[str], **_kwargs):
        commands.append(command)
        assert command[:2] == ["python", "-c"]
        if "load_runtime_artifact_bundle" in command[2]:
            return (
                0,
                {
                    "probe_ok": True,
                    "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
                    "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/20260628T122109_024304_0000-sent-a4eb56dcf249.json",
                    "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
                    "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
                    "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
                    "stage_packet": {"packet_ref": "stage_packet:pkt-live"},
                    "safe_work_result": {"result_ref": "safe_work_result:res-live"},
                    "current_packet_live_pending_count": 1,
                },
                '{"probe_ok":true}',
                "",
            )
        if "record_current_proactive_ooda_approval_outcome" in command[2]:
            return (
                0,
                {
                    "status": "recorded",
                    "approval_outcome_id": "approval-1",
                    "approval_outcome_status": "accepted_redacted",
                    "approval_outcome_accepted": True,
                    "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
                    "operator_status_path": "/app/.codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
                    "gold_acceptance_path": "/app/.codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
                    "teable_sync": {"status": "synced", "sync_attempted": True, "blocked_reason": ""},
                },
                '{"status":"recorded","approval_outcome_id":"approval-1","approval_outcome_status":"accepted_redacted","approval_outcome_accepted":true}',
                "",
            )
        raise AssertionError(command)

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-28T13:25:00Z")

    report = module.record_proactive_approval(
        principal_id="exec-1",
        outcome="approved",
        evidence="Approved after review.",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        dry_run=False,
        output_format="json",
    )

    assert report["recorded"] is True
    assert report["reason"] == "recorded"
    assert report["accepted"] is True
    assert report["approval_outcome_id"] == "approval-1"
    assert report["approval_outcome_path"] == "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json"
    assert report["operator_status_path"] == "/app/.codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    assert report["gold_acceptance_path"] == "/app/.codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    assert report["teable_sync"]["status"] == "synced"
    assert "artifact_probe" not in report
    assert "stage_packet:pkt-live" not in json.dumps(report, sort_keys=True)
    assert "safe_work_result:res-live" not in json.dumps(report, sort_keys=True)
    assert "Approved after review." not in json.dumps(report, sort_keys=True)
    assert len(commands) == 2


def test_record_proactive_approval_records_in_process_without_docker_cli(monkeypatch) -> None:
    module = _module()

    def _unexpected_exec_json(**_kwargs):
        raise AssertionError("docker compose exec should not run for in-process fallback")

    monkeypatch.setenv("EA_ROLE", "api")
    monkeypatch.setattr(module, "_docker_cli_available", lambda: False)
    monkeypatch.setattr(module, "_docker_compose_exec_json", _unexpected_exec_json)
    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "stage_packet": {"packet_ref": "stage_packet:pkt-live"},
            "safe_work_result": {"result_ref": "safe_work_result:res-live"},
            "current_packet_live_pending_count": 1,
        },
    )
    monkeypatch.setattr(
        module,
        "_record_current_proactive_approval_in_process",
        lambda **_kwargs: {
            "status": "recorded",
            "approval_outcome_id": "approval-local",
            "approval_outcome_status": "accepted_redacted",
            "approval_outcome_accepted": True,
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "operator_status_path": "/app/.codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
            "gold_acceptance_path": "/app/.codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
            "teable_sync": {"status": "synced", "sync_attempted": True, "blocked_reason": ""},
        },
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-30T08:15:00Z")

    report = module.record_proactive_approval(
        principal_id="exec-1",
        outcome="approved",
        evidence="Approved after review.",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        dry_run=False,
        output_format="json",
    )

    assert report["recorded"] is True
    assert report["reason"] == "recorded"
    assert report["source"] == "in_process_runtime:record_proactive_approval"
    assert report["approval_outcome_id"] == "approval-local"
    assert report["teable_sync"]["status"] == "synced"
    assert "artifact_probe" not in report
    assert "stage_packet:pkt-live" not in json.dumps(report, sort_keys=True)
    assert "safe_work_result:res-live" not in json.dumps(report, sort_keys=True)


def test_reissue_proactive_approval_dry_run_executes_runtime_script(monkeypatch) -> None:
    module = _module()
    commands: list[list[str]] = []

    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/current.json",
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "current_packet_live_pending_count": 0,
        },
    )

    def _fake_exec_json(*, command: list[str], **_kwargs):
        commands.append(command)
        return (
            0,
            {
                "status": "dry_run",
                "reason": "approval_surface_ready_to_reissue",
                "packet_ref_sha256": "a" * 64,
                "staged_artifact_ref_sha256": "b" * 64,
                "approval_prompt_sha256": "c" * 64,
                "staged_action_url_sha256": "d" * 64,
                "has_staged_action_url": True,
                "stage_kind": "research_packet",
                "safe_work_status": "staged_for_user_decision",
            },
            '{"status":"dry_run"}',
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T08:30:00Z")

    report = module.reissue_proactive_approval(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        dry_run=True,
        output_format="operator",
    )

    assert report["status"] == "dry_run"
    assert report["sent"] is False
    assert report["reason"] == "approval_surface_ready_to_reissue"
    assert "proactive_approval_reissue status=dry_run" in str(report["operator_text"])
    assert len(commands) == 1
    command = commands[0]
    assert command[:2] == ["python", "/app/scripts/reissue_proactive_ooda_approval.py"]
    assert command[command.index("--state-path") + 1] == "/data/provider-ledger/proactive_ooda_notified.json"
    assert command[command.index("--receipt-path") + 1] == "/data/provider-ledger/proactive_ooda_run_receipts/current.json"
    assert command[command.index("--stage-packet-dir") + 1] == "/data/provider-ledger/proactive_ooda_stage_packets"
    assert command[command.index("--safe-work-result-dir") + 1] == "/data/provider-ledger/proactive_ooda_safe_work_results"
    assert "--dry-run" in command
    assert "--force" not in command


def test_reissue_proactive_approval_reports_sent_action_surface(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/current.json",
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "current_packet_live_pending_count": 0,
        },
    )

    def _fake_exec_json(*, command: list[str], **_kwargs):
        assert "--force" in command
        return (
            0,
            {
                "status": "sent",
                "reason": "approval_surface_reissued",
                "message_count": 1,
                "message_ids": ["tg-1"],
                "approval_surface": {
                    "present": True,
                    "channel": "telegram",
                    "status": "pending",
                    "inline_button_count": 3,
                    "url_button_count": 1,
                    "message_count": 1,
                },
                "packet_ref_sha256": "a" * 64,
                "staged_artifact_ref_sha256": "b" * 64,
                "approval_prompt_sha256": "c" * 64,
                "staged_action_url_sha256": "d" * 64,
                "has_staged_action_url": True,
                "stage_kind": "research_packet",
                "safe_work_status": "staged_for_user_decision",
            },
            '{"status":"sent"}',
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T08:30:00Z")

    report = module.reissue_proactive_approval(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        force=True,
        output_format="json",
    )

    assert report["status"] == "sent"
    assert report["sent"] is True
    assert report["message_count"] == 1
    assert report["message_ids"] == ["tg-1"]
    assert report["approval_surface"]["present"] is True


def test_reissue_proactive_approval_passes_reissue_threshold(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/current.json",
            "stage_packet_dir": "/data/provider-ledger/proactive_ooda_stage_packets",
            "safe_work_result_dir": "/data/provider-ledger/proactive_ooda_safe_work_results",
            "current_packet_live_pending_count": 1,
        },
    )

    commands: list[list[str]] = []

    def _fake_exec_json(*, command: list[str], **_kwargs):
        commands.append(list(command))
        return (
            0,
            {
                "status": "dry_run",
                "reason": "approval_surface_ready_to_reissue",
                "message_count": 0,
                "message_ids": [],
                "approval_surface": {},
                "packet_ref_sha256": "a" * 64,
                "staged_artifact_ref_sha256": "b" * 64,
                "approval_prompt_sha256": "c" * 64,
                "staged_action_url_sha256": "d" * 64,
                "has_staged_action_url": True,
                "stage_kind": "research_packet",
                "safe_work_status": "staged_for_user_decision",
            },
            '{"status":"dry_run"}',
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T08:30:00Z")

    report = module.reissue_proactive_approval(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        dry_run=True,
        reissue_after_seconds=3600,
        output_format="json",
    )

    assert report["status"] == "dry_run"
    command = commands[0]
    assert command[command.index("--reissue-after-seconds") + 1] == "3600"


def test_parse_args_probe_proactive_route_uses_proactive_principal_default(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", "cf-email:test@example.com")
    monkeypatch.setenv("EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID", "wa-default")
    monkeypatch.setattr(sys, "argv", ["ea_live_ops.py", "probe-proactive-route"])

    args = module.parse_args()

    assert args.principal_id == "wa-default"
    assert args.proactive_principal_id == "cf-email:test@example.com"


def test_parse_args_probe_proactive_route_accepts_timeout_after_subcommand(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(sys, "argv", ["ea_live_ops.py", "probe-proactive-route", "--timeout-seconds", "180"])

    args = module.parse_args()

    assert args.command == "probe-proactive-route"
    assert args.timeout_seconds == 180.0


def test_parse_args_probe_proactive_artifacts_uses_runtime_defaults(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_PROACTIVE_OODA_RUNTIME_SERVICE", "ea-proactive-ooda")
    monkeypatch.setattr(sys, "argv", ["ea_live_ops.py", "probe-proactive-artifacts"])

    args = module.parse_args()

    assert args.command == "probe-proactive-artifacts"
    assert args.runtime_service == "ea-proactive-ooda"
    assert args.format == "json"


def test_parse_args_probe_proactive_approval_capture_uses_proactive_principal_default(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", "cf-email:test@example.com")
    monkeypatch.setenv("EA_PROACTIVE_OODA_RUNTIME_SERVICE", "ea-proactive-ooda")
    monkeypatch.setattr(sys, "argv", ["ea_live_ops.py", "probe-proactive-approval-capture", "--format", "operator"])

    args = module.parse_args()

    assert args.command == "probe-proactive-approval-capture"
    assert args.proactive_principal_id == "cf-email:test@example.com"
    assert args.runtime_service == "ea-proactive-ooda"
    assert args.format == "operator"


def test_parse_args_probe_proactive_gmail_draft_uses_proactive_principal_default(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", "cf-email:test@example.com")
    monkeypatch.setattr(sys, "argv", ["ea_live_ops.py", "probe-proactive-gmail-draft"])

    args = module.parse_args()

    assert args.command == "probe-proactive-gmail-draft"
    assert args.proactive_principal_id == "cf-email:test@example.com"
    assert args.format == "json"


def test_parse_args_probe_proactive_source_coverage_uses_proactive_principal_default(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", "cf-email:test@example.com")
    monkeypatch.setattr(sys, "argv", ["ea_live_ops.py", "probe-proactive-source-coverage"])

    args = module.parse_args()

    assert args.command == "probe-proactive-source-coverage"
    assert args.proactive_principal_id == "cf-email:test@example.com"
    assert args.observation_limit == 400


def test_main_probe_proactive_route_uses_long_default_timeout(monkeypatch, capsys) -> None:
    module = _module()
    captured: dict[str, object] = {}

    def _fake_probe_proactive_route(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"probe_ok": True, "status": "ready"}

    monkeypatch.setattr(module, "probe_proactive_route", _fake_probe_proactive_route)
    monkeypatch.setattr(sys, "argv", ["ea_live_ops.py", "probe-proactive-route"])

    assert module.main() == 0
    assert captured["timeout_seconds"] == 60.0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"


def test_main_probe_proactive_source_coverage_uses_long_default_timeout(monkeypatch, capsys) -> None:
    module = _module()
    captured: dict[str, object] = {}

    def _fake_probe_proactive_source_coverage(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"probe_ok": True, "status": "ready"}

    monkeypatch.setattr(module, "probe_proactive_source_coverage", _fake_probe_proactive_source_coverage)
    monkeypatch.setattr(sys, "argv", ["ea_live_ops.py", "probe-proactive-source-coverage"])

    assert module.main() == 0
    assert captured["timeout_seconds"] == 60.0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"


def test_probe_google_workspace_oauth_send_telegram_uses_direct_auth_link(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-01T19:41:00Z")
    monkeypatch.setattr(
        module.google_workspace_oauth_readiness,
        "build_receipt",
        lambda **_kwargs: {
            "status": "blocked_setup_required",
            "blocker_kind": "oauth_test_user_or_verification_required",
            "console_deep_link": "https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
            "auth_link_template": "https://myexternalbrain.com/app/actions/google/connect?return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace&expected_google_email=%3Credacted-email%3E",
            "missing_setup": ["oauth_test_user_missing_or_app_unverified", "gcloud_project_mismatch"],
            "expected_google_account": {"present": True, "domain": "gmail.com", "email_sha256": "abc"},
            "oauth_client": {"client_project_id": "propertyquarry-498318", "client_project_number": "95627800296"},
            "gcloud_probe": {
                "active_project": "openclaw-concierge",
                "active_project_matches_oauth_project": False,
                "active_account_present": True,
                "oauth_project_id": "propertyquarry-498318",
            },
            "operator_action": {
                "user_action_required": True,
                "next_action": "add_google_oauth_test_user_and_retry_full_workspace_auth",
                "next_action_href": "/integrations/google",
                "next_action_label": "Open Google setup",
                "next_action_method": "get",
                "delivery_policy": "action_required_only",
                "instruction": "Open the Google Auth Platform Audience page for the OAuth project.",
                "telegram_message": "Action needed",
            },
        },
    )
    captured: dict[str, object] = {}

    def _fake_send_telegram(*, principal_id: str, text: str, dry_run: bool, timeout_seconds: float):
        captured["principal_id"] = principal_id
        captured["text"] = text
        captured["dry_run"] = dry_run
        captured["timeout_seconds"] = timeout_seconds
        return {"sent": True, "reason": "sent", "delivery_transport": "telegram_bot"}

    monkeypatch.setattr(module, "send_telegram", _fake_send_telegram)

    report = module.probe_google_workspace_oauth(
        expected_google_email="work.tibor.girschele@gmail.com",
        observed_error="access_denied",
        probe_gcloud=True,
        send_telegram_to_principal="cf-email:tibor.girschele@gmail.com",
        timeout_seconds=45.0,
    )

    assert report["telegram_delivery"]["sent"] is True
    assert captured["principal_id"] == "cf-email:tibor.girschele@gmail.com"
    assert captured["dry_run"] is False
    assert captured["timeout_seconds"] == 45.0
    assert "expected_google_email=work.tibor.girschele%40gmail.com" in str(captured["text"])
    assert "propertyquarry-498318" in str(captured["text"])
    assert "openclaw-concierge" in str(captured["text"])


def test_probe_google_workspace_oauth_suppresses_telegram_when_office_setup_stream_is_excluded(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-01T19:41:00Z")
    monkeypatch.setattr(
        module.google_workspace_oauth_readiness,
        "build_receipt",
        lambda **_kwargs: {
            "status": "blocked_setup_required",
            "blocker_kind": "oauth_test_user_or_verification_required",
            "console_deep_link": "https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
            "auth_link_template": "https://myexternalbrain.com/app/actions/google/connect",
            "missing_setup": ["oauth_test_user_missing_or_app_unverified"],
            "expected_google_account": {"present": True, "domain": "gmail.com", "email_sha256": "abc"},
            "oauth_client": {"client_project_id": "propertyquarry-498318", "client_project_number": "95627800296"},
            "gcloud_probe": {
                "active_project": "openclaw-concierge",
                "active_project_matches_oauth_project": False,
                "active_account_present": True,
                "oauth_project_id": "propertyquarry-498318",
            },
            "operator_action": {
                "user_action_required": True,
                "next_action": "add_google_oauth_test_user_and_retry_full_workspace_auth",
                "next_action_href": "/integrations/google",
                "next_action_label": "Open Google setup",
                "next_action_method": "get",
                "delivery_policy": "action_required_only",
                "instruction": "Open the Google Auth Platform Audience page for the OAuth project.",
                "telegram_message": "Action needed",
            },
        },
    )
    monkeypatch.setattr(
        module,
        "send_telegram",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("telegram send should stay suppressed")),
    )

    report = module.probe_google_workspace_oauth(
        expected_google_email="work.tibor.girschele@gmail.com",
        observed_error="access_denied",
        probe_gcloud=True,
        send_telegram_to_principal="cf-email:tibor.girschele@gmail.com",
        timeout_seconds=45.0,
        telegram_operator_streams="recovery",
    )

    assert report["telegram_delivery"]["sent"] is False
    assert report["telegram_delivery"]["reason"] == "operator_stream_not_allowed"
    assert report["telegram_delivery"]["readiness_status"] == "suppressed_by_stream_policy"
    assert report["allowed_operator_streams"] == ["recovery"]


def test_main_probe_proactive_source_coverage_accepts_subcommand_timeout(monkeypatch, capsys) -> None:
    module = _module()
    captured: dict[str, object] = {}

    def _fake_probe_proactive_source_coverage(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"probe_ok": True, "status": "ready"}

    monkeypatch.setattr(module, "probe_proactive_source_coverage", _fake_probe_proactive_source_coverage)
    monkeypatch.setattr(
        sys,
        "argv",
        ["ea_live_ops.py", "probe-proactive-source-coverage", "--timeout-seconds", "180"],
    )

    assert module.main() == 0
    assert captured["timeout_seconds"] == 180.0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"


def test_probe_proactive_source_coverage_reports_required_lanes_without_raw_payload(monkeypatch) -> None:
    module = _module()
    captured: dict[str, object] = {}

    def _fake_exec_json(**_kwargs: object) -> tuple[int, dict[str, object], str, str]:
        captured.update(_kwargs)
        return (
            0,
            {
                "probe_ok": True,
                "observation_repository": "PostgresObservationEventRepository",
                "rows": [
                    {
                        "channel": "product",
                        "event_type": "pocket_recording_archive_indexed",
                        "created_at": "2026-06-29T07:58:00Z",
                        "payload_keys": ["recording_id", "transcript_text", "location_name"],
                        "hints": [
                            "pocket_ai_audio_transcripts",
                            "shopping_and_vendor_signals",
                            "durable_profile_and_location_context",
                        ],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                    {
                        "channel": "gmail",
                        "event_type": "gmail.message",
                        "created_at": "2026-06-29T07:59:00Z",
                        "payload_keys": ["subject_sha256", "sender_sha256"],
                        "hints": ["google_workspace", "commitment_and_deadline_signals"],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                    {
                        "channel": "calendar",
                        "event_type": "calendar.event",
                        "created_at": "2026-06-29T08:00:00Z",
                        "payload_keys": ["event_id_sha256"],
                        "hints": ["calendar_and_renewal_signals"],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                ],
            },
            "",
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T08:01:00Z")

    report = module.probe_proactive_source_coverage(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "ready_with_gaps"
    assert report["observed_lane_count"] == 7
    assert captured["timeout_seconds"] == 60.0
    probe_code = str(list(captured["command"])[2])
    assert "EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH" not in probe_code
    assert "property_scout_sync_completed" in probe_code
    assert "assistant_property_task_auto_closed" in probe_code
    assert "property_" in probe_code
    assert "assistant_property_" in probe_code
    assert "excluded_event_types" not in probe_code
    assert "pocket_ai_audio_transcripts" not in report["missing_lane_keys"]
    assert report["privacy"]["raw_payload_exposed"] is False
    assert report["privacy"]["raw_transcript_text_exposed"] is False
    assert report["privacy"]["raw_credential_exposed"] is False
    serialized = json.dumps(report, sort_keys=True)
    assert "Order flowers" not in serialized
    assert "/mnt/pcloud" not in serialized


def test_probe_proactive_source_coverage_omits_property_exclusion_noise(monkeypatch) -> None:
    module = _module()

    def _fake_exec_json(**_kwargs: object) -> tuple[int, dict[str, object], str, str]:
        return (
            0,
            {
                "probe_ok": True,
                "observation_repository": "PostgresObservationEventRepository",
                "rows": [
                    {
                        "channel": "product",
                        "event_type": "assistant_property_task_auto_closed",
                        "created_at": "2026-06-29T07:57:00Z",
                        "payload_keys": ["reason"],
                        "hints": ["property", "cleanup"],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                    {
                        "channel": "product",
                        "event_type": "property_scout_sync_completed",
                        "created_at": "2026-06-29T07:57:30Z",
                        "payload_keys": ["run_id"],
                        "hints": ["property_scout"],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                    {
                        "channel": "product",
                        "event_type": "property_alert_review_created",
                        "created_at": "2026-06-29T07:57:45Z",
                        "payload_keys": ["listing_id", "wife_note"],
                        "hints": ["relationship_and_occasion_signals", "wife"],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                    {
                        "channel": "product",
                        "event_type": "pocket_recording_archive_indexed",
                        "created_at": "2026-06-29T07:58:00Z",
                        "payload_keys": ["transcript_sha256", "location_name"],
                        "hints": [
                            "pocket_ai_audio_transcripts",
                            "relationship_and_occasion_signals",
                            "shopping_and_vendor_signals",
                            "durable_profile_and_location_context",
                        ],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                    {
                        "channel": "calendar",
                        "event_type": "calendar.event",
                        "created_at": "2026-06-29T08:00:00Z",
                        "payload_keys": ["event_id_sha256"],
                        "hints": [
                            "google_workspace",
                            "calendar_and_renewal_signals",
                            "commitment_and_deadline_signals",
                        ],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                ],
            },
            "",
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T08:01:00Z")

    report = module.probe_proactive_source_coverage(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "ready"
    assert "flat_search_enabled" not in report
    assert "excluded_event_types" not in report
    assert "excluded_event_type_counts" not in report
    for lane in report["lanes"]:
        assert "assistant_property_task_auto_closed" not in lane["evidence_event_types"]
        assert "property_scout_sync_completed" not in lane["evidence_event_types"]
        assert "property_alert_review_created" not in lane["evidence_event_types"]


def test_probe_proactive_source_coverage_accepts_pocket_archive_evidence_when_event_rows_are_missing(monkeypatch) -> None:
    module = _module()

    def _fake_exec_json(**_kwargs: object) -> tuple[int, dict[str, object], str, str]:
        return (
            0,
            {
                "probe_ok": True,
                "observation_repository": "PostgresObservationEventRepository",
                "rows": [
                    {
                        "channel": "gmail",
                        "event_type": "gmail.message",
                        "created_at": "2026-06-29T07:59:00Z",
                        "payload_keys": ["subject_sha256", "sender_sha256"],
                        "hints": ["google_workspace", "commitment_and_deadline_signals"],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                    {
                        "channel": "calendar",
                        "event_type": "calendar.event",
                        "created_at": "2026-06-29T08:00:00Z",
                        "payload_keys": ["event_id_sha256"],
                        "hints": ["calendar_and_renewal_signals"],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                    {
                        "channel": "telegram",
                        "event_type": "office_signal_ooda_evaluated",
                        "created_at": "2026-06-29T08:01:00Z",
                        "payload_keys": ["signal_id_sha256"],
                        "hints": [
                            "relationship_and_occasion_signals",
                            "shopping_and_vendor_signals",
                            "durable_profile_and_location_context",
                        ],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                ],
            },
            "",
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(
        module,
        "_pocket_audio_archive_evidence",
        lambda: {
            "checked": True,
            "status": "pass",
            "transcript_ingest_ready": True,
            "evidence_mode": "filesystem_archive_scan",
            "latest_backfill_event_type": "filesystem_archive_scan_completed",
            "latest_completion_event_type": "filesystem_archive_scan_completed",
            "latest_backfill_created_at": "",
            "latest_completion_created_at": "",
            "archived_total": 36,
            "dismissed_total": 0,
            "failed_total": 0,
            "distinct_recording_total": 36,
            "blocking_reason": "",
            "next_action": "maintain_pocket_ai_audio_transcript_archive",
        },
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T08:02:00Z")

    report = module.probe_proactive_source_coverage(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "ready"
    assert report["missing_lane_keys"] == []
    pocket_lane = next(row for row in report["lanes"] if row["key"] == "pocket_ai_audio_transcripts")
    assert pocket_lane["observed"] is True
    assert pocket_lane["status"] == "observed_via_archive_evidence"
    assert pocket_lane["required_event_type_observed"] is True
    assert pocket_lane["missing_required_event_types"] == []
    assert pocket_lane["evidence_event_types"] == ["filesystem_archive_scan_completed"]
    assert pocket_lane["record_count"] == 36


def test_probe_proactive_source_coverage_treats_runtime_failure_as_probe_failed(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "_docker_compose_exec_json",
        lambda **_kwargs: (
            124,
            {"ok": False, "reason": "TimeoutExpired:15s"},
            "",
            "",
        ),
    )
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T08:01:00Z")

    report = module.probe_proactive_source_coverage(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
    )

    assert report["probe_ok"] is False
    assert report["checked"] is False
    assert report["status"] == "probe_failed"
    assert report["blocking_reason"] == "TimeoutExpired:15s"
    assert report["next_action"] == "inspect_proactive_runtime_container"
    assert report["missing_lane_keys"] == list(module.PROACTIVE_SOURCE_COVERAGE_LANE_KEYS)


def test_probe_proactive_source_coverage_prefers_in_process_when_database_url_present(monkeypatch) -> None:
    module = _module()

    def _unexpected_exec_json(**_kwargs):
        raise AssertionError("docker compose exec should not run when DATABASE_URL enables in-process coverage")

    class PostgresObservationEventRepository:
        pass

    class _FakeRuntime:
        def __init__(self) -> None:
            self._observations = PostgresObservationEventRepository()

        def list_recent_observations(self, limit: int, principal_id: str):
            assert limit == 400
            assert principal_id == "exec-1"
            return [
                SimpleNamespace(
                    channel="product",
                    event_type="pocket_recording_archive_indexed",
                    created_at="2026-06-29T07:58:00Z",
                    payload={"recording_id": "rec-1", "transcript_text": "spiderman shortlist", "location_name": "1200 Wien"},
                    source_id="src-pocket-1",
                    external_id="ext-pocket-1",
                ),
                SimpleNamespace(
                    channel="gmail",
                    event_type="gmail.message",
                    created_at="2026-06-29T07:59:00Z",
                    payload={"subject_sha256": "a" * 64, "sender_sha256": "b" * 64, "followup_due": "today"},
                    source_id="src-gmail-1",
                    external_id="ext-gmail-1",
                ),
                SimpleNamespace(
                    channel="calendar",
                    event_type="calendar.event",
                    created_at="2026-06-29T08:00:00Z",
                    payload={"event_id_sha256": "c" * 64},
                    source_id="src-calendar-1",
                    external_id="ext-calendar-1",
                ),
                SimpleNamespace(
                    channel="telegram",
                    event_type="office_signal_ooda_evaluated",
                    created_at="2026-06-29T08:01:00Z",
                    payload={"context": {"relationship": "wife", "address": "1200 Wien", "vendor": "pagro"}},
                    source_id="src-telegram-1",
                    external_id="ext-telegram-1",
                ),
            ]

    monkeypatch.setenv("DATABASE_URL", "postgresql://ea:test@localhost/ea")
    monkeypatch.delenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", raising=False)
    monkeypatch.setattr(module, "_docker_cli_available", lambda: True)
    monkeypatch.setattr(module, "_docker_compose_exec_json", _unexpected_exec_json)
    monkeypatch.setattr(module, "build_container", lambda: SimpleNamespace(channel_runtime=_FakeRuntime()))
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T08:02:00Z")

    report = module.probe_proactive_source_coverage(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "ready"
    assert report["source"] == "in_process_runtime:proactive_source_coverage"
    assert report["observation_repository"] == "PostgresObservationEventRepository"
    assert report["missing_lane_keys"] == []


def test_probe_proactive_source_coverage_falls_back_to_docker_when_in_process_errors(monkeypatch) -> None:
    module = _module()

    def _fake_exec_json(**_kwargs: object) -> tuple[int, dict[str, object], str, str]:
        return (
            0,
            {
                "probe_ok": True,
                "observation_repository": "PostgresObservationEventRepository",
                "rows": [
                    {
                        "channel": "product",
                        "event_type": "pocket_recording_archive_indexed",
                        "created_at": "2026-06-29T07:58:00Z",
                        "payload_keys": ["recording_id", "transcript_text", "location_name"],
                        "hints": [
                            "pocket_ai_audio_transcripts",
                            "shopping_and_vendor_signals",
                            "durable_profile_and_location_context",
                        ],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                    {
                        "channel": "gmail",
                        "event_type": "gmail.message",
                        "created_at": "2026-06-29T07:59:00Z",
                        "payload_keys": ["subject_sha256", "sender_sha256"],
                        "hints": ["google_workspace", "commitment_and_deadline_signals"],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                    {
                        "channel": "calendar",
                        "event_type": "calendar.event",
                        "created_at": "2026-06-29T08:00:00Z",
                        "payload_keys": ["event_id_sha256"],
                        "hints": ["calendar_and_renewal_signals"],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                    {
                        "channel": "telegram",
                        "event_type": "office_signal_ooda_evaluated",
                        "created_at": "2026-06-29T08:01:00Z",
                        "payload_keys": ["signal_id_sha256"],
                        "hints": [
                            "relationship_and_occasion_signals",
                            "shopping_and_vendor_signals",
                            "durable_profile_and_location_context",
                        ],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                ],
            },
            "",
            "",
        )

    monkeypatch.setenv("DATABASE_URL", "postgresql://ea:test@localhost/ea")
    monkeypatch.delenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", raising=False)
    monkeypatch.setattr(module, "_docker_cli_available", lambda: True)
    monkeypatch.setattr(module, "build_container", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T08:02:00Z")

    report = module.probe_proactive_source_coverage(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
    )

    assert report["probe_ok"] is True
    assert report["source"] == "docker_compose_exec"
    assert report["status"] == "ready"


def test_probe_proactive_source_coverage_suppresses_container_fallback_warning_when_docker_fallback_succeeds(
    monkeypatch,
    caplog,
) -> None:
    module = _module()

    def _fake_exec_json(**_kwargs: object) -> tuple[int, dict[str, object], str, str]:
        return (
            0,
            {
                "probe_ok": True,
                "observation_repository": "PostgresObservationEventRepository",
                "rows": [],
            },
            "",
            "",
        )

    def _fake_build_container():
        logging.getLogger("ea.container").warning(
            "postgres runtime profile unavailable, switching whole container to memory: failed to resolve host 'ea-db'"
        )
        return SimpleNamespace(channel_runtime=SimpleNamespace(_observations=object()))

    monkeypatch.setenv("DATABASE_URL", "postgresql://ea:test@localhost/ea")
    monkeypatch.delenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", raising=False)
    monkeypatch.setattr(module, "_docker_cli_available", lambda: True)
    monkeypatch.setattr(module, "build_container", _fake_build_container)
    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T08:02:00Z")

    caplog.set_level(logging.WARNING, logger="ea.container")
    report = module.probe_proactive_source_coverage(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
    )

    assert report["probe_ok"] is True
    assert report["source"] == "docker_compose_exec"
    assert "postgres runtime profile unavailable, switching whole container to memory" not in caplog.text


def test_probe_proactive_source_coverage_expands_window_when_initial_limit_is_truncated(monkeypatch) -> None:
    module = _module()
    calls: list[dict[str, object]] = []

    def _fake_exec_json(**kwargs: object) -> tuple[int, dict[str, object], str, str]:
        calls.append(dict(kwargs))
        if len(calls) == 1:
            return (
                0,
                {
                    "probe_ok": True,
                    "observation_repository": "PostgresObservationEventRepository",
                    "rows": [
                        {
                            "channel": "gmail",
                            "event_type": "gmail.message",
                            "created_at": "2026-06-29T07:59:00Z",
                            "payload_keys": ["subject_sha256", "sender_sha256"],
                            "hints": ["google_workspace", "commitment_and_deadline_signals"],
                            "source_id_sha256_present": True,
                            "raw_payload_exposed": False,
                        }
                    ]
                    * 400,
                },
                "",
                "",
            )
        return (
            0,
            {
                "probe_ok": True,
                "observation_repository": "PostgresObservationEventRepository",
                "rows": [
                    {
                        "channel": "product",
                        "event_type": "pocket_recording_archive_indexed",
                        "created_at": "2026-06-29T07:58:00Z",
                        "payload_keys": ["recording_id", "transcript_text", "location_name"],
                        "hints": [
                            "pocket_ai_audio_transcripts",
                            "relationship_and_occasion_signals",
                            "shopping_and_vendor_signals",
                            "durable_profile_and_location_context",
                        ],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                    {
                        "channel": "gmail",
                        "event_type": "gmail.message",
                        "created_at": "2026-06-29T07:59:00Z",
                        "payload_keys": ["subject_sha256", "sender_sha256"],
                        "hints": ["google_workspace", "commitment_and_deadline_signals"],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                    {
                        "channel": "calendar",
                        "event_type": "calendar.event",
                        "created_at": "2026-06-29T08:00:00Z",
                        "payload_keys": ["event_id_sha256"],
                        "hints": ["calendar_and_renewal_signals"],
                        "source_id_sha256_present": True,
                        "raw_payload_exposed": False,
                    },
                ],
            },
            "",
            "",
        )

    monkeypatch.setenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", "1")
    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T08:01:00Z")

    report = module.probe_proactive_source_coverage(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
    )

    assert len(calls) == 2
    assert calls[0]["timeout_seconds"] == 60.0
    assert calls[1]["timeout_seconds"] == 180.0
    assert report["observation_limit"] == 4000
    assert report["observation_row_count"] == 3
    assert "pocket_ai_audio_transcripts" not in report["missing_lane_keys"]


def test_parse_args_sync_pocket_transcripts_uses_proactive_principal_default(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", "cf-email:test@example.com")
    monkeypatch.setattr(sys, "argv", ["ea_live_ops.py", "sync-pocket-transcripts", "--mode", "backfill", "--limit", "25"])

    args = module.parse_args()

    assert args.command == "sync-pocket-transcripts"
    assert args.proactive_principal_id == "cf-email:test@example.com"
    assert args.mode == "backfill"
    assert args.limit == 25


def test_main_sync_pocket_transcripts_uses_long_default_timeout(monkeypatch, capsys) -> None:
    module = _module()
    captured: dict[str, object] = {}

    def _fake_sync_pocket_transcripts(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"probe_ok": True, "operator_text": "ok"}

    monkeypatch.setattr(module, "sync_pocket_transcripts", _fake_sync_pocket_transcripts)
    monkeypatch.setattr(sys, "argv", ["ea_live_ops.py", "sync-pocket-transcripts", "--format", "operator"])

    assert module.main() == 0
    assert captured["timeout_seconds"] == 120.0
    assert capsys.readouterr().out.strip() == "ok"


def test_sync_pocket_transcripts_reports_counts_without_raw_transcript_or_paths(monkeypatch) -> None:
    module = _module()

    def _fake_exec_json(**_kwargs: object) -> tuple[int, dict[str, object], str, str]:
        return (
            0,
            {
                "ok": True,
                "assistant_auto_actions": "manual_followup,none",
                "dangerous_auto_actions_enabled": False,
                "summary": {
                    "generated_at": "2026-06-29T08:02:00Z",
                    "mode": "incremental",
                    "recording_total": 2,
                    "total": 1,
                    "synced_total": 1,
                    "deduplicated_total": 0,
                    "suppressed_total": 1,
                    "failed_total": 0,
                    "archived_total": 1,
                    "archive_dismissed_total": 0,
                    "archive_failed_total": 0,
                    "teable_index_status": "synced",
                    "teable_index_row_total": 1,
                    "teable_index_sync_attempted": True,
                    "assistant_trigger_total": 1,
                    "assistant_trigger_executed_total": 1,
                    "assistant_trigger_blocked_total": 0,
                    "cursor_used": True,
                    "cursor_persisted": True,
                    "cursor_advanced": True,
                    "scan_truncated": False,
                    "location_matched_total": 1,
                    "location_unmatched_total": 0,
                },
            },
            "",
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _fake_exec_json)
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T08:03:00Z")

    report = module.sync_pocket_transcripts(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
    )

    assert report["probe_ok"] is True
    assert report["status"] == "synced"
    assert report["recording_total"] == 2
    assert report["synced_total"] == 1
    assert report["archived_total"] == 1
    assert report["assistant_auto_actions"] == "manual_followup,none"
    assert report["dangerous_auto_actions_enabled"] is False
    assert report["raw_payload_exposed"] is False
    assert report["raw_transcript_text_exposed"] is False
    assert report["raw_archive_path_exposed"] is False
    assert report["raw_credential_exposed"] is False
    serialized = json.dumps(report, sort_keys=True)
    assert "Order flowers" not in serialized
    assert "/mnt/pcloud" not in serialized


def test_sync_pocket_transcripts_maps_missing_api_key_to_blocked_next_action(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_docker_compose_exec_json",
        lambda **_kwargs: (
            0,
            {
                "ok": False,
                "reason": "RuntimeError:pocket_api_key_missing",
                "assistant_auto_actions": "manual_followup,none",
                "dangerous_auto_actions_enabled": False,
            },
            "",
            "",
        ),
    )

    report = module.sync_pocket_transcripts(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
    )

    assert report["probe_ok"] is True
    assert report["synced"] is False
    assert report["status"] == "blocked"
    assert report["blocking_reason"] == "RuntimeError:pocket_api_key_missing"
    assert report["next_action"] == "configure_pocket_api_key"


def test_sync_pocket_transcripts_maps_timeout_to_operator_blocker(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_docker_compose_exec_json",
        lambda **_kwargs: (
            124,
            {"ok": False, "reason": "TimeoutExpired:120s"},
            "",
            "",
        ),
    )

    report = module.sync_pocket_transcripts(
        principal_id="exec-1",
        compose_file="/docker/EA/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        output_format="operator",
    )

    assert report["probe_ok"] is True
    assert report["synced"] is False
    assert report["status"] == "blocked"
    assert report["blocking_reason"] == "TimeoutExpired:120s"
    assert report["next_action"] == "inspect_pocket_sync_runtime"
    assert "pocket_transcript_sync status=blocked" in str(report["operator_text"])


def test_parse_args_record_proactive_approval_uses_proactive_principal_default(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", "cf-email:test@example.com")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ea_live_ops.py",
            "record-proactive-approval",
            "--outcome",
            "approved",
            "--evidence",
            "Approved after review.",
        ],
    )

    args = module.parse_args()

    assert args.command == "record-proactive-approval"
    assert args.proactive_principal_id == "cf-email:test@example.com"
    assert args.outcome == "approved"


def test_parse_args_reissue_proactive_approval_uses_proactive_principal_default(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", "cf-email:test@example.com")
    monkeypatch.setattr(sys, "argv", ["ea_live_ops.py", "reissue-proactive-approval", "--dry-run"])

    args = module.parse_args()

    assert args.command == "reissue-proactive-approval"
    assert args.proactive_principal_id == "cf-email:test@example.com"
    assert args.dry_run is True


def test_main_probe_proactive_artifacts_emits_json(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "status": "ok",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
        },
    )
    monkeypatch.setattr(sys, "argv", ["ea_live_ops.py", "probe-proactive-artifacts"])

    assert module.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["probe_ok"] is True
    assert payload["status"] == "ok"


def test_main_probe_proactive_approval_capture_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "probe_proactive_approval_capture",
        lambda **kwargs: {
            "probe_ok": True,
            "ready": True,
            "operator_text": (
                "proactive_approval_capture status=ready "
                f"principal={kwargs['principal_id']}"
            ),
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ea_live_ops.py",
            "probe-proactive-approval-capture",
            "--principal-id",
            "principal-1",
            "--format",
            "operator",
        ],
    )

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "proactive_approval_capture status=ready principal=principal-1"


def test_resolve_whatsapp_matches_phone_hint_suffix_and_returns_chat_ref(monkeypatch) -> None:
    module = _module()
    binding = SimpleNamespace(
        binding_id="binding-1",
        principal_id="principal-1",
        auth_metadata_json={"session_ref": "tibor-wa-web", "session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages"},
    )
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: binding)
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        if suffix == "heyy-ai-routes":
            return {
                "routes": [
                    {"route_key": "default", "inbound_number_digits": "*", "ai_key": "empathetic_slow_typing_old_lady", "ai_name": "Herta"},
                    {"route_key": "436647916419", "inbound_number_digits": "436647916419", "ai_key": "empathetic_slow_typing_old_lady", "ai_name": "Herta"},
                ]
            }
        if suffix.startswith("conversations?"):
            return {
                "conversations": [
                    {
                        "chat_ref": "chat-ref-1",
                        "updated_at": "2026-06-23T10:05:00Z",
                        "messages": [{"sender_digits": "436647916419"}],
                    }
                ]
            }
        if suffix.startswith("recipients/"):
            return {
                "registered": True,
                "resolution_method": "phone_chat_id",
                "chat_id_kind": "phone",
            }
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args())

    assert report["status"] == "resolved"
    assert report["recipient_digits"] == "436647916419"
    assert report["route_key"] == "436647916419"
    assert report["chat_ref"] == "chat-ref-1"
    assert report["registered"] is True
    assert report["resolution_method"] == "phone_chat_id"


def test_resolve_whatsapp_returns_blocked_report_when_sidecar_conversations_not_ready(monkeypatch) -> None:
    module = _module()
    binding = SimpleNamespace(
        binding_id="binding-1",
        principal_id="principal-1",
        auth_metadata_json={"session_ref": "tibor-wa-web", "session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages"},
    )
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: binding)
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        if suffix == "heyy-ai-routes":
            return {
                "routes": [
                    {"route_key": "436647916419", "inbound_number_digits": "436647916419", "ai_key": "empathetic_slow_typing_old_lady", "ai_name": "Herta"}
                ]
            }
        if suffix.startswith("conversations?"):
            raise module.urllib.error.HTTPError(
                "https://wa-web.test/sessions/tibor-wa-web/conversations",
                409,
                "Conflict",
                {},
                io.BytesIO(b'{"ok":false,"reason":"session_not_ready","status":"qr_required"}'),
            )
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args())

    assert report["status"] == "resolved"
    assert report["recipient_digits"] == "436647916419"
    assert report["conversation_lookup_ready"] is False
    assert report["conversation_lookup_status"] == "qr_required"
    assert report["conversation_lookup_status_code"] == 409
    assert report["reason"] == "session_not_ready"


def test_resolve_whatsapp_falls_back_to_sidecar_when_binding_lookup_errors(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_load_whatsapp_binding",
        lambda _args: (_ for _ in ()).throw(RuntimeError("postgresql://user:secret@ea-db/ea")),
    )
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        if suffix == "heyy-ai-routes":
            return {
                "routes": [
                    {"route_key": "436647916419", "inbound_number_digits": "436647916419", "ai_key": "herta", "ai_name": "Herta"},
                ]
            }
        if suffix.startswith("conversations?"):
            return {
                "conversations": [
                    {
                        "chat_ref": "chat-ref-1",
                        "updated_at": "2026-06-23T10:05:00Z",
                        "messages": [{"sender_digits": "436647916419", "direction": "inbound", "from_me": False}],
                    }
                ]
            }
        if suffix.startswith("recipients/"):
            return {
                "registered": True,
                "resolution_method": "number_id",
                "chat_id_kind": "lid",
                "chat_ref": "chat-ref-1",
            }
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args())
    serialized = json.dumps(report)

    assert report["status"] == "resolved"
    assert report["reason"] == ""
    assert report["binding_lookup_status"] == "degraded_sidecar_fallback"
    assert report["binding_lookup_error"] == "RuntimeError"
    assert report["binding_lookup_recovered"] is True
    assert report["binding_lookup_fallback_source"] == "whatsapp_web_session_sidecar"
    assert report["route_lookup_ready"] is True
    assert report["chat_ref"] == "chat-ref-1"
    assert "secret" not in serialized
    assert "ea-db" not in serialized


def test_resolve_whatsapp_blocks_without_traceback_when_binding_and_sidecar_route_fail(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_load_whatsapp_binding",
        lambda _args: (_ for _ in ()).throw(RuntimeError("postgresql://user:secret@ea-db/ea")),
    )
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")
    monkeypatch.setattr(
        module,
        "_sidecar_get",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("sidecar token secret")),
    )

    report = module.resolve_whatsapp("*6419", args=_args())
    serialized = json.dumps(report)

    assert report["status"] == "blocked"
    assert report["reason"] == "OSError"
    assert report["binding_lookup_status"] == "error"
    assert report["binding_lookup_error"] == "RuntimeError"
    assert report["binding_lookup_recovered"] is False
    assert report["route_lookup_ready"] is False
    assert "sidecar token secret" not in serialized
    assert "postgresql://" not in serialized
    assert "ea-db" not in serialized


def test_send_whatsapp_dry_run_avoids_delivery(monkeypatch) -> None:
    module = _module()
    binding = SimpleNamespace(binding_id="binding-1", principal_id="principal-1")
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: binding)
    monkeypatch.setattr(
        module,
        "resolve_whatsapp",
        lambda _phone_hint, args: {
            "status": "resolved",
            "recipient_digits": "436647916419",
            "route_key": "436647916419",
        },
    )

    def _unexpected_post(**_kwargs):
        raise AssertionError("send should not run during dry-run")

    monkeypatch.setattr(module, "_sidecar_post", _unexpected_post)

    report = module.send_whatsapp(phone_hint="*6419", text="status update", args=_args(dry_run=True))

    assert report["sent"] is False
    assert report["reason"] == "dry_run"
    assert report["recipient_digits"] == "436647916419"
    assert report["binding_id"] == "binding-1"


def test_session_ref_falls_back_to_readiness_receipt_when_binding_and_env_are_missing(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    receipt_path = tmp_path / "readiness.json"
    receipt_path.write_text(json.dumps({"effective_session_ref": "tibor-wa-web"}), encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_READINESS_RECEIPT_PATH", receipt_path)
    monkeypatch.delenv("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", raising=False)

    assert module._session_ref(None) == "tibor-wa-web"


def test_session_ref_falls_back_to_readiness_receipt_when_binding_session_ref_is_blank(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    receipt_path = tmp_path / "readiness.json"
    receipt_path.write_text(json.dumps({"effective_session_ref": "tibor-wa-web"}), encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_READINESS_RECEIPT_PATH", receipt_path)
    monkeypatch.delenv("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", raising=False)
    binding = SimpleNamespace(
        auth_metadata_json={"session_ref": "", "session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages"}
    )

    assert module._session_ref(binding) == "tibor-wa-web"


def test_session_ref_prefers_runtime_readiness_receipt_when_published_receipt_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.delenv("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", raising=False)
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(tmp_path / "provider-ledger"))
    runtime_receipt = tmp_path / "provider-ledger" / "provider-health-cache" / "whatsapp_web_action_processor_readiness.generated.json"
    runtime_receipt.parent.mkdir(parents=True, exist_ok=True)
    runtime_receipt.write_text(json.dumps({"effective_session_ref": "tibor-wa-web"}), encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_READINESS_RECEIPT_PATH", tmp_path / "missing-readiness.json")

    assert module._session_ref(None) == "tibor-wa-web"


def test_resolve_whatsapp_without_binding_uses_recent_sender_to_narrow_routes(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: None)
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        if suffix == "heyy-ai-routes":
            return {
                "routes": [
                    {"route_key": "436647016419", "ai_key": "chummer_run_casey", "ai_name": "Casey from Chummer.run"},
                    {"route_key": "436647916419", "ai_key": "empathetic_slow_typing_old_lady", "ai_name": "Herta (Heyy Lady)"},
                ]
            }
        if suffix.startswith("conversations?"):
            return {
                "conversations": [
                    {
                        "chat_ref": "chat-ref-1",
                        "updated_at": "2026-06-23T10:05:00Z",
                        "messages": [{"sender_digits": "436647916419"}],
                    }
                ]
            }
        if suffix.startswith("recipients/"):
            return {
                "registered": True,
                "resolution_method": "number_id",
                "chat_id_kind": "lid",
            }
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args(database_url=""))

    assert report["status"] == "resolved"
    assert report["candidate_count"] == 1
    assert report["route_key"] == "436647916419"
    assert report["recipient_digits"] == "436647916419"
    assert report["chat_ref"] == "chat-ref-1"
    assert report["registered"] is True
    assert report["chat_id_kind"] == "lid"


def test_resolve_whatsapp_uses_recipient_chat_ref_when_conversation_match_is_unavailable(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: None)
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        if suffix == "heyy-ai-routes":
            return {
                "routes": [
                    {"route_key": "436647916419", "ai_key": "empathetic_slow_typing_old_lady", "ai_name": "Herta (Heyy Lady)"},
                ]
            }
        if suffix.startswith("conversations?"):
            return {
                "conversations": [
                    {
                        "chat_ref": "stale-self-message-only",
                        "timestamp": "2026-06-23T10:22:10.000Z",
                        "messages": [
                            {"sender_digits": "233385066778814", "direction": "outbound", "from_me": True, "message_timestamp": "2026-06-23T10:22:10.000Z"},
                        ],
                    }
                ]
            }
        if suffix.startswith("recipients/"):
            return {
                "registered": True,
                "resolution_method": "number_id",
                "chat_id_kind": "lid",
                "chat_ref": "chat-ref-1",
            }
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args(database_url=""))

    assert report["status"] == "resolved"
    assert report["recipient_digits"] == "436647916419"
    assert report["chat_ref"] == "chat-ref-1"
    assert report["resolution_method"] == "number_id"


def test_resolve_whatsapp_does_not_probe_partial_recipient_digits_when_no_real_match(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: None)
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")
    sidecar_calls: list[str] = []

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        sidecar_calls.append(suffix)
        if suffix == "heyy-ai-routes":
            return {"routes": []}
        if suffix.startswith("conversations?"):
            return {
                "conversations": [
                    {
                        "chat_ref": "chat-ref-1",
                        "updated_at": "2026-06-23T10:05:00Z",
                        "messages": [{"sender_digits": "6419", "direction": "inbound", "from_me": False}],
                    }
                ]
            }
        if suffix.startswith("recipients/"):
            raise AssertionError("partial recipient probe should not run")
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args(database_url=""))

    assert report["status"] == "unresolved"
    assert report["recipient_digits"] == ""
    assert report["registered"] is False
    assert sidecar_calls == [
        "heyy-ai-routes",
        "conversations?take=50&messages=1&fetch_timeout_ms=5000",
    ]


def test_resolve_whatsapp_ignores_outbound_sender_digit_pollution_and_uses_conversation_timestamp(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: None)
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        if suffix == "heyy-ai-routes":
            return {
                "routes": [
                    {"route_key": "436647916419", "ai_key": "empathetic_slow_typing_old_lady", "ai_name": "Herta (Heyy Lady)"},
                ]
            }
        if suffix.startswith("conversations?"):
            return {
                "conversations": [
                    {
                        "chat_ref": "older-real-match",
                        "timestamp": "2026-06-23T09:43:25.000Z",
                        "messages": [
                            {"sender_digits": "4369919226996", "direction": "inbound", "from_me": False, "message_timestamp": "2026-05-26T06:50:17.000Z"},
                            {"sender_digits": "436647916419", "direction": "outbound", "from_me": True, "message_timestamp": "2026-05-26T07:53:36.000Z"},
                        ],
                    },
                    {
                        "chat_ref": "stale-self-message-only",
                        "timestamp": "2026-06-08T14:18:13.000Z",
                        "messages": [
                            {"sender_digits": "436647916419", "direction": "outbound", "from_me": True, "message_timestamp": "2026-06-08T14:18:13.000Z"},
                        ],
                    },
                ]
            }
        if suffix.startswith("recipients/"):
            return {
                "registered": True,
                "resolution_method": "number_id",
                "chat_id_kind": "lid",
            }
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args(database_url=""))

    assert report["status"] == "resolved"
    assert report["chat_ref"] == ""
    assert report["route_key"] == "436647916419"
    assert report["recipient_digits"] == "436647916419"
    assert report["registered"] is True


def test_recent_conversation_match_uses_timestamp_when_updated_at_is_missing() -> None:
    module = _module()

    report = module._recent_conversation_match(
        {
            "conversations": [
                {
                    "chat_ref": "older",
                    "timestamp": "2026-06-23T09:14:23.000Z",
                    "messages": [
                        {"sender_digits": "436647916419", "direction": "inbound", "from_me": False, "message_timestamp": "2026-06-23T09:14:23.000Z"},
                    ],
                },
                {
                    "chat_ref": "newer",
                    "timestamp": "2026-06-23T09:43:25.000Z",
                    "messages": [
                        {"sender_digits": "436647916419", "direction": "inbound", "from_me": False, "message_timestamp": "2026-06-23T09:43:25.000Z"},
                    ],
                },
            ]
        },
        "*6419",
    )

    assert report == {"chat_ref": "newer", "sender_digits": "436647916419"}


def test_resolve_whatsapp_ambiguous_routes_do_not_probe_partial_phone_hint(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: None)
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")
    sidecar_calls: list[str] = []

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        sidecar_calls.append(suffix)
        if suffix == "heyy-ai-routes":
            return {
                "routes": [
                    {"route_key": "436647016419", "ai_key": "chummer_run_casey", "ai_name": "Casey from Chummer.run"},
                    {"route_key": "436647916419", "ai_key": "empathetic_slow_typing_old_lady", "ai_name": "Herta (Heyy Lady)"},
                ]
            }
        if suffix.startswith("conversations?"):
            return {"conversations": []}
        if suffix.startswith("recipients/"):
            raise AssertionError("recipient probe should not run for an ambiguous partial hint")
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args(database_url=""))

    assert report["status"] == "ambiguous"
    assert report["recipient_digits"] == ""
    assert report["registered"] is False
    assert sidecar_calls == [
        "heyy-ai-routes",
        "conversations?take=50&messages=1&fetch_timeout_ms=5000",
    ]


def test_send_whatsapp_without_binding_posts_to_sidecar(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: None)
    monkeypatch.setattr(
        module,
        "resolve_whatsapp",
        lambda _phone_hint, args: {
            "status": "resolved",
            "recipient_digits": "436647916419",
            "route_key": "436647916419",
            "session_ref": "tibor-wa-web",
            "chat_ref": "chat-ref-1",
        },
    )
    captured: dict[str, object] = {}

    def _fake_sidecar_post(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "message_ids": ["wamid.1"]}

    monkeypatch.setattr(module, "_sidecar_post", _fake_sidecar_post)

    report = module.send_whatsapp(phone_hint="*6419", text="status update", args=_args(database_url=""))

    assert report["sent"] is True
    assert report["delivery_transport"] == "whatsapp_web_session_sidecar"
    assert report["message_ids"] == ["wamid.1"]
    assert captured["suffix"] == "messages"
    assert captured["body"] == {
        "chat_ref": "chat-ref-1",
        "text": "status update",
        "pre_reply_delay_min_seconds": 0,
        "pre_reply_delay_max_seconds": 0,
        "typing_delay_ms": 0,
        "typing_delay_ms_per_character": 0,
        "typing_status_enabled": False,
    }


def test_send_whatsapp_reports_degraded_binding_fallback_without_secret(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_load_whatsapp_binding",
        lambda _args: (_ for _ in ()).throw(RuntimeError("postgresql://user:secret@ea-db/ea")),
    )
    monkeypatch.setattr(
        module,
        "resolve_whatsapp",
        lambda _phone_hint, args: {
            "status": "resolved",
            "recipient_digits": "436647916419",
            "route_key": "436647916419",
            "session_ref": "tibor-wa-web",
            "chat_ref": "chat-ref-1",
        },
    )
    monkeypatch.setattr(module, "_sidecar_post", lambda **_kwargs: {"ok": True, "message_ids": ["wamid.1"]})

    report = module.send_whatsapp(phone_hint="*6419", text="status update", args=_args())
    serialized = json.dumps(report)

    assert report["sent"] is True
    assert report["binding_lookup_status"] == "degraded_sidecar_fallback"
    assert report["binding_lookup_error"] == "RuntimeError"
    assert report["binding_lookup_recovered"] is True
    assert report["binding_lookup_fallback_source"] == "whatsapp_web_session_sidecar_send"
    assert "secret" not in serialized
    assert "postgresql://" not in serialized
    assert "ea-db" not in serialized


def test_send_whatsapp_with_binding_uses_sidecar_chat_ref_first(monkeypatch) -> None:
    module = _module()
    binding = SimpleNamespace(binding_id="binding-1", principal_id="principal-1")
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: binding)
    monkeypatch.setattr(
        module,
        "resolve_whatsapp",
        lambda _phone_hint, args: {
            "status": "resolved",
            "recipient_digits": "436647916419",
            "route_key": "436647916419",
            "chat_ref": "chat-ref-1",
            "session_ref": "tibor-wa-web",
        },
    )
    captured: list[dict[str, object]] = []

    def _fake_sidecar_post(**kwargs):
        captured.append(kwargs)
        return {"ok": True, "message_ids": ["wamid.1"]}

    monkeypatch.setattr(module, "_sidecar_post", _fake_sidecar_post)

    report = module.send_whatsapp(phone_hint="*6419", text="status update", args=_args())

    assert report["sent"] is True
    assert report["binding_id"] == "binding-1"
    assert report["principal_id"] == "principal-1"
    assert report["chat_ref_used"] is True
    assert len(captured) == 1
    assert captured[0]["body"] == {
        "chat_ref": "chat-ref-1",
        "text": "status update",
        "pre_reply_delay_min_seconds": 0,
        "pre_reply_delay_max_seconds": 0,
        "typing_delay_ms": 0,
        "typing_delay_ms_per_character": 0,
        "typing_status_enabled": False,
    }


def test_send_whatsapp_sidecar_exception_returns_no_secret_failure_receipt(monkeypatch) -> None:
    module = _module()
    binding = SimpleNamespace(binding_id="binding-1", principal_id="principal-1")
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: binding)
    monkeypatch.setattr(
        module,
        "resolve_whatsapp",
        lambda _phone_hint, args: {
            "status": "resolved",
            "recipient_digits": "436647916419",
            "route_key": "436647916419",
            "chat_ref": "chat-ref-1",
            "session_ref": "tibor-wa-web",
        },
    )
    monkeypatch.setattr(
        module,
        "_sidecar_post",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("https://wa-web.test/token secret")),
    )

    report = module.send_whatsapp(phone_hint="*6419", text="status update", args=_args())
    serialized = json.dumps(report)

    assert report["sent"] is False
    assert report["reason"] == "OSError"
    assert report["binding_lookup_status"] == "found"
    assert report["request_url_present"] is False
    assert report["message_ids"] == []
    assert report["chat_ref_used"] is True
    assert report["retry_attempted"] is False
    assert "status update" not in serialized
    assert "token secret" not in serialized
    assert "wa-web.test" not in serialized


def test_send_whatsapp_retries_with_recipient_when_chat_ref_is_stale(monkeypatch) -> None:
    module = _module()
    binding = SimpleNamespace(binding_id="binding-1", principal_id="principal-1")
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: binding)
    monkeypatch.setattr(
        module,
        "resolve_whatsapp",
        lambda _phone_hint, args: {
            "status": "resolved",
            "recipient_digits": "436647916419",
            "route_key": "436647916419",
            "chat_ref": "chat-ref-1",
            "session_ref": "tibor-wa-web",
        },
    )
    captured: list[dict[str, object]] = []

    def _fake_sidecar_post(**kwargs):
        captured.append(kwargs)
        if len(captured) == 1:
            return {"ok": False, "reason": "chat_ref_not_found"}
        return {"ok": True, "message_ids": ["wamid.2"]}

    monkeypatch.setattr(module, "_sidecar_post", _fake_sidecar_post)

    report = module.send_whatsapp(phone_hint="*6419", text="status update", args=_args())

    assert report["sent"] is True
    assert len(captured) == 2
    assert captured[0]["body"]["chat_ref"] == "chat-ref-1"
    assert captured[1]["body"]["to"] == "436647916419"
    assert "chat_ref" not in captured[1]["body"]
    assert report["message_ids"] == ["wamid.2"]


def test_send_whatsapp_retry_exception_returns_no_secret_failure_receipt(monkeypatch) -> None:
    module = _module()
    binding = SimpleNamespace(binding_id="binding-1", principal_id="principal-1")
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: binding)
    monkeypatch.setattr(
        module,
        "resolve_whatsapp",
        lambda _phone_hint, args: {
            "status": "resolved",
            "recipient_digits": "436647916419",
            "route_key": "436647916419",
            "chat_ref": "chat-ref-1",
            "session_ref": "tibor-wa-web",
        },
    )
    calls = 0

    def _fake_sidecar_post(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"ok": False, "reason": "chat_ref_not_found"}
        raise TimeoutError("sidecar bearer token secret")

    monkeypatch.setattr(module, "_sidecar_post", _fake_sidecar_post)

    report = module.send_whatsapp(phone_hint="*6419", text="status update", args=_args())
    serialized = json.dumps(report)

    assert report["sent"] is False
    assert report["reason"] == "TimeoutError"
    assert report["retry_attempted"] is True
    assert report["request_url_present"] is False
    assert calls == 2
    assert "status update" not in serialized
    assert "bearer token" not in serialized
    assert "secret" not in serialized


def test_send_telegram_dry_run_reuses_readiness_probe_without_sending(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T14:00:00Z")

    def _fake_probe_telegram_readiness(*, principal_id: str, timeout_seconds: float, output_format: str):
        assert principal_id == "principal-1"
        assert timeout_seconds == 30.0
        assert output_format == "json"
        return {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "reason": "",
            "principal_id": "principal-1",
            "binding_id": "binding-1",
            "next_action": "",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
            "chat_ref_present": True,
            "chat_ref_sha256": "c" * 64,
            "bot_key": "default",
            "bot_handle": "ea_concierge_bot",
            "bot_token_present": True,
            "runtime_container": "ea-api",
        }

    monkeypatch.setattr(module, "probe_telegram_readiness", _fake_probe_telegram_readiness)

    report = module.send_telegram(principal_id="principal-1", text="status update", dry_run=True)
    serialized = json.dumps(report, sort_keys=True)

    assert report["sent"] is False
    assert report["reason"] == "dry_run"
    assert report["ready"] is True
    assert report["readiness_probe_ok"] is True
    assert report["delivery_transport"] == "telegram_bot"
    assert report["chat_ref_sha256"] == "c" * 64
    assert report["next_action"] == ""
    assert report["next_action_href"] == ""
    assert report["next_action_label"] == ""
    assert report["next_action_method"] == ""
    assert report["bot_token_present"] is True
    assert report["timeout_seconds"] == 30.0
    assert report["observed_at"] == "2026-06-29T14:00:00Z"
    assert "123456789" not in serialized
    assert "telegram-token" not in serialized


def test_send_telegram_dry_run_enforces_minimum_readiness_timeout(monkeypatch) -> None:
    module = _module()
    observed: dict[str, object] = {}

    def _fake_probe_telegram_readiness(*, principal_id: str, timeout_seconds: float, output_format: str):
        observed["principal_id"] = principal_id
        observed["timeout_seconds"] = timeout_seconds
        observed["output_format"] = output_format
        return {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "reason": "",
            "principal_id": principal_id,
            "binding_id": "binding-1",
            "chat_ref_present": True,
            "chat_ref_sha256": "d" * 64,
            "bot_key": "default",
            "bot_handle": "ea_concierge_bot",
            "bot_token_present": True,
            "runtime_container": "ea-api",
        }

    monkeypatch.setattr(module, "probe_telegram_readiness", _fake_probe_telegram_readiness)

    report = module.send_telegram(principal_id="principal-1", text="status update", dry_run=True, timeout_seconds=15.0)

    assert observed == {
        "principal_id": "principal-1",
        "timeout_seconds": 30.0,
        "output_format": "json",
    }
    assert report["readiness_probe_ok"] is True
    assert report["timeout_seconds"] == 15.0


def test_send_telegram_executes_runtime_without_exposing_chat_secret(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T14:01:00Z")

    def _fake_exec_json(*, code: str, timeout_seconds: float):
        assert "send_telegram_message_for_principal" in code
        assert "build_container" not in code
        assert "build_tool_runtime" in code
        assert "disable_web_page_preview=True" in code
        assert "os._exit(0)" in code
        assert "flush=True" in code
        assert timeout_seconds == 75.0
        return (
            0,
            {
                "ok": True,
                "sent": True,
                "reason": "sent",
                "principal_id": "principal-1",
                "chat_ref_present": True,
                "chat_ref_sha256": "d" * 64,
                "bot_key": "default",
                "bot_handle": "ea_concierge_bot",
                "message_ids": ["1001"],
            },
            "ea-api",
        )

    monkeypatch.setattr(module, "_runtime_container_exec_json", _fake_exec_json)

    report = module.send_telegram(principal_id="principal-1", text="status update", dry_run=False, timeout_seconds=75.0)
    serialized = json.dumps(report, sort_keys=True)

    assert report["sent"] is True
    assert report["reason"] == "sent"
    assert report["delivery_transport"] == "telegram_bot"
    assert report["message_ids"] == ["1001"]
    assert report["message_count"] == 1
    assert report["runtime_container"] == "ea-api"
    assert report["timeout_seconds"] == 75.0
    assert report["observed_at"] == "2026-06-29T14:01:00Z"
    assert report["chat_ref_sha256"] == "d" * 64
    assert "123456789" not in serialized
    assert "telegram-token" not in serialized


def test_send_telegram_falls_back_to_in_process_delivery_when_runtime_exec_is_unavailable(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T14:01:30Z")
    monkeypatch.setattr(
        module,
        "_runtime_container_exec_json",
        lambda **_kwargs: (127, {"ok": False, "reason": "FileNotFoundError"}, "ea-api"),
    )

    class _Receipt:
        principal_id = "principal-1"
        chat_id = "1354554303"
        bot_key = "default"
        bot_handle = "ea_concierge_bot"
        message_ids = ("1002",)

    settings_calls: list[str] = []
    monkeypatch.setattr(module, "get_settings", lambda: settings_calls.append("get_settings") or object())
    monkeypatch.setattr(module, "build_tool_runtime", lambda _settings: "tool-runtime")
    monkeypatch.setattr(
        module,
        "send_telegram_message_for_principal",
        lambda tool_runtime, *, principal_id, text, disable_web_page_preview: (
            _Receipt()
            if tool_runtime == "tool-runtime"
            and principal_id == "principal-1"
            and text == "status update"
            and disable_web_page_preview is True
            else None
        ),
    )

    report = module.send_telegram(principal_id="principal-1", text="status update", dry_run=False, timeout_seconds=45.0)
    serialized = json.dumps(report, sort_keys=True)

    assert settings_calls == ["get_settings"]
    assert report["sent"] is True
    assert report["reason"] == "sent"
    assert report["source"] == "in_process:telegram_delivery.send_telegram_message_for_principal"
    assert report["runtime_container"] == ""
    assert report["message_ids"] == ["1002"]
    assert report["message_count"] == 1
    assert report["chat_ref_sha256"] == module._hash_text("1354554303")  # noqa: SLF001
    assert report["observed_at"] == "2026-06-29T14:01:30Z"
    assert "1354554303" not in serialized


def test_send_telegram_document_dry_run_reuses_readiness_without_exposing_document(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T14:02:00Z")
    monkeypatch.setattr(
        module,
        "probe_telegram_readiness",
        lambda principal_id, timeout_seconds=None, output_format="json": {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "reason": "",
            "principal_id": principal_id,
            "binding_id": "binding-1",
            "chat_ref_present": True,
            "chat_ref_sha256": "a" * 64,
            "bot_key": "default",
            "bot_handle": "ea_concierge_bot",
            "bot_token_present": True,
            "runtime_container": "ea-api",
        },
    )

    report = module.send_telegram_document(
        principal_id="principal-1",
        document_ref="/tmp/secret-qr.svg",
        caption="pairing",
        dry_run=True,
    )

    assert report["sent"] is False
    assert report["reason"] == "dry_run"
    assert report["ready"] is True
    assert report["readiness_probe_ok"] is True
    assert report["document_ref_present"] is True
    assert report["caption_present"] is True


def test_send_telegram_document_dry_run_enforces_minimum_readiness_timeout(monkeypatch) -> None:
    module = _module()
    observed: dict[str, object] = {}
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T14:03:00Z")
    monkeypatch.setattr(
        module,
        "probe_telegram_readiness",
        lambda principal_id, timeout_seconds=None, output_format="json": (
            observed.update(
                {
                    "principal_id": principal_id,
                    "timeout_seconds": timeout_seconds,
                    "output_format": output_format,
                }
            )
            or {
                "probe_ok": True,
                "ready": True,
                "status": "ready",
                "reason": "",
                "principal_id": principal_id,
                "binding_id": "binding-1",
                "chat_ref_present": True,
                "chat_ref_sha256": "a" * 64,
                "bot_key": "default",
                "bot_handle": "ea_concierge_bot",
                "bot_token_present": True,
                "runtime_container": "ea-api",
            }
        ),
    )

    report = module.send_telegram_document(
        principal_id="principal-1",
        document_ref="/tmp/proof.svg",
        caption="pairing",
        dry_run=True,
        timeout_seconds=15.0,
    )

    assert observed == {
        "principal_id": "principal-1",
        "timeout_seconds": 30.0,
        "output_format": "json",
    }
    assert report["readiness_probe_ok"] is True
    assert report["timeout_seconds"] == 15.0
    assert report["observed_at"] == "2026-06-29T14:03:00Z"
    assert "/tmp/secret-qr.svg" not in json.dumps(report, sort_keys=True)


def test_send_telegram_document_stages_local_file_into_runtime_container(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    document = tmp_path / "pairing.svg"
    document.write_text("<svg>qr</svg>", encoding="utf-8")
    removed: list[tuple[str, str]] = []
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-06-29T14:03:00Z")
    monkeypatch.setattr(
        module,
        "_runtime_container_stage_file",
        lambda path, timeout_seconds=20.0: (True, "ea-api", "/tmp/ea-live-ops-document.svg", ""),
    )
    monkeypatch.setattr(
        module,
        "_runtime_container_remove_file",
        lambda container, remote_path, timeout_seconds=10.0: removed.append((container, remote_path)),
    )

    def _fake_exec_json(*, code: str, timeout_seconds: float):
        assert str(document) not in code
        assert "/tmp/ea-live-ops-document.svg" in code
        assert "send_telegram_document_for_principal" in code
        assert "build_container" not in code
        assert "build_tool_runtime" in code
        assert "os._exit(0)" in code
        assert "flush=True" in code
        return (
            0,
            {
                "ok": True,
                "sent": True,
                "reason": "sent",
                "principal_id": "principal-1",
                "chat_ref_present": True,
                "chat_ref_sha256": "f" * 64,
                "bot_key": "default",
                "bot_handle": "ea_concierge_bot",
                "message_ids": ["2001"],
            },
            "ea-api",
        )

    monkeypatch.setattr(module, "_runtime_container_exec_json", _fake_exec_json)

    report = module.send_telegram_document(
        principal_id="principal-1",
        document_ref=str(document),
        caption="pairing",
        dry_run=False,
    )
    serialized = json.dumps(report, sort_keys=True)

    assert report["sent"] is True
    assert report["reason"] == "sent"
    assert report["message_ids"] == ["2001"]
    assert report["local_file_staged"] is True
    assert removed == [("ea-api", "/tmp/ea-live-ops-document.svg")]
    assert str(document) not in serialized


def test_send_telegram_video_dry_run_reuses_readiness_without_exposing_video(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-10T11:52:00Z")
    monkeypatch.setattr(
        module,
        "probe_telegram_readiness",
        lambda principal_id, timeout_seconds=None, output_format="json": {
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "reason": "",
            "principal_id": principal_id,
            "binding_id": "binding-1",
            "chat_ref_present": True,
            "chat_ref_sha256": "a" * 64,
            "bot_key": "default",
            "bot_handle": "ea_concierge_bot",
            "bot_token_present": True,
            "runtime_container": "ea-api",
        },
    )

    report = module.send_telegram_video(
        principal_id="principal-1",
        video_ref="/tmp/private-walkthrough.mp4",
        caption="PropertyQuarry walkthrough",
        dry_run=True,
    )
    serialized = json.dumps(report, sort_keys=True)

    assert report["sent"] is False
    assert report["reason"] == "dry_run"
    assert report["ready"] is True
    assert report["video_ref_present"] is True
    assert report["caption_present"] is True
    assert "/tmp/private-walkthrough.mp4" not in serialized


def test_send_telegram_video_stages_local_file_into_runtime_container(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    video = tmp_path / "walkthrough.mp4"
    video.write_bytes(b"video")
    removed: list[tuple[str, str]] = []
    monkeypatch.setattr(module, "_utc_now", lambda: "2026-07-10T11:53:00Z")
    monkeypatch.setattr(
        module,
        "_runtime_container_stage_file",
        lambda path, timeout_seconds=20.0: (True, "ea-api", "/tmp/ea-live-ops-video.mp4", ""),
    )
    monkeypatch.setattr(
        module,
        "_runtime_container_remove_file",
        lambda container, remote_path, timeout_seconds=10.0: removed.append((container, remote_path)),
    )

    def _fake_exec_json(*, code: str, timeout_seconds: float):
        assert str(video) not in code
        assert "/tmp/ea-live-ops-video.mp4" in code
        assert "send_telegram_video_for_principal" in code
        assert "fallback_audio_text" in code
        assert "build_tool_runtime" in code
        assert timeout_seconds == 120.0
        return (
            0,
            {
                "ok": True,
                "sent": True,
                "reason": "sent",
                "principal_id": "principal-1",
                "chat_ref_present": True,
                "chat_ref_sha256": "f" * 64,
                "bot_key": "default",
                "bot_handle": "ea_concierge_bot",
                "message_ids": ["3001"],
            },
            "ea-api",
        )

    monkeypatch.setattr(module, "_runtime_container_exec_json", _fake_exec_json)

    report = module.send_telegram_video(
        principal_id="principal-1",
        video_ref=str(video),
        caption="PropertyQuarry walkthrough",
        fallback_audio_text="PropertyQuarry walkthrough preview.",
        fallback_audio_language="en",
        dry_run=False,
    )
    serialized = json.dumps(report, sort_keys=True)

    assert report["sent"] is True
    assert report["reason"] == "sent"
    assert report["message_ids"] == ["3001"]
    assert report["local_file_staged"] is True
    assert removed == [("ea-api", "/tmp/ea-live-ops-video.mp4")]
    assert str(video) not in serialized


def test_main_send_telegram_emits_json(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="send-telegram",
            telegram_principal_id="principal-1",
            text="status update",
            dry_run=True,
            timeout_seconds=90.0,
        ),
    )

    def _fake_send_telegram(*, principal_id: str, text: str, dry_run: bool, timeout_seconds: float):
        assert principal_id == "principal-1"
        assert text == "status update"
        assert dry_run is True
        assert timeout_seconds == 90.0
        return {"sent": False, "reason": "dry_run", "ready": True, "delivery_transport": "telegram_bot"}

    monkeypatch.setattr(module, "send_telegram", _fake_send_telegram)

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"delivery_transport": "telegram_bot", "ready": True, "reason": "dry_run", "sent": False}


def test_main_probe_google_workspace_oauth_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="probe-google-workspace-oauth",
            expected_google_email="work.tibor.girschele@gmail.com",
            scope_bundle="full_workspace",
            observed_error="access_denied",
            error_description="",
            test_user_confirmed=False,
            probe_gcloud=True,
            telegram_principal_id="principal-1",
            send_telegram=False,
            dry_run=False,
            timeout_seconds=20.0,
            format="operator",
        ),
    )
    monkeypatch.setattr(
        module,
        "probe_google_workspace_oauth",
        lambda **_kwargs: {
            "probe_ok": True,
            "operator_text": "google oauth ok",
        },
    )

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "google oauth ok"


def test_main_probe_google_workspace_oauth_uses_receipt_context_when_runtime_context_omitted(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="probe-google-workspace-oauth",
            expected_google_email="work.tibor.girschele@gmail.com",
            scope_bundle="",
            observed_error="",
            error_description="",
            observed_google_email="",
            test_user_confirmed=False,
            probe_gcloud=True,
            telegram_principal_id="principal-1",
            send_telegram=False,
            dry_run=False,
            timeout_seconds=20.0,
            format="json",
        ),
    )
    monkeypatch.setattr(
        module,
        "_google_workspace_oauth_probe_context_from_receipt",
        lambda receipt_path="": {
            "scope_bundle": "full_workspace",
            "observed_error": "access_denied",
            "observed_google_email": "__expected__",
            "test_user_confirmed": True,
        },
    )
    captured: dict[str, object] = {}

    def _fake_probe_google_workspace_oauth(**kwargs):
        captured.update(kwargs)
        return {"probe_ok": True, "status": "ready_retry_required", "next_action": "retry_full_workspace_auth_with_approved_account"}

    monkeypatch.setattr(module, "probe_google_workspace_oauth", _fake_probe_google_workspace_oauth)

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ready_retry_required"
    assert captured["scope_bundle"] == "full_workspace"
    assert captured["observed_error"] == "access_denied"
    assert captured["observed_google_email"] == "__expected__"
    assert captured["test_user_confirmed"] is True


def test_main_probe_google_workspace_oauth_send_telegram_dry_run_fails_closed_when_not_ready(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="probe-google-workspace-oauth",
            expected_google_email="work.tibor.girschele@gmail.com",
            scope_bundle="full_workspace",
            observed_error="access_denied",
            error_description="",
            test_user_confirmed=False,
            probe_gcloud=True,
            telegram_principal_id="principal-1",
            send_telegram=True,
            dry_run=True,
            timeout_seconds=20.0,
            format="json",
        ),
    )
    monkeypatch.setattr(
        module,
        "probe_google_workspace_oauth",
        lambda **_kwargs: {
            "probe_ok": True,
            "status": "blocked_setup_required",
            "telegram_delivery": {"sent": False, "reason": "dry_run", "ready": False},
        },
    )

    assert module.main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["telegram_delivery"]["reason"] == "dry_run"


def test_main_send_telegram_dry_run_fails_closed_when_not_ready(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="send-telegram",
            telegram_principal_id="principal-1",
            text="status update",
            dry_run=True,
            timeout_seconds=20.0,
        ),
    )
    monkeypatch.setattr(
        module,
        "send_telegram",
        lambda **_kwargs: {
            "sent": False,
            "reason": "dry_run",
            "ready": False,
            "readiness_status": "probe_failed",
            "delivery_transport": "telegram_bot",
        },
    )

    assert module.main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "dry_run"
    assert payload["ready"] is False


def test_main_probe_provider_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(command="probe-provider", provider="unmixr", format="operator", timeout_seconds=9.0),
    )
    monkeypatch.setattr(
        module,
        "probe_provider",
        lambda provider, output_format="json", timeout_seconds=20.0: {"operator_text": f"{provider}:{output_format}:{timeout_seconds}"},
    )

    exit_code = module.main()

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "unmixr:operator:9.0"


def test_refresh_onemin_direct_api_dry_run_writes_resume_ready_receipt(monkeypatch, tmp_path) -> None:
    module = _module()
    output_path = tmp_path / "onemin-direct-refresh.json"
    monkeypatch.setattr(
        module,
        "_load_onemin_owner_rows_for_live_ops",
        lambda owner_ledger_path="": (
            Path("/tmp/onemin_slot_owners.local.json"),
            [
                {"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner@example.com", "owner_name": "Owner", "slot": "primary"},
                {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "owner_email": "owner2@example.com", "owner_name": "Owner 2", "slot": "fallback_1"},
            ],
            "",
        ),
    )

    report = module.refresh_onemin_direct_api(
        dry_run=True,
        output_json=str(output_path),
        account_labels=["ONEMIN_AI_API_KEY"],
        output_format="json",
    )

    assert report["status"] == "dry_run"
    assert report["selected_account_count"] == 1
    assert report["pending_account_count"] == 1
    assert report["next_action"] == "resume_onemin_direct_refresh"
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "dry_run"
    assert persisted["output_json"] == str(output_path)
    assert persisted["batch_size"] == 1
    assert persisted["refresh_transport"] == "direct_provider_api"
    assert persisted["proxy_mode"] == "direct_no_ui_proxy"
    assert persisted["proxy_pool_size"] == 0
    assert persisted["proxy_secret_material_exposed"] is False


def test_refresh_onemin_direct_api_configured_proxy_mode_preserves_proxy_env_without_leaking_it(
    monkeypatch,
    tmp_path,
) -> None:
    module = _module()
    output_path = tmp_path / "onemin-direct-refresh.json"
    monkeypatch.setattr(
        module,
        "_load_onemin_owner_rows_for_live_ops",
        lambda owner_ledger_path="": (
            Path("/tmp/onemin_slot_owners.local.json"),
            [{"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner@example.com", "owner_name": "Owner", "slot": "primary"}],
            "",
        ),
    )
    monkeypatch.setenv("ONEMIN_DEFAULT_PASSWORD", "secret")
    for key in (
        "EA_ONEMIN_DIRECT_API_PROXY_POOL",
        "ONEMIN_DIRECT_API_PROXY_SERVER",
        "ONEMIN_DIRECT_API_PROXY_POOL",
        "EA_UI_BROWSER_PROXY_SERVER",
        "EA_UI_BROWSER_PROXY_POOL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EA_ONEMIN_DIRECT_API_PROXY_SERVER", "http://proxy-user:proxy-pass@proxy.internal:3128")
    monkeypatch.setenv("ONEMIN_DIRECT_API_PROXY_POOL", "http://docker-only.internal:3128")
    monkeypatch.setenv("EA_UI_BROWSER_PROXY_POOL", "http://ui-fallback.internal:3128")
    monkeypatch.setattr(module, "_onemin_direct_refresh_reachable_proxy_count", lambda proxy_mode: 1)
    monkeypatch.setattr(module, "_onemin_direct_refresh_proxy_country", lambda proxy_mode: "CH")
    observed: dict[str, object] = {}

    from app.api.routes import providers as providers_route

    def _fake_refresh(**kwargs):
        observed["proxy_server"] = os.environ.get("EA_ONEMIN_DIRECT_API_PROXY_SERVER")
        observed["legacy_pool"] = os.environ.get("ONEMIN_DIRECT_API_PROXY_POOL")
        observed["ui_pool"] = os.environ.get("EA_UI_BROWSER_PROXY_POOL")
        return (
            [
                {
                    "account_label": "ONEMIN_AI_API_KEY",
                    "remaining_credits": 100.0,
                    "next_topup_at": "2026-08-13T00:00:00Z",
                    "refresh_backend": "onemin_api",
                    "observed_at": "2026-08-12T04:00:00Z",
                }
            ],
            [],
            [],
            1,
            0,
            False,
        )

    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", _fake_refresh)

    report = module.refresh_onemin_direct_api(
        output_json=str(output_path),
        proxy_mode="configured",
        expected_proxy_country="CH",
        output_format="json",
    )

    assert observed == {
        "proxy_server": "http://proxy-user:proxy-pass@proxy.internal:3128",
        "legacy_pool": None,
        "ui_pool": None,
    }
    assert report["status"] == "ready"
    assert report["proxy_mode"] == "configured_proxy_pool"
    assert report["proxy_pool_size"] == 1
    assert report["proxy_reachable_count"] == 1
    assert report["proxy_config_source"] == "ea_onemin"
    assert report["expected_proxy_country"] == "CH"
    assert report["proxy_country"] == "CH"
    assert report["proxy_country_verified"] is True
    assert report["proxy_country_source"] == "ipinfo_country_via_configured_proxy"
    assert report["proxy_secret_material_exposed"] is False
    serialized = json.dumps(report, sort_keys=True)
    assert "proxy-user" not in serialized
    assert "proxy-pass" not in serialized
    assert "proxy.internal" not in serialized


def test_refresh_onemin_direct_api_configured_proxy_mode_fails_closed_without_proxy(
    monkeypatch,
    tmp_path,
) -> None:
    module = _module()
    output_path = tmp_path / "onemin-direct-refresh.json"
    monkeypatch.setattr(
        module,
        "_load_onemin_owner_rows_for_live_ops",
        lambda owner_ledger_path="": (
            Path("/tmp/onemin_slot_owners.local.json"),
            [{"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner@example.com", "owner_name": "Owner", "slot": "primary"}],
            "",
        ),
    )
    for key in (
        "EA_ONEMIN_DIRECT_API_PROXY_SERVER",
        "EA_ONEMIN_DIRECT_API_PROXY_POOL",
        "ONEMIN_DIRECT_API_PROXY_SERVER",
        "ONEMIN_DIRECT_API_PROXY_POOL",
        "EA_UI_BROWSER_PROXY_SERVER",
        "EA_UI_BROWSER_PROXY_POOL",
    ):
        monkeypatch.delenv(key, raising=False)

    report = module.refresh_onemin_direct_api(
        dry_run=True,
        output_json=str(output_path),
        proxy_mode="configured",
        output_format="json",
    )

    assert report["probe_ok"] is False
    assert report["status"] == "blocked_proxy_not_configured"
    assert report["next_action"] == "configure_onemin_direct_api_proxy"
    assert report["proxy_pool_size"] == 0


def test_refresh_onemin_direct_api_configured_proxy_mode_fails_closed_when_proxy_is_unreachable(
    monkeypatch,
    tmp_path,
) -> None:
    module = _module()
    output_path = tmp_path / "onemin-direct-refresh.json"
    monkeypatch.setattr(
        module,
        "_load_onemin_owner_rows_for_live_ops",
        lambda owner_ledger_path="": (
            Path("/tmp/onemin_slot_owners.local.json"),
            [{"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner@example.com", "owner_name": "Owner", "slot": "primary"}],
            "",
        ),
    )
    monkeypatch.setenv("EA_ONEMIN_DIRECT_API_PROXY_SERVER", "http://unreachable.internal:3128")
    monkeypatch.delenv("EA_ONEMIN_DIRECT_API_PROXY_POOL", raising=False)
    monkeypatch.setattr(module, "_onemin_direct_refresh_reachable_proxy_count", lambda proxy_mode: 0)

    report = module.refresh_onemin_direct_api(
        dry_run=True,
        output_json=str(output_path),
        proxy_mode="configured",
        output_format="json",
    )

    assert report["probe_ok"] is False
    assert report["status"] == "blocked_proxy_unreachable"
    assert report["next_action"] == "start_or_repair_onemin_direct_api_proxy"
    assert report["proxy_pool_size"] == 1
    assert report["proxy_reachable_count"] == 0


def test_refresh_onemin_direct_api_configured_proxy_mode_rejects_wrong_country(
    monkeypatch,
    tmp_path,
) -> None:
    module = _module()
    output_path = tmp_path / "onemin-direct-refresh.json"
    monkeypatch.setattr(
        module,
        "_load_onemin_owner_rows_for_live_ops",
        lambda owner_ledger_path="": (
            Path("/tmp/onemin_slot_owners.local.json"),
            [{"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner@example.com", "owner_name": "Owner", "slot": "primary"}],
            "",
        ),
    )
    monkeypatch.setenv("EA_ONEMIN_DIRECT_API_PROXY_SERVER", "http://proxy.internal:3128")
    monkeypatch.delenv("EA_ONEMIN_DIRECT_API_PROXY_POOL", raising=False)
    monkeypatch.setattr(module, "_onemin_direct_refresh_reachable_proxy_count", lambda proxy_mode: 1)
    monkeypatch.setattr(module, "_onemin_direct_refresh_proxy_country", lambda proxy_mode: "DE")

    report = module.refresh_onemin_direct_api(
        dry_run=True,
        output_json=str(output_path),
        proxy_mode="configured",
        expected_proxy_country="CH",
        output_format="json",
    )

    assert report["probe_ok"] is False
    assert report["status"] == "blocked_proxy_country_mismatch"
    assert report["expected_proxy_country"] == "CH"
    assert report["proxy_country"] == "DE"
    assert report["proxy_country_verified"] is False
    assert report["next_action"] == "switch_to_expected_proxy_country"


def test_probe_onemin_direct_refresh_posture_prefers_latest_non_dry_run_receipt(monkeypatch, tmp_path) -> None:
    module = _module()
    root = tmp_path / "repo"
    ea_root = root / "ea"
    state_dir = root / ".state" / "onemin-direct-refresh"
    ea_state_dir = ea_root / "state"
    state_dir.mkdir(parents=True)
    ea_state_dir.mkdir(parents=True)
    live_receipt = state_dir / "onemin_direct_refresh_live.json"
    dry_run_receipt = ea_state_dir / "onemin_direct_refresh_dryrun.json"
    live_receipt.write_text(
        json.dumps(
            {
                "status": "rate_limited",
                "reason": "cloudflare_rate_limited",
                "observed_at": "2026-07-10T02:10:57Z",
                "next_action": "resume_onemin_direct_refresh_after_cooldown",
                "ready": False,
                "selected_account_count": 1,
                "pending_account_count": 1,
                "owner_row_count": 74,
                "attempted_count": 1,
                "current_run_refreshed_count": 0,
                "refreshed_count": 0,
                "error_count": 1,
                "error_code_counts": {"onemin_login_http_429": 1},
                "errors": [{"error": 'onemin_login_http_429:{"status":429}'}],
                "rate_limited": True,
                "batch_size": 1,
                "batch_backoff_seconds": 1.0,
                "max_rate_limit_sleep_seconds": 120.0,
                "continue_on_rate_limit": True,
                "refresh_transport": "direct_provider_api",
                "proxy_mode": "direct_no_ui_proxy",
                "telegram_delivery": {
                    "sent": True,
                    "reason": "sent",
                    "message_ids": ["3694"],
                    "source": "runtime_container_exec:telegram_delivery.send_telegram_message_for_principal",
                },
            }
        ),
        encoding="utf-8",
    )
    dry_run_receipt.write_text(
        json.dumps(
            {
                "status": "dry_run",
                "reason": "dry_run",
                "observed_at": "2026-07-10T02:13:04Z",
                "selected_account_count": 1,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "EA_ROOT", ea_root)
    monkeypatch.setattr(module, "DEFAULT_ONEMIN_DIRECT_REFRESH_STATE_DIR", state_dir)

    report = module.probe_onemin_direct_refresh_posture()

    assert report["checked"] is True
    assert report["probe_ok"] is True
    assert report["status"] == "rate_limited"
    assert report["receipt_name"] == "onemin_direct_refresh_live.json"
    assert report["next_action_href"] == "https://myexternalbrain.com/admin/goals"
    assert report["next_action_label"] == "Open goals"
    assert report["next_action_method"] == "get"
    assert report["controls"]["batch_size"] == 1
    assert report["controls"]["single_account_batch_mode"] is True
    assert report["controls"]["refresh_transport"] == "direct_provider_api"
    assert report["controls"]["proxy_pool_size"] == 0
    assert report["controls"]["proxy_country_verified"] is False
    assert report["retry_after_seconds"] == 300
    assert report["resume_not_before"] == "2026-07-10T02:15:57Z"
    assert report["telegram_delivery"]["sent"] is True
    assert report["telegram_delivery"]["message_count"] == 1


def test_refresh_onemin_direct_api_persists_telegram_delivery_receipt(monkeypatch, tmp_path) -> None:
    module = _module()
    output_path = tmp_path / "onemin-direct-refresh.json"
    monkeypatch.setattr(
        module,
        "_load_onemin_owner_rows_for_live_ops",
        lambda owner_ledger_path="": (
            Path("/tmp/onemin_slot_owners.local.json"),
            [{"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner@example.com", "owner_name": "Owner", "slot": "primary"}],
            "",
        ),
    )
    monkeypatch.setattr(
        module,
        "send_telegram",
        lambda **_kwargs: {
            "sent": True,
            "reason": "sent",
            "message_ids": ["3694"],
            "source": "runtime_container_exec:telegram_delivery.send_telegram_message_for_principal",
        },
    )

    report = module.refresh_onemin_direct_api(
        dry_run=True,
        output_json=str(output_path),
        send_telegram_to_principal="principal-1",
        output_format="json",
    )

    assert report["telegram_delivery"]["sent"] is True
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["telegram_delivery"]["sent"] is True
    assert persisted["telegram_delivery"]["message_ids"] == ["3694"]


def test_refresh_onemin_direct_api_reports_partial_rate_limit_and_merges_resume_receipt(monkeypatch, tmp_path) -> None:
    module = _module()
    output_path = tmp_path / "onemin-direct-refresh.json"
    output_path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "account_label": "ONEMIN_AI_API_KEY",
                        "remaining_credits": 15025.0,
                        "next_topup_at": "2026-07-11T00:59:12Z",
                        "refresh_backend": "onemin_api",
                        "observed_at": "2026-07-10T01:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "_load_onemin_owner_rows_for_live_ops",
        lambda owner_ledger_path="": (
            Path("/tmp/onemin_slot_owners.local.json"),
            [
                {"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner@example.com", "owner_name": "Owner", "slot": "primary"},
                {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "owner_email": "owner2@example.com", "owner_name": "Owner 2", "slot": "fallback_1"},
                {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_2", "owner_email": "owner3@example.com", "owner_name": "Owner 3", "slot": "fallback_2"},
            ],
            "",
        ),
    )
    monkeypatch.setenv("ONEMIN_DEFAULT_PASSWORD", "secret")
    monkeypatch.setattr(
        module,
        "_run_onemin_direct_api_refresh",
        lambda **_kwargs: (
            [
                {
                    "account_label": "ONEMIN_AI_API_KEY_FALLBACK_1",
                    "remaining_credits": 4041342.0,
                    "next_topup_at": "2026-07-10T11:45:01Z",
                    "refresh_backend": "onemin_api",
                    "observed_at": "2026-07-10T01:45:50Z",
                }
            ],
            [],
            [
                {
                    "account_label": "ONEMIN_AI_API_KEY_FALLBACK_2",
                    "error": 'onemin_login_http_429:{"status":429}',
                }
            ],
            2,
            0,
            True,
        ),
    )

    report = module.refresh_onemin_direct_api(
        dry_run=False,
        output_json=str(output_path),
        output_format="json",
    )

    assert report["status"] == "partial_rate_limited"
    assert report["resume_success_count"] == 1
    assert report["current_run_refreshed_count"] == 1
    assert report["refreshed_count"] == 2
    assert report["rate_limited"] is True
    assert report["error_code_counts"] == {"onemin_login_http_429": 1}
    assert report["retry_after_seconds"] == 300
    assert str(report["resume_not_before"]).endswith("Z")
    assert report["remaining_credits_total"] == 4056367.0
    assert report["next_action"] == "resume_onemin_direct_refresh_after_cooldown"
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(persisted["results"]) == 2


def test_onemin_direct_refresh_retry_after_prefers_provider_hint() -> None:
    module = _module()

    seconds = module._onemin_direct_refresh_retry_after_seconds(
        [
            {
                "error": 'onemin_login_http_429:{"message":"Too many requests after 206 seconds","retryAfter":206}'
            }
        ]
    )

    assert seconds == 221


def test_refresh_onemin_direct_api_blocks_when_owner_ledger_missing(monkeypatch, tmp_path) -> None:
    module = _module()
    output_path = tmp_path / "onemin-direct-refresh.json"
    monkeypatch.setattr(module, "_load_onemin_owner_rows_for_live_ops", lambda owner_ledger_path="": (None, [], "owner_ledger_missing"))

    report = module.refresh_onemin_direct_api(output_json=str(output_path))

    assert report["probe_ok"] is False
    assert report["status"] == "blocked_owner_ledger_missing"
    assert report["next_action"] == "repair_onemin_owner_ledger_projection"


def test_main_refresh_onemin_direct_api_returns_zero_for_partial_rate_limit(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="refresh-onemin-direct-api",
            account_labels=[],
            max_accounts=0,
            owner_ledger_path="",
            output_json="",
            batch_size=1,
            batch_backoff_seconds=1.0,
            max_rate_limit_sleep_seconds=120.0,
            continue_on_rate_limit=True,
            telegram_principal_id="principal-1",
            send_telegram=False,
            dry_run=False,
            timeout_seconds=180.0,
            format="json",
            telegram_operator_streams="",
        ),
    )
    monkeypatch.setattr(
        module,
        "refresh_onemin_direct_api",
        lambda **_kwargs: {
            "probe_ok": True,
            "status": "partial_rate_limited",
            "ready": False,
            "reason": "cloudflare_rate_limited",
            "output_json": "/tmp/onemin-direct-refresh.json",
        },
    )

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "partial_rate_limited"


def test_main_refresh_onemin_direct_api_preserves_explicit_zero_backoff_controls(monkeypatch, capsys) -> None:
    module = _module()
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(
            command="refresh-onemin-direct-api",
            account_labels=[],
            max_accounts=0,
            owner_ledger_path="",
            output_json="",
            batch_size=1,
            batch_backoff_seconds=0.0,
            max_rate_limit_sleep_seconds=0.0,
            continue_on_rate_limit=False,
            proxy_mode="direct",
            expected_proxy_country="",
            telegram_principal_id="",
            send_telegram=False,
            dry_run=True,
            timeout_seconds=30.0,
            format="json",
            telegram_operator_streams="",
        ),
    )

    def _fake_refresh(**kwargs):
        observed.update(kwargs)
        return {"probe_ok": True, "status": "dry_run", "ready": False, "reason": "dry_run"}

    monkeypatch.setattr(module, "refresh_onemin_direct_api", _fake_refresh)

    assert module.main() == 0
    json.loads(capsys.readouterr().out)
    assert observed["batch_backoff_seconds"] == 0.0
    assert observed["max_rate_limit_sleep_seconds"] == 0.0
    assert observed["continue_on_rate_limit"] is False
