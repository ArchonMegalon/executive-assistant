from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import run_proactive_ooda


def _base_args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        dry_run=False,
        armed_send=False,
        principal_id="cf-email:tibor.girschele@gmail.com",
        state_path="state/proactive_ooda_notified.json",
        receipt_path=str(tmp_path / "state" / "proactive_ooda_latest_run.generated.json"),
        goal_posture_json="",
        operator_action_required_digest_json="",
        operator_action_required_digest_state_path="",
    )


def test_followthrough_refreshes_google_workspace_oauth_readiness_when_runtime_blocked(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    root_module = getattr(run_proactive_ooda, "_module", run_proactive_ooda)
    monkeypatch.setattr(root_module, "ROOT", tmp_path)
    observed_google_builder: dict[str, object] = {}

    def _operator_status_default_report_args() -> argparse.Namespace:
        return argparse.Namespace()

    def _operator_status(**kwargs: object) -> dict[str, object]:
        return {
            "status": "ready_with_recovery_action",
            "reason": "source_health_google_workspace:google_oauth_invalid_grant",
            "source_health": {
                "issues": [
                    {
                        "source_key": "google_workspace",
                        "status": "unhealthy",
                        "error_code": "google_oauth_invalid_grant",
                        "operator_action_required": True,
                        "user_action_required": True,
                    }
                ]
            },
        }

    def _gold_acceptance(**kwargs: object) -> dict[str, object]:
        return {"status": "blocked_operator_runtime_posture"}

    def _goal_posture(**kwargs: object) -> dict[str, object]:
        return {"status": "active_with_blockers", "operator_action_queue": [{"id": "queue-1"}]}

    def _operator_action_required_digest(**kwargs: object) -> dict[str, object]:
        return {
            "status": "suppressed_duplicate",
            "notification_status": "suppressed_duplicate",
            "item_count": 1,
        }

    def _operator_action_required_dedupe_proof(**kwargs: object) -> dict[str, object]:
        return {"status": "pass"}

    def _google_workspace_oauth_readiness(**kwargs: object) -> dict[str, object]:
        observed_google_builder.update(kwargs)
        return {
            "contract_name": "ea.google_workspace_oauth_readiness.v1",
            "generated_at": "2026-07-08T14:00:00Z",
            "status": "ready_retry_required",
            "reauth_required_reason": "google_oauth_invalid_grant",
            "operator_action": {
                "next_action": "retry_full_workspace_auth_with_approved_account",
            },
        }

    monkeypatch.setattr(
        root_module,
        "_load_followthrough_builders",
        lambda: {
            "operator_status_default_report_args": _operator_status_default_report_args,
            "operator_status": _operator_status,
            "gold_acceptance": _gold_acceptance,
            "goal_posture": _goal_posture,
            "google_workspace_oauth_readiness": _google_workspace_oauth_readiness,
            "operator_action_required_digest": _operator_action_required_digest,
            "operator_action_required_dedupe_proof": _operator_action_required_dedupe_proof,
        },
    )

    receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_packet_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_work_result_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    summary = root_module._materialize_followthrough_artifacts(  # noqa: SLF001
        _base_args(tmp_path),
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
        current_runtime_artifacts_present=False,
    )

    readiness_path = tmp_path / ".codex-studio" / "published" / "ea_google_workspace_oauth_readiness.generated.json"
    readiness_payload = json.loads(readiness_path.read_text(encoding="utf-8"))
    assert observed_google_builder["reauth_required_reason"] == "google_oauth_invalid_grant"
    assert observed_google_builder["probe_gcloud"] is False
    assert summary["google_workspace_oauth_readiness"]["status"] == "ready_retry_required"
    assert summary["google_workspace_oauth_readiness"]["reauth_required_reason"] == "google_oauth_invalid_grant"
    assert summary["google_workspace_oauth_readiness"]["next_action"] == "retry_full_workspace_auth_with_approved_account"
    assert readiness_payload["status"] == "ready_retry_required"
    assert readiness_payload["reauth_required_reason"] == "google_oauth_invalid_grant"


def test_followthrough_skips_google_workspace_oauth_readiness_when_no_runtime_blocker(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    root_module = getattr(run_proactive_ooda, "_module", run_proactive_ooda)
    monkeypatch.setattr(root_module, "ROOT", tmp_path)

    def _operator_status_default_report_args() -> argparse.Namespace:
        return argparse.Namespace()

    def _operator_status(**kwargs: object) -> dict[str, object]:
        return {
            "status": "ready",
            "reason": "",
            "source_health": {
                "issues": []
            },
        }

    def _unexpected_google_workspace_oauth_readiness(**kwargs: object) -> dict[str, object]:
        raise AssertionError("google readiness should not be refreshed without a Google blocker")

    monkeypatch.setattr(
        root_module,
        "_load_followthrough_builders",
        lambda: {
            "operator_status_default_report_args": _operator_status_default_report_args,
            "operator_status": _operator_status,
            "gold_acceptance": lambda **kwargs: {"status": "blocked_real_world_acceptance"},
            "goal_posture": lambda **kwargs: {"status": "active_with_blockers", "operator_action_queue": []},
            "google_workspace_oauth_readiness": _unexpected_google_workspace_oauth_readiness,
            "operator_action_required_digest": lambda **kwargs: {
                "status": "suppressed_duplicate",
                "notification_status": "suppressed_duplicate",
                "item_count": 0,
            },
            "operator_action_required_dedupe_proof": lambda **kwargs: {"status": "pass"},
        },
    )

    summary = root_module._materialize_followthrough_artifacts(  # noqa: SLF001
        _base_args(tmp_path),
        receipt_path=tmp_path / "state" / "proactive_ooda_latest_run.generated.json",
        stage_packet_dir=tmp_path / "state" / "proactive_ooda_stage_packets",
        safe_work_result_dir=tmp_path / "state" / "proactive_ooda_safe_work_results",
        current_runtime_artifacts_present=False,
    )

    readiness_path = tmp_path / ".codex-studio" / "published" / "ea_google_workspace_oauth_readiness.generated.json"
    assert summary["google_workspace_oauth_readiness"] == {
        "path": ".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json",
        "status": "not_needed",
        "reason": "no_google_workspace_runtime_blocker",
    }
    assert readiness_path.exists() is False
