from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.verify_proactive_ooda_operator_status as verifier


def _write_receipt(path: Path, **payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _base_payload() -> dict[str, object]:
    return {
        "contract_name": "ea.proactive_ooda_operator_status.v1",
        "generated_by": "scripts/materialize_proactive_ooda_operator_status.py",
        "head_semantics": "source_state",
        "source_state_fingerprint": "source-fingerprint-123",
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "status": "ready_local_runtime",
        "summary": "Proactive OODA route and packet runtime are locally ready; mirror a host-visible live receipt when the next real packet is sent.",
        "next_action": "run_or_mirror_live_proactive_ooda_receipt",
        "goal_completion_claim_allowed": False,
        "live_delivery_claim_allowed": False,
        "route_probe_source": "host_verifier",
        "route_probe_runtime_service": "",
        "route_probe_observed_at": "",
        "delivery_route_ready": True,
        "delivery_route_error": "",
        "delivery_recovery_hint": "",
        "delivery_next_action": "",
        "delivery_route": {"ready": True, "route_error": "", "next_action": ""},
        "delivery_guard": {"delivery_state": "eligible"},
        "stage_packets": {"ready": True},
        "safe_work_results": {"ready": True},
        "live_receipt_checked": False,
        "live_receipt": {"ok": False, "receipt_path": ""},
        "gmail_draft_followthrough": {
            "checked": False,
            "status": "not_checked",
            "source": "",
            "observed_at": "",
            "blocking_reason": "",
            "next_action": "",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
            "action": "",
            "work_type": "",
            "execution_observation_present": False,
            "execution_status": "",
            "execution_saved_at": "",
            "recipient_email_hash_present": False,
            "gmail_draft_id_hash_present": False,
            "gmail_message_id_hash_present": False,
            "draft_folder_url_hash_present": False,
            "raw_execution_payload_exposed": False,
        },
        "verifier_commands": [
            "make verify-proactive-ooda",
            "make verify-proactive-ooda-live-receipt",
            "make verify-proactive-ooda-operator-status",
        ],
        "remaining_external_proofs": [
            "real proactive OODA packet accepted with routed delivery, approved-source or transcript signal, live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, current-packet, stale-approval, and decision facts, and explicit approval outcome"
        ],
        "rules": [
            "This receipt proves proactive OODA route, guard, and packet-runtime posture only; it does not prove a human accepted the packet.",
            "Delivery recovery hints may be mirrored here and in Teable, but they remain operator aids rather than canonical queue truth.",
            "A live sent receipt can prove one routed delivery happened, but it does not by itself prove ordinary-use usefulness or approval correctness.",
            "Gold-production claims still require accepted proactive packets, routed delivery proof, approved-source or transcript signal evidence, live browse evidence, an auditor-passed chosen candidate, staged reversible artifacts, mirrored Teable current/stale delivery and decision facts, explicit approval outcome evidence, and consent-gated irreversible actions.",
        ],
    }


@pytest.fixture(autouse=True)
def _stable_source_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verifier, "_source_fingerprint", lambda path=verifier.ROOT: "source-fingerprint-123")


def test_proactive_ooda_operator_status_verifier_accepts_valid_receipt(tmp_path: Path, monkeypatch) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload["source_git_head"] = "source-head-123"
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_operator_status_verifier_accepts_post_commit_head_change_when_source_fingerprint_matches(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload["source_git_head"] = "pre-commit-source-head"
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "post-commit-source-head")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_operator_status_verifier_rejects_source_fingerprint_drift(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload["source_git_head"] = "pre-commit-source-head"
    payload["source_state_fingerprint"] = "old-source-fingerprint"
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "post-commit-source-head")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "receipt is stale relative to current source HEAD" in issues
    assert "receipt is stale relative to current source fingerprint" in issues


def test_proactive_ooda_operator_status_verifier_rejects_live_receipt_overclaim(tmp_path: Path, monkeypatch) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_live_receipt",
            "live_receipt_checked": True,
            "live_receipt": {"ok": False, "receipt_path": str(tmp_path / "receipt.json")},
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "ready_with_live_receipt status requires live_receipt.ok=true" in issues


