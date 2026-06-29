from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.verify_proactive_ooda_gold_acceptance as verifier


def _write_receipt(path: Path, **payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _base_payload() -> dict[str, object]:
    return {
        "contract_name": "ea.proactive_ooda_gold_acceptance.v1",
        "generated_by": "scripts/materialize_proactive_ooda_gold_acceptance.py",
        "head_semantics": "source_state",
        "status": "ready_for_approval_outcome_capture",
        "summary": "A proactive OODA packet has local gold-proof runtime evidence; capture the redacted approval outcome next.",
        "next_action": "record_proactive_ooda_approval_outcome",
        "goal_completion_claim_allowed": False,
        "gold_claim_allowed": False,
        "proofs": {
            "operator_runtime_posture": {"present": True, "status": "pass"},
            "routed_delivery": {"present": True, "status": "pass"},
            "action_required_only_delivery": {"present": True, "status": "pass"},
            "assistant_grade_packet_quality": {"present": True, "status": "pass", "issues": []},
            "browser_action_contract": {
                "present": True,
                "status": "pass",
                "required_for_selected_packet": False,
                "browser_action_receipt_present": False,
            },
            "live_browse_evidence": {"present": True, "status": "pass"},
            "chosen_candidate": {"present": True, "status": "pass"},
            "staged_reversible_artifact": {"present": True, "status": "pass"},
            "teable_projection": {"present": True, "status": "pass"},
            "approval_outcome": {
                "present": False,
                "accepted": False,
                "approval_outcome_recorded": False,
                "status": "missing_or_invalid",
                "outcome": "missing",
                "source_kind": "unknown",
                "recorded_at": "",
                "evidence_sha256": "",
                "actor_sha256": "",
                "packet_ref_sha256": "",
                "staged_artifact_sha256": "",
                "raw_evidence_exposed": False,
                "raw_actor_exposed": False,
                "raw_packet_ref_exposed": False,
                "raw_staged_artifact_exposed": False,
            },
        },
        "remaining_external_proofs": ["redacted explicit approval outcome for the proactive OODA packet"],
        "verifier_commands": [
            "make verify-proactive-ooda",
            "make verify-proactive-ooda-live-receipt",
            "make verify-proactive-ooda-operator-status",
            "make verify-proactive-ooda-gold-acceptance",
        ],
        "rules": [
            "This receipt proves proactive OODA gold only when routed delivery, assistant-grade source intent, live browse evidence, a chosen candidate, a staged reversible artifact, mirrored Teable projection, and a redacted approval outcome are all present.",
            "Irreversible purchases, bookings, cancellations, sent messages, posts, and commitments remain consent-gated even when proactive staging is automated.",
            "Website browser work must produce a redacted browser-action receipt; CAPTCHA, Cloudflare, MFA, passkey, or credential blockers require a human handoff and must not be counted as completed work.",
            "Raw packet text, private links, actor identity, packet refs, and staged artifact refs must stay out of this published receipt; only hashes and coarse status may appear.",
            "Teable remains an admin projection and audit mirror rather than canonical queue or product truth.",
        ],
        "source_git_head": "source-head-123",
        "source_state_fingerprint": "source-fingerprint-123",
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "evidence_receipts": {},
    }


@pytest.fixture(autouse=True)
def _stable_source_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verifier, "_source_fingerprint", lambda path=verifier.ROOT: "source-fingerprint-123")


def test_proactive_ooda_gold_acceptance_verifier_accepts_valid_receipt(tmp_path: Path, monkeypatch) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    operator_status = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    _write_receipt(
        operator_status,
        contract_name="ea.proactive_ooda_operator_status.v1",
        generated_by="scripts/materialize_proactive_ooda_operator_status.py",
        head_semantics="source_state",
        status="ready_with_live_receipt",
        generated_at="2026-06-26T19:00:00Z",
        source_git_head="source-head-123",
        source_state_fingerprint="source-fingerprint-123",
    )
    payload = _base_payload()
    payload["evidence_receipts"] = {
        "operator_status": {
            "present": True,
            "path": ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "generated_at": "2026-06-26T19:00:00Z",
            "source_git_head": "source-head-123",
            "source_state_fingerprint": "source-fingerprint-123",
        }
    }
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_gold_acceptance_verifier_accepts_post_commit_head_change_when_source_fingerprint_matches(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    payload = _base_payload()
    payload["source_git_head"] = "pre-commit-source-head"
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "post-commit-source-head")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_gold_acceptance_verifier_rejects_source_fingerprint_drift(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    payload = _base_payload()
    payload["source_git_head"] = "pre-commit-source-head"
    payload["source_state_fingerprint"] = "old-source-fingerprint"
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "post-commit-source-head")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "receipt is stale relative to current source HEAD" in issues
    assert "receipt is stale relative to current source fingerprint" in issues


