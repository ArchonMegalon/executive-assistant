from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_proactive_ooda_live_receipt.py"


def _module():
    spec = importlib.util.spec_from_file_location("verify_proactive_ooda_live_receipt", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _archived_sent_receipt() -> dict[str, object]:
    return {
        "generated_at": "2026-07-08T08:56:20.470522+00:00",
        "notification_status": "sent",
        "dry_run": False,
        "item_count": 1,
        "delivery_channel": "telegram",
        "delivery_message_ids": ["delivery-msg-1"],
        "telegram_message_ids": ["telegram-msg-1"],
        "principal_id_hash": _sha256("principal"),
        "notified_ref_hashes": [_sha256("notified-ref")],
        "delivery_guard": {
            "delivery_state": "eligible",
            "deferred_reason": "",
            "quiet_hours_active": False,
            "interruption_budget_exhausted": False,
            "notification_requires_user_action": True,
        },
    }


def _latest_quiet_receipt_with_followthrough() -> dict[str, object]:
    return {
        "generated_at": "2026-07-08T13:29:08.941863+00:00",
        "notification_status": "skipped_no_items",
        "dry_run": False,
        "item_count": 0,
        "delivery_channel": "",
        "delivery_message_ids": [],
        "telegram_message_ids": [],
        "error_code": "",
        "delivery_guard": {
            "delivery_state": "no_actionable_items",
            "deferred_reason": "",
            "quiet_hours_active": False,
            "interruption_budget_exhausted": False,
            "notification_requires_user_action": False,
        },
        "followthrough_artifacts": {
            "status": "ok",
            "reason": "",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "operator_status": {
                "path": ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
                "status": "ready_with_recovery_action",
                "reason": "source_health_google_workspace:google_oauth_invalid_grant",
            },
            "gold_acceptance": {
                "path": ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
                "status": "blocked_operator_runtime_posture",
            },
            "goal_posture": {
                "path": ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json",
                "status": "blocked_real_world_acceptance",
                "operator_action_queue_count": 7,
            },
            "operator_action_required_digest": {
                "path": ".codex-studio/published/ea_operator_action_required_digest.generated.json",
                "input_path": ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json",
                "state_path": ".runtime/ea_operator_action_required_digest_state.json",
                "refresh_source": False,
                "status": "suppressed_duplicate",
                "notification_status": "suppressed_duplicate",
                "item_count": 1,
            },
        },
    }


def test_verify_receipt_prefers_archived_sent_delivery_and_latest_quiet_followthrough(tmp_path: Path) -> None:
    module = _module()
    module._module.ROOT = tmp_path
    latest_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    archive_path = (
        tmp_path
        / "state"
        / "proactive_ooda_run_receipts"
        / "20260708T085620_470522_0000-sent-84c3c5227cb4.json"
    )
    _write_json(latest_path, _latest_quiet_receipt_with_followthrough())
    _write_json(archive_path, _archived_sent_receipt())

    report = module.verify_receipt(latest_path)

    assert report["ok"] is True
    assert report["errors"] == []
    assert report["archived_delivery_receipt_used"] is True
    assert report["archived_sent_receipt_used"] is True
    assert report["archived_operator_safe_mirror_receipt_used"] is False
    assert report["receipt_path"] == str(archive_path)
    assert report["latest_receipt_path"] == str(latest_path)
    assert report["notification_status"] == "sent"
    assert report["latest_notification_status"] == "skipped_no_items"
    assert report["delivery_mode"] == "telegram_sent"
    assert report["delivery_message_count"] == 1
    assert report["telegram_message_count"] == 1
    assert report["followthrough_status"] == "ok"
    assert report["followthrough_operator_status"] == "ready_with_recovery_action"
    assert report["followthrough_gold_acceptance_status"] == "blocked_operator_runtime_posture"
    assert report["followthrough_goal_posture_status"] == "blocked_real_world_acceptance"
    assert report["followthrough_goal_posture_queue_count"] == 7
    assert report["followthrough_digest_status"] == "suppressed_duplicate"
    assert report["followthrough_digest_notification_status"] == "suppressed_duplicate"
    assert report["followthrough_digest_item_count"] == 1


def test_verify_receipt_uses_archived_sent_followthrough_when_latest_quiet_receipt_omits_it(tmp_path: Path) -> None:
    module = _module()
    latest_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    archive_path = tmp_path / "state" / "proactive_ooda_run_receipts" / "20260708T085620Z-sent.json"
    latest_payload = _latest_quiet_receipt_with_followthrough()
    latest_payload.pop("followthrough_artifacts", None)
    archive_payload = _archived_sent_receipt()
    archive_payload["followthrough_artifacts"] = dict(
        _latest_quiet_receipt_with_followthrough().get("followthrough_artifacts") or {}
    )
    _write_json(latest_path, latest_payload)
    _write_json(archive_path, archive_payload)

    report = module.verify_receipt(latest_path)

    assert report["ok"] is True
    assert report["archived_delivery_receipt_used"] is True
    assert report["errors"] == []
    assert report["receipt_path"] == str(archive_path)
    assert report["latest_receipt_path"] == str(latest_path)
    assert report["followthrough_status"] == "ok"
    assert report["followthrough_source"] == "delivery_receipt"


def test_runtime_container_verifier_retries_after_invalid_json(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "DEFAULT_RUNTIME_VERIFY_ATTEMPTS", 2)
    monkeypatch.setattr(module, "DEFAULT_RUNTIME_VERIFY_RETRY_DELAY_SECONDS", 0.0)
    observed_execs: list[list[str]] = []
    exec_calls = {"count": 0}

    def _fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        rendered = list(command)
        if rendered[:2] == ["docker", "inspect"]:
            return SimpleNamespace(returncode=0, stdout="running\n", stderr="")
        observed_execs.append(rendered)
        exec_calls["count"] += 1
        if exec_calls["count"] == 1:
            return SimpleNamespace(returncode=0, stdout="not-json", stderr="")
        return SimpleNamespace(returncode=0, stdout='{"ok": true, "notification_status": "sent"}', stderr="")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    payload = module._verify_receipt_via_runtime_container("ea-proactive-ooda")

    assert exec_calls["count"] == 2
    assert observed_execs[0][:4] == ["docker", "exec", "ea-proactive-ooda", "python"]
    assert payload == {
        "ok": True,
        "notification_status": "sent",
        "runtime_container_delegated": True,
        "runtime_container": "ea-proactive-ooda",
    }
