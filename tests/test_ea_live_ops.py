from __future__ import annotations

import importlib.util
import io
import json
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
    assert report["next_action"] == "restore_whatsapp_web_session_sidecar_readiness"
    assert report["sidecar_qr_required"] is True
    assert report["sidecar_qr_present"] is True
    assert report["processor_container_enabled"] is True
    assert "whatsapp_readiness status=blocked" in str(report["operator_text"])
    assert "qr=required:true,present:true,age_seconds:35,fresh:true" in str(report["operator_text"])
    assert "raw-secret-qr" not in serialized


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
            "source": "runtime_container_exec:telegram_delivery.resolve_primary_telegram_binding",
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
        assert "resolve_primary_telegram_binding" in code
        assert timeout_seconds == 20.0
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


def test_main_probe_telegram_readiness_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: Namespace(command="probe-telegram-readiness", telegram_principal_id="principal-1", format="operator"),
    )

    def _fake_probe_telegram_readiness(*, principal_id: str, output_format: str):
        assert principal_id == "principal-1"
        assert output_format == "operator"
        return {"probe_ok": True, "operator_text": "telegram ok"}

    monkeypatch.setattr(module, "probe_telegram_readiness", _fake_probe_telegram_readiness)

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "telegram ok"


def test_probe_proactive_route_normalizes_live_runtime_route_status(monkeypatch) -> None:
    module = _module()
    receipt_paths: list[str] = []

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


def test_probe_proactive_route_checks_workspace_source_by_default(monkeypatch) -> None:
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
    assert report["status"] == "blocked_local_runtime"
    assert report["blocking_reason"] == "google_workspace_signal_source_unhealthy:google_oauth_invalid_grant"
    assert report["next_action"] == "reauthorize_google_workspace_binding"
    assert report["next_action_href"] == (
        "https://myexternalbrain.com/app/actions/google/connect?"
        "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
    )
    assert report["next_action_label"] == "Reconnect Google workspace"
    assert report["next_action_method"] == "get"
    assert "--skip-workspace-source" not in seen_verify_command


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
    assert report["packet_ref"] == "stage_packet:pkt-live"
    assert report["staged_artifact_ref"] == "safe_work_result:res-live"
    assert report["approval_capture_surface_ready"] is True
    assert report["approval_capture_surface_pending_count"] == 1
    assert len(commands) == 1


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
        if "finalize_proactive_ooda_approval_outcome" in command[2]:
            return (
                0,
                {
                    "approval_outcome": {
                        "approval_outcome_recorded": True,
                        "accepted": True,
                        "status": "accepted_redacted",
                        "outcome_id": "approval-1",
                    },
                    "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
                    "operator_status_path": "/app/.codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
                    "gold_acceptance_path": "/app/.codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
                    "teable_sync": {"status": "synced", "sync_attempted": True, "blocked_reason": ""},
                },
                '{"approval_outcome":{"approval_outcome_recorded":true,"accepted":true,"status":"accepted_redacted","outcome_id":"approval-1"}}',
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
    assert len(commands) == 2


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


def test_parse_args_probe_proactive_artifacts_uses_runtime_defaults(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv("EA_PROACTIVE_OODA_RUNTIME_SERVICE", "ea-proactive-ooda")
    monkeypatch.setattr(sys, "argv", ["ea_live_ops.py", "probe-proactive-artifacts"])

    args = module.parse_args()

    assert args.command == "probe-proactive-artifacts"
    assert args.runtime_service == "ea-proactive-ooda"
    assert args.format == "json"


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


def test_probe_proactive_source_coverage_reports_required_lanes_without_raw_payload(monkeypatch) -> None:
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
    assert "pocket_ai_audio_transcripts" not in report["missing_lane_keys"]
    assert report["privacy"]["raw_payload_exposed"] is False
    assert report["privacy"]["raw_transcript_text_exposed"] is False
    assert report["privacy"]["raw_credential_exposed"] is False
    serialized = json.dumps(report, sort_keys=True)
    assert "Order flowers" not in serialized
    assert "/mnt/pcloud" not in serialized


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
    assert report["binding_lookup_status"] == "error"
    assert report["binding_lookup_error"] == "RuntimeError"
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


def test_main_probe_provider_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(module, "parse_args", lambda: Namespace(command="probe-provider", provider="unmixr", format="operator"))
    monkeypatch.setattr(module, "probe_provider", lambda provider, output_format="json": {"operator_text": f"{provider}:{output_format}"})

    exit_code = module.main()

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "unmixr:operator"
