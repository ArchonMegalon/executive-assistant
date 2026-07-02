from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFY_OODA_PATH = ROOT / "scripts" / "verify_proactive_ooda.py"


def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _base_args(module, receipt_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        principal_id="cf-email:tibor.girschele@gmail.com",
        signals_json="",
        discovery_json="",
        opportunity_rules_json="",
        state_path="state/proactive_ooda_notified.json",
        receipt_path="",
        max_items=5,
        observation_lookback_hours=24,
        observation_limit=50,
        skip_observation_source=False,
        skip_workspace_source=True,
        paused=False,
        armed_send=False,
        pause_reason="",
        quiet_hours_start="",
        quiet_hours_end="",
        quiet_hours_timezone="UTC",
        quiet_hours_allow_high_priority=True,
        interruption_budget_limit=0,
        interruption_budget_window_hours=24,
        interruption_budget_allow_high_priority=True,
        stage_packet_dir="",
        safe_work_result_dir="",
        stage_packets=True,
        safe_work_results=True,
        require_stage_packets=True,
        require_safe_work_results=True,
        require_source=True,
        require_telegram=True,
        delivery_route_mode="lightweight",
        require_receipt_observation=True,
        operator_status_receipt=str(receipt_path),
        allow_operator_status_receipt_fallback=True,
    )


def _ready_stage_packets() -> dict[str, object]:
    return {
        "enabled": True,
        "required": True,
        "ready": True,
        "output_dir": "/tmp/proactive-stage-packets",
        "output_dir_writable": True,
        "expected_packet_count": 0,
        "packet_count": 0,
        "safe_work_order_count": 0,
        "errors": [],
    }


def _ready_safe_work_results() -> dict[str, object]:
    return {
        "enabled": True,
        "required": True,
        "ready": True,
        "output_dir": "/tmp/proactive-safe-work-results",
        "output_dir_writable": True,
        "expected_result_count": 0,
        "result_count": 0,
        "schema_valid_count": 0,
        "errors": [],
    }


def _host_stage_packet_failure() -> dict[str, object]:
    payload = _ready_stage_packets()
    payload["ready"] = False
    payload["errors"] = ["stage_packet_count_mismatch"]
    return payload


def _host_safe_work_result_failure() -> dict[str, object]:
    payload = _ready_safe_work_results()
    payload["ready"] = False
    payload["errors"] = ["safe_work_result_count_mismatch"]
    return payload


def _operator_status_receipt(module) -> dict[str, object]:
    return {
        "contract_name": module.OPERATOR_STATUS_CONTRACT,
        "generated_at": "2026-07-02T16:00:00Z",
        "generated_by": module.OPERATOR_STATUS_GENERATOR,
        "source_git_head": module.resolve_source_state_head(module.ROOT),
        "source_state_fingerprint": module.resolve_source_worktree_fingerprint(module.ROOT),
        "status": "ready_with_live_receipt",
        "actionable_count": 1,
        "source_coverage": {
            "checked": True,
            "probe_ok": True,
            "status": "ready",
            "source": "docker_compose_exec",
            "observed_lane_count": 8,
            "observation_row_count": 400,
            "lanes": [
                {
                    "key": "google_workspace",
                    "observed": True,
                    "status": "observed",
                }
            ],
        },
        "delivery_route": {
            "ready": True,
            "selected_channel": "telegram",
            "selected_transport": "telegram",
            "selected_by": "env_telegram_fallback",
            "selected_reason": "Telegram bot token and proactive chat id available",
            "binding_id_present": False,
            "recipient_ref_hash_present": True,
            "available_channels": ["telegram"],
            "errors": [],
            "route_error": "",
            "recovery_hint": "",
            "next_action": "",
            "preference_count": 0,
            "policy_count": 0,
            "follow_up_hint_count": 0,
        },
        "delivery_guard": {
            "delivery_state": "approval_capture_pending",
            "deferred_reason": "",
            "armed_send": True,
            "operator_paused": False,
            "quiet_hours_active": False,
            "interruption_budget_limit": 0,
            "interruption_budget_used": 0,
        },
        "context_grounding": {
            "current_packet_context_grounding": {
                "grounded": True,
                "item_count": 1,
                "grounded_item_count": 1,
                "candidate_assessment_count": 0,
                "preference_count": 0,
                "requirement_count": 2,
                "deadline_count": 0,
            }
        },
        "stage_packets": _ready_stage_packets(),
        "safe_work_results": _ready_safe_work_results(),
        "approval_capture": {
            "telegram_binding_ready": True,
        },
        "receipt_observation_count": 812,
    }


