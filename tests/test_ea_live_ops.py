from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from argparse import Namespace
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

    assert report["status"] == "ready"
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
    monkeypatch.setattr(module, "_runtime_container_preflight", lambda: {})
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
    assert report["remaining"] == 3
    assert report["unit"] == "configured_api_key_slots"
    assert "remaining=3 configured_api_key_slots" in str(report["operator_text"])
    assert "observed_at=2026-06-23T10:00:00Z" in str(report["operator_text"])


def test_probe_provider_unmixr_treats_optional_preflight_warnings_as_operationally_pass(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_runtime_container_preflight", lambda: {})
    monkeypatch.setattr(
        module,
        "audiobook_runtime_preflight",
        lambda: {
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
    monkeypatch.setattr(
        module,
        "_runtime_container_preflight",
        lambda: {
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
        },
    )
    monkeypatch.setattr(module, "audiobook_runtime_preflight", lambda: {"status": "fail", "provider": {"api_key_slot_count": 0, "voice_catalog_count": 0}})
    monkeypatch.setattr(module, "_provider_display_name", lambda _provider_key: "Unmixr AI")
    monkeypatch.setattr(module, "_runtime_container_name", lambda: "ea-api")

    report = module.probe_provider("unmixr", output_format="json")

    assert report["status"] == "pass"
    assert report["remaining"] == 3
    assert report["raw"]["runtime_container"] == "ea-api"
    assert report["raw"]["preflight_status"] == "warn"


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
    assert report["status"] == "ready"
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
    )

    caption = str(observed["caption"])
    assert report["pair_url_scope"] == "host_local"
    assert report["pair_url_actionable_from_telegram"] is False
    assert report["telegram_caption_includes_pair_url"] is False
    assert "pair_url=http://127.0.0.1:8098" not in caption
    assert "pair_url_scope=host_local" in caption
    assert "scan the attached QR" in caption
    assert Path(str(observed["document_ref"])).is_file()


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
            "pair_url": "https://wa-web.test/sessions/tibor-wa-web/pair",
            "qr_svg_url": "https://wa-web.test/sessions/tibor-wa-web/qr.svg",
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
        "probe_proactive_route",
        lambda **_kwargs: {
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
            "route_report": {"raw": "large-private-payload"},
            "observed_at": "2026-06-29T14:55:04Z",
            "source": "proactive_route_probe",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
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
    )

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

    assert report["contract_name"] == "ea.operator_readiness.v1"
    assert report["probe_ok"] is True
    assert report["ready"] is False
    assert report["status"] == "ready_with_actions"
    assert report["component_count"] == 6
    assert [item["key"] for item in report["components"]] == [
        "telegram",
        "whatsapp",
        "whatsapp_pairing",
        "teable_recovery",
        "proactive_route",
        "proactive_artifacts",
    ]
    assert report["blocked_count"] == 2
    assert report["attention_required_count"] == 3
    assert {"component_key": "whatsapp_pairing", "component_label": "WhatsApp Web pairing recovery", "action": "scan_whatsapp_web_qr", "reason": ""} in report["next_actions"]
    assert not any(
        item["component_key"] == "whatsapp" and item["action"] == "scan_whatsapp_web_qr"
        for item in report["next_actions"]
    )
    assert "operator_readiness status=ready_with_actions" in str(report["operator_text"])
    assert "next=whatsapp_pairing:scan_whatsapp_web_qr" in str(report["operator_text"])
    assert "raw-secret-qr" not in serialized
    assert "123456789" not in serialized
    assert "telegram-token" not in serialized
    assert "tbl-secret-id" not in serialized
    assert "https://wa-web.test/sessions/tibor-wa-web/pair" not in serialized
    assert "large-private-payload" not in serialized


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
            timeout_seconds=5.0,
        ),
    )

    def _fake_probe_operator_readiness(**kwargs):
        assert kwargs["telegram_principal_id"] == "principal-1"
        assert kwargs["proactive_principal_id"] == "principal-1"
        assert kwargs["timeout_seconds"] == 5.0
        assert kwargs["output_format"] == "operator"
        return {"probe_ok": True, "operator_text": "operator readiness ok"}

    monkeypatch.setattr(module, "probe_operator_readiness", _fake_probe_operator_readiness)

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "operator readiness ok"


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
    assert receipt_paths == ["/data/provider-ledger/proactive_ooda_run_receipts/20260626T180300Z-sent-abc123.json"]
    assert "--delivery-route-mode" in route_commands[0]
    assert route_commands[0][route_commands[0].index("--delivery-route-mode") + 1] == "lightweight"


def test_probe_proactive_route_reports_unarmed_deferred_runtime(monkeypatch) -> None:
    module = _module()

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
    assert report["next_action_label"] == "Open approval capture"
    assert report["next_action_method"] == "get"


def test_probe_proactive_route_skips_workspace_source_for_route_readiness(monkeypatch) -> None:
    module = _module()
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


def test_probe_proactive_artifacts_reads_runtime_bundle(monkeypatch) -> None:
    module = _module()

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
        lambda: {
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
                "stage_packet": {"packet_ref": "stage_packet:pkt-live"},
                "safe_work_result": {"result_ref": "safe_work_result:res-live"},
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
    assert "EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH" in probe_code
    assert "property_scout_sync_completed" in probe_code
    assert "pocket_ai_audio_transcripts" not in report["missing_lane_keys"]
    assert report["privacy"]["raw_payload_exposed"] is False
    assert report["privacy"]["raw_transcript_text_exposed"] is False
    assert report["privacy"]["raw_credential_exposed"] is False
    serialized = json.dumps(report, sort_keys=True)
    assert "Order flowers" not in serialized
    assert "/mnt/pcloud" not in serialized


def test_probe_proactive_source_coverage_surfaces_flat_search_filter(monkeypatch) -> None:
    module = _module()

    def _fake_exec_json(**_kwargs: object) -> tuple[int, dict[str, object], str, str]:
        return (
            0,
            {
                "probe_ok": True,
                "observation_repository": "PostgresObservationEventRepository",
                "flat_search_enabled": False,
                "excluded_event_types": ["property_scout_sync_completed"],
                "excluded_event_type_counts": {"property_scout_sync_completed": 3},
                "rows": [
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
    assert report["flat_search_enabled"] is False
    assert report["excluded_event_types"] == ["property_scout_sync_completed"]
    assert report["excluded_event_type_counts"] == {"property_scout_sync_completed": 3}
    for lane in report["lanes"]:
        assert "property_scout_sync_completed" not in lane["evidence_event_types"]


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
    assert report["bot_token_present"] is True
    assert report["timeout_seconds"] == 30.0
    assert report["observed_at"] == "2026-06-29T14:00:00Z"
    assert "123456789" not in serialized
    assert "telegram-token" not in serialized


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
    assert report["observed_at"] == "2026-06-29T14:02:00Z"
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
    monkeypatch.setattr(module, "parse_args", lambda: Namespace(command="probe-provider", provider="unmixr", format="operator"))
    monkeypatch.setattr(module, "probe_provider", lambda provider, output_format="json": {"operator_text": f"{provider}:{output_format}"})

    exit_code = module.main()

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "unmixr:operator"