def test_proactive_ooda_gold_acceptance_verifier_rejects_pass_without_accepted_outcome(
    tmp_path: Path,
    monkeypatch,
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    payload = _base_payload()
    payload["status"] = "pass"
    payload["gold_claim_allowed"] = True
    payload["remaining_external_proofs"] = []
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "pass requires approval_outcome.accepted=true" in issues


def test_proactive_ooda_gold_acceptance_verifier_allows_ready_state_before_action_required_proof(
    tmp_path: Path,
    monkeypatch,
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    payload = _base_payload()
    payload["proofs"]["action_required_only_delivery"] = {"present": False, "status": "blocked"}
    payload["remaining_external_proofs"] = [
        "action-required-only Telegram delivery proof for the proactive OODA packet",
        "redacted explicit approval outcome for the proactive OODA packet",
    ]
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_gold_acceptance_verifier_rejects_linked_operator_status_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    operator_status = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    _write_receipt(
        operator_status,
        contract_name="ea.proactive_ooda_operator_status.v1",
        generated_by="scripts/materialize_proactive_ooda_operator_status.py",
        head_semantics="source_state",
        status="blocked_delivery_route",
        generated_at="2026-06-26T19:05:00Z",
        source_git_head="source-head-123",
    )
    payload = _base_payload()
    payload["evidence_receipts"] = {
        "operator_status": {
            "present": True,
            "path": ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
            "contract_name": "ea.proactive_ooda_operator_status.v1",
            "status": "ready_with_live_receipt",
            "generated_at": "2026-06-26T19:00:00Z",
            "source_git_head": "source-head-123",
        }
    }
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "linked operator_status status drifted" in issues
    assert "linked operator_status generated_at drifted" in issues


def test_proactive_ooda_gold_acceptance_verifier_rejects_ready_approval_surface_without_live_pending_callback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    payload = _base_payload()
    payload["evidence_receipts"] = {
        "approval_capture_surface": {
            "ready": True,
            "selected_channel": "telegram",
            "callback_dir_writable": True,
            "approval_outcome_path": "state/proactive_ooda_latest_approval_outcome.generated.json",
            "callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "current_packet_live_pending_count": 0,
        }
    }
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "ready approval_capture_surface requires current_packet_live_pending_count>0" in issues


def test_proactive_ooda_gold_acceptance_verifier_accepts_blocked_operator_runtime_posture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    payload = _base_payload()
    payload["status"] = "blocked_operator_runtime_posture"
    payload["summary"] = "The proactive OODA packet proofs exist, but operator runtime posture is blocked and gold cannot be claimed until approved source health is restored."
    payload["next_action"] = "reauthorize_google_workspace_binding"
    payload["proofs"]["operator_runtime_posture"] = {
        "present": False,
        "status": "blocked",
        "reason": "google_workspace_signal_source_unhealthy:google_oauth_invalid_grant",
        "next_action": "reauthorize_google_workspace_binding",
        "next_action_href": (
            "https://myexternalbrain.com/app/actions/google/connect?"
            "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
        ),
        "next_action_label": "Reconnect Google workspace",
        "next_action_method": "get",
    }
    payload["next_action_href"] = (
        "https://myexternalbrain.com/app/actions/google/connect?"
        "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
    )
    payload["next_action_label"] = "Reconnect Google workspace"
    payload["next_action_method"] = "get"
    payload["evidence_receipts"] = {}
    payload["remaining_external_proofs"] = [
        "healthy operator runtime posture across approved proactive sources",
        "redacted explicit approval outcome for the proactive OODA packet",
    ]
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_gold_acceptance_verifier_accepts_low_quality_packet_blocker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    payload = _base_payload()
    payload["status"] = "blocked_low_quality_packet_evidence"
    payload["summary"] = "The proactive OODA mechanics have evidence, but the selected packet is not assistant-grade enough to prove production readiness."
    payload["next_action"] = "stage_fresh_assistant_grade_proactive_packet"
    payload["proofs"]["assistant_grade_packet_quality"] = {
        "present": False,
        "status": "blocked",
        "issues": ["transcript_signal_lacks_action_intent"],
    }
    payload["evidence_receipts"] = {}
    payload["remaining_external_proofs"] = [
        "assistant-grade source intent and candidate alignment for the proactive OODA packet",
        "redacted explicit approval outcome for the proactive OODA packet",
    ]
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_gold_acceptance_verifier_requires_reauth_surface_for_google_runtime_blocker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
    payload = _base_payload()
    payload["status"] = "blocked_operator_runtime_posture"
    payload["summary"] = "The proactive OODA packet proofs exist, but operator runtime posture is blocked and gold cannot be claimed until approved source health is restored."
    payload["next_action"] = "reauthorize_google_workspace_binding"
    payload["proofs"]["operator_runtime_posture"] = {
        "present": False,
        "status": "blocked",
        "reason": "google_workspace_signal_source_unhealthy:google_oauth_invalid_grant",
        "next_action": "reauthorize_google_workspace_binding",
        "next_action_href": "",
        "next_action_label": "",
        "next_action_method": "",
    }
    payload["evidence_receipts"] = {}
    payload["remaining_external_proofs"] = [
        "healthy operator runtime posture across approved proactive sources",
        "redacted explicit approval outcome for the proactive OODA packet",
    ]
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "reauthorize_google_workspace_binding requires next_action_href" in issues
    assert "reauthorize_google_workspace_binding requires next_action_label" in issues
    assert "reauthorize_google_workspace_binding requires next_action_method=get" in issues
    assert "operator_runtime_posture reauthorize_google_workspace_binding requires next_action_href" in issues