def _patch_host_blindness(module, monkeypatch) -> None:
    monkeypatch.setattr(module, "discover_postgres_observation_signals", lambda **kwargs: [])
    monkeypatch.setattr(
        module,
        "_delivery_route_status",
        lambda *args, **kwargs: {
            "mode": "lightweight",
            "ready": False,
            "selected_channel": "",
            "selected_transport": "",
            "selected_by": "",
            "selected_reason": "",
            "binding_id_present": False,
            "recipient_ref_hash_present": False,
            "available_channels": [],
            "errors": ["telegram_notification_not_configured"],
            "route_error": "telegram_notification_not_configured",
            "recovery_hint": "Link Telegram delivery.",
            "next_action": "configure_telegram_proactive_delivery",
            "preference_count": 0,
            "policy_count": 0,
            "follow_up_hint_count": 0,
        },
    )
    monkeypatch.setattr(module, "_telegram_ready", lambda principal_id: False)
    monkeypatch.setattr(module, "_receipt_observation_count", lambda principal_id: 0)
    monkeypatch.setattr(
        module,
        "_delivery_guard_status",
        lambda *args, **kwargs: {
            "delivery_state": "no_actionable_items",
            "deferred_reason": "",
            "armed_send": False,
            "operator_paused": False,
            "pause_reason_present": False,
            "quiet_hours_configured": False,
            "quiet_hours_active": False,
            "quiet_hours_allow_high_priority": True,
            "interruption_budget_limit": 0,
            "interruption_budget_window_hours": 24,
            "interruption_budget_used": 0,
            "interruption_budget_exhausted": False,
            "interruption_budget_allow_high_priority": True,
            "has_high_priority": False,
        },
    )
    monkeypatch.setattr(module, "_persisted_delivery_guard_status", lambda args: {})
    monkeypatch.setattr(module, "_stage_packet_status", lambda *args, **kwargs: _host_stage_packet_failure())
    monkeypatch.setattr(module, "_safe_work_result_status", lambda *args, **kwargs: _host_safe_work_result_failure())


def test_build_report_uses_fresh_operator_status_receipt_when_host_is_blind(tmp_path: Path, monkeypatch) -> None:
    module = _load_script(VERIFY_OODA_PATH, "verify_proactive_ooda_fallback_test")
    receipt_path = tmp_path / "operator_status.json"
    receipt_path.write_text(json.dumps(_operator_status_receipt(module), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _patch_host_blindness(module, monkeypatch)

    report = module._build_report(_base_args(module, receipt_path))  # noqa: SLF001

    assert report["ok"] is True
    assert report["verification_source"] == "operator_status_receipt"
    assert report["source_mode"] == "docker_compose_exec"
    assert report["source_count_label"] == "observations"
    assert report["signal_count"] == 400
    assert report["actionable_count"] == 1
    assert report["telegram_ready"] is True
    assert report["workspace_source_status"] == "ready"
    assert report["receipt_observation_count"] == 812
    assert report["delivery_route"]["ready"] is True
    assert report["delivery_guard"]["delivery_state"] == "approval_capture_pending"
    assert report["context_grounding"]["grounded"] is True
    assert report["stage_packets"]["ready"] is True
    assert report["safe_work_results"]["ready"] is True
    assert report["errors"] == []
    assert "operator_status_receipt_fallback_applied" in report["warnings"]


def test_build_report_ignores_stale_operator_status_receipt(tmp_path: Path, monkeypatch) -> None:
    module = _load_script(VERIFY_OODA_PATH, "verify_proactive_ooda_stale_fallback_test")
    receipt = _operator_status_receipt(module)
    receipt["source_git_head"] = "stale-source-head"
    receipt["source_state_fingerprint"] = "stale-source-fingerprint"
    receipt_path = tmp_path / "operator_status.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _patch_host_blindness(module, monkeypatch)

    report = module._build_report(_base_args(module, receipt_path))  # noqa: SLF001

    assert report["ok"] is False
    assert report["verification_source"] == "host_runtime"
    assert "no_signal_source_configured" in report["errors"]
    assert "telegram_notification_not_configured" in report["errors"]
    assert "receipt_observation_missing" in report["errors"]
    assert "stage_packet_count_mismatch" in report["errors"]
    assert "safe_work_result_count_mismatch" in report["errors"]