def test_proactive_ooda_operator_status_verifier_rejects_gmail_draft_execution_overclaim(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload["source_git_head"] = "source-head-123"
    payload["gmail_draft_followthrough"] = {
        **dict(payload["gmail_draft_followthrough"]),
        "status": "already_executed",
        "action": "save_gmail_draft",
        "execution_status": "",
        "execution_observation_present": False,
        "gmail_draft_id_hash_present": False,
        "raw_execution_payload_exposed": True,
    }
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "gmail_draft_followthrough.raw_execution_payload_exposed must remain false" in issues
    assert "already_executed gmail_draft_followthrough requires execution_status=executed" in issues
    assert "already_executed gmail_draft_followthrough requires execution_observation_present=true" in issues
    assert "already_executed gmail_draft_followthrough requires gmail_draft_id_hash_present=true" in issues


def test_proactive_ooda_operator_status_verifier_rejects_incomplete_docker_probe_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "",
            "route_probe_observed_at": "",
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "docker_compose_exec route probes require route_probe_runtime_service" in issues
    assert "docker_compose_exec route probes require route_probe_observed_at" in issues


def test_proactive_ooda_operator_status_verifier_rejects_ready_approval_surface_without_live_pending_callback(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "approval_capture_surface": {
                "ready": True,
                "selected_channel": "telegram",
                "callback_dir_writable": True,
                "approval_outcome_path": "state/proactive_ooda_latest_approval_outcome.generated.json",
                "callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
                "current_packet_live_pending_count": 0,
            },
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "ready approval_capture_surface requires current_packet_live_pending_count>0" in issues


def test_proactive_ooda_operator_status_verifier_rejects_clear_status_when_approval_capture_is_pending(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_live_receipt",
            "live_receipt_checked": True,
            "live_receipt": {"ok": True, "receipt_path": str(tmp_path / "receipt.json")},
            "next_action": "maintain_proactive_ooda_runtime",
            "operator_action_state": "clear",
            "approval_capture_surface": {
                "ready": True,
                "selected_channel": "telegram",
                "callback_dir_writable": True,
                "approval_outcome_path": "state/proactive_ooda_latest_approval_outcome.generated.json",
                "callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
                "current_packet_live_pending_count": 1,
            },
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "ready approval_capture_surface with ready_with_live_receipt requires approval-capture next_action" in issues
    assert "ready approval_capture_surface with ready_with_live_receipt requires operator_action_state=approval_capture_pending" in issues
    assert "ready approval_capture_surface with ready_with_live_receipt requires delivery_guard.delivery_state=approval_capture_pending" in issues
    assert "ready approval_capture_surface with ready_with_live_receipt requires delivery_guard.user_action_required=true" in issues
    assert "ready approval_capture_surface with ready_with_live_receipt requires actionable_count to include pending approval surfaces" in issues


def test_proactive_ooda_operator_status_verifier_requires_reauth_surface_for_google_reauth(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "blocked_local_runtime",
            "summary": "Proactive OODA routing is available, but Google workspace needs reauthorization before EA can rely on that source (google_oauth_invalid_grant).",
            "next_action": "reauthorize_google_workspace_binding",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "reauthorize_google_workspace_binding requires next_action_href" in issues
    assert "reauthorize_google_workspace_binding requires next_action_label" in issues
    assert "reauthorize_google_workspace_binding requires next_action_method=get" in issues


def test_proactive_ooda_operator_status_verifier_allows_google_workspace_recovery_without_route_error(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_recovery_action",
            "summary": "Proactive OODA routing is available, but Google workspace needs reauthorization before EA can rely on that source (google_oauth_invalid_grant).",
            "reason": "google_workspace_signal_source_unhealthy:google_oauth_invalid_grant",
            "next_action": "maintain_proactive_ooda_runtime",
            "delivery_route_error": "",
            "delivery_route": {"ready": True, "route_error": "", "next_action": ""},
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []
