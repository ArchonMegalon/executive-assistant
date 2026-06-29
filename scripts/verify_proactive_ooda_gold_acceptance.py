#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts.source_state_head import resolve_source_state_head
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
EXPECTED_RULES = {
    "This receipt proves proactive OODA gold only when routed delivery, live browse evidence, a chosen candidate, a staged reversible artifact, mirrored Teable projection, and a redacted approval outcome are all present.",
    "Irreversible purchases, bookings, cancellations, sent messages, posts, and commitments remain consent-gated even when proactive staging is automated.",
    "Raw packet text, private links, actor identity, packet refs, and staged artifact refs must stay out of this published receipt; only hashes and coarse status may appear.",
    "Teable remains an admin projection and audit mirror rather than canonical queue or product truth.",
}
KNOWN_STATUSES = {
    "blocked_operator_runtime_posture",
    "blocked_missing_proactive_packet_evidence",
    "blocked_not_accepted_under_ordinary_use",
    "ready_for_approval_outcome_capture",
    "pass",
}
EXPECTED_PROOF_KEYS = {
    "operator_runtime_posture",
    "routed_delivery",
    "action_required_only_delivery",
    "live_browse_evidence",
    "chosen_candidate",
    "staged_reversible_artifact",
    "teable_projection",
    "approval_outcome",
}


def _verify_next_action_surface(payload: Mapping[str, Any], issues: list[str], *, prefix: str = "") -> None:
    next_action = str(payload.get("next_action") or "").strip()
    if next_action != "reauthorize_google_workspace_binding":
        return
    href = str(payload.get("next_action_href") or "").strip()
    label = str(payload.get("next_action_label") or "").strip()
    method = str(payload.get("next_action_method") or "").strip().lower()
    context = f"{prefix} " if prefix else ""
    if not href:
        issues.append(f"{context}reauthorize_google_workspace_binding requires next_action_href")
    elif "/app/actions/google/connect?" not in href:
        issues.append(f"{context}reauthorize_google_workspace_binding next_action_href must target the Google connect action")
    if not label:
        issues.append(f"{context}reauthorize_google_workspace_binding requires next_action_label")
    if method != "get":
        issues.append(f"{context}reauthorize_google_workspace_binding requires next_action_method=get")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _git_head(path: Path = ROOT) -> str:
    return resolve_source_state_head(path)


def _path_from_text(root: Path, value: object) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else root / path


def verify(path: Path = DEFAULT_RECEIPT, *, root: Path = ROOT) -> list[str]:
    issues: list[str] = []
    receipt = _load_json(path)
    if not receipt:
        return [f"proactive OODA gold acceptance missing or invalid: {path}"]

    if receipt.get("contract_name") != "ea.proactive_ooda_gold_acceptance.v1":
        issues.append("contract_name must be ea.proactive_ooda_gold_acceptance.v1")
    if receipt.get("generated_by") != "scripts/materialize_proactive_ooda_gold_acceptance.py":
        issues.append("generated_by must point at the proactive OODA gold-acceptance materializer")
    if receipt.get("head_semantics") != "source_state":
        issues.append("head_semantics must remain source_state")

    current_head = _git_head(root)
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    if not recorded_head:
        issues.append("source_git_head missing")
    elif current_head and current_head != recorded_head:
        issues.append("receipt is stale relative to current source HEAD")

    status = str(receipt.get("status") or "").strip()
    if status not in KNOWN_STATUSES:
        issues.append(f"status must stay within known proactive OODA gold states: {status or 'missing'}")
    if receipt.get("goal_completion_claim_allowed") is not False:
        issues.append("goal_completion_claim_allowed must remain false")
    if bool(receipt.get("gold_claim_allowed")) != (status == "pass"):
        issues.append("gold_claim_allowed must only be true when status=pass")
    if not str(receipt.get("summary") or "").strip():
        issues.append("summary must be present")
    if not str(receipt.get("next_action") or "").strip():
        issues.append("next_action must be present")
    _verify_next_action_surface(receipt, issues)

    proofs = receipt.get("proofs")
    if not isinstance(proofs, dict):
        issues.append("proofs must be a mapping")
        return issues
    if set(proofs) != EXPECTED_PROOF_KEYS:
        issues.append("proof keys drifted")
        return issues

    required_runtime_proofs = [
        str(proofs[key].get("present")).lower() == "true"
        for key in (
            "operator_runtime_posture",
            "routed_delivery",
            "action_required_only_delivery",
            "live_browse_evidence",
            "chosen_candidate",
            "staged_reversible_artifact",
            "teable_projection",
        )
        if isinstance(proofs.get(key), dict)
    ]
    approval = dict(proofs.get("approval_outcome") or {})
    if approval.get("raw_evidence_exposed") is not False:
        issues.append("approval_outcome.raw_evidence_exposed must remain false")
    if approval.get("raw_actor_exposed") is not False:
        issues.append("approval_outcome.raw_actor_exposed must remain false")
    if approval.get("raw_packet_ref_exposed") is not False:
        issues.append("approval_outcome.raw_packet_ref_exposed must remain false")
    if approval.get("raw_staged_artifact_exposed") is not False:
        issues.append("approval_outcome.raw_staged_artifact_exposed must remain false")

    approval_recorded = bool(approval.get("approval_outcome_recorded"))
    approval_accepted = bool(approval.get("accepted"))
    if approval_recorded:
        for key in ("evidence_sha256", "actor_sha256", "packet_ref_sha256", "staged_artifact_sha256"):
            if not str(approval.get(key) or "").strip():
                issues.append(f"approval_outcome missing hash field: {key}")

    rules = set(str(item).strip() for item in list(receipt.get("rules") or []) if str(item).strip())
    if rules != EXPECTED_RULES:
        issues.append("rules drifted")

    commands = [str(item).strip() for item in list(receipt.get("verifier_commands") or []) if str(item).strip()]
    for expected in (
        "make verify-proactive-ooda",
        "make verify-proactive-ooda-live-receipt",
        "make verify-proactive-ooda-operator-status",
        "make verify-proactive-ooda-gold-acceptance",
    ):
        if expected not in commands:
            issues.append(f"verifier_commands missing: {expected}")

    if status == "pass":
        if not all(required_runtime_proofs):
            issues.append("pass requires all runtime proofs present")
        if not approval_accepted:
            issues.append("pass requires approval_outcome.accepted=true")
        if list(receipt.get("remaining_external_proofs") or []):
            issues.append("pass must not retain remaining_external_proofs")
    if status == "ready_for_approval_outcome_capture" and not all(required_runtime_proofs):
        issues.append("ready_for_approval_outcome_capture requires the runtime proofs to be present")
    if status == "ready_for_approval_outcome_capture" and approval_recorded:
        issues.append("ready_for_approval_outcome_capture must not already have a recorded approval outcome")
    if status == "blocked_not_accepted_under_ordinary_use":
        if not all(required_runtime_proofs):
            issues.append("blocked_not_accepted_under_ordinary_use requires the runtime proofs to be present")
        if not approval_recorded or approval_accepted:
            issues.append("blocked_not_accepted_under_ordinary_use requires a recorded non-accepted approval outcome")
    if status == "blocked_operator_runtime_posture":
        operator_runtime = dict(proofs.get("operator_runtime_posture") or {})
        if bool(operator_runtime.get("present")):
            issues.append("blocked_operator_runtime_posture requires operator_runtime_posture.present=false")
        _verify_next_action_surface(operator_runtime, issues, prefix="operator_runtime_posture")

    evidence_receipts = receipt.get("evidence_receipts")
    if not isinstance(evidence_receipts, dict):
        issues.append("evidence_receipts must be a mapping")
        return issues
    approval_capture_surface = dict(evidence_receipts.get("approval_capture_surface") or {})
    if approval_capture_surface and bool(approval_capture_surface.get("ready")):
        if str(approval_capture_surface.get("selected_channel") or "").strip() != "telegram":
            issues.append("ready approval_capture_surface requires selected_channel=telegram")
        if not bool(approval_capture_surface.get("callback_dir_writable")):
            issues.append("ready approval_capture_surface requires callback_dir_writable=true")
        if not str(approval_capture_surface.get("approval_outcome_path") or "").strip():
            issues.append("ready approval_capture_surface requires approval_outcome_path")
        if not str(approval_capture_surface.get("callback_dir") or "").strip():
            issues.append("ready approval_capture_surface requires callback_dir")
        if int(approval_capture_surface.get("current_packet_live_pending_count") or 0) <= 0:
            issues.append("ready approval_capture_surface requires current_packet_live_pending_count>0")
    operator_status_evidence = dict(evidence_receipts.get("operator_status") or {})
    if bool(operator_status_evidence.get("present")):
        operator_status_path = _path_from_text(root, operator_status_evidence.get("path"))
        if operator_status_path is None or not operator_status_path.is_file():
            issues.append("linked operator_status receipt missing on disk")
        else:
            linked_operator_status = _load_json(operator_status_path)
            if not linked_operator_status:
                issues.append("linked operator_status receipt invalid")
            else:
                for key in ("contract_name", "status", "generated_at", "source_git_head"):
                    expected = str(operator_status_evidence.get(key) or "").strip()
                    actual = str(linked_operator_status.get(key) or "").strip()
                    if expected != actual:
                        issues.append(f"linked operator_status {key} drifted")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the proactive OODA gold-acceptance receipt.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    issues = verify(args.receipt)
    payload = {"status": "pass" if not issues else "blocked", "issues": issues}
    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
