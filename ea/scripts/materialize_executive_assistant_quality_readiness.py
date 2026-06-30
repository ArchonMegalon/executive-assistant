from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from materialize_executive_assistant_acceptance_evidence import ACCEPTANCE_CAPTURE_LABEL
from materialize_executive_assistant_acceptance_evidence import ACCEPTANCE_CAPTURE_METHOD
from materialize_executive_assistant_acceptance_evidence import ACCEPTANCE_CAPTURE_PATH
from materialize_executive_assistant_acceptance_evidence import acceptance_capture_requirements
from materialize_executive_assistant_acceptance_evidence import _acceptance_capture_surface
from materialize_executive_assistant_acceptance_evidence import _empty_row
from materialize_executive_assistant_acceptance_evidence import _normalized_existing_row
from materialize_executive_assistant_acceptance_evidence import REMAINING_PROOF_LABELS, REQUIRED_ACCEPTANCE_KEYS


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_executive_assistant_quality_readiness.generated.json"
DEFAULT_OFFICE_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_office_loop_goal.generated.json"
DEFAULT_ACCEPTANCE_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_executive_assistant_acceptance_evidence.generated.json"

LOCAL_CHECKS = {
    "command_brief_local_ready": "command_brief",
    "decision_queue_local_ready": "decision_queue",
    "commitment_ledger_local_ready": "commitment_ledger",
    "approved_action_review_local_ready": "approved_action_workflow",
    "evidence_audit_trail_local_ready": "evidence_audit_trail",
    "support_recovery_local_ready": "support_recovery",
    "operator_control_local_ready": "operator_control",
    "goal_evidence_local_ready": "goal_evidence",
}

REQUIRED_REAL_WORLD_PROOF = list(REMAINING_PROOF_LABELS.values())
LOCAL_REVIEW_PATH = "/app/today"
LOCAL_REVIEW_LABEL = "Open Today"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _receipt_info(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        return {"exists": False, "path": str(path), "bytes": 0, "sha256": ""}
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    try:
        rel = target.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        rel = str(target)
    return {"exists": True, "path": rel, "bytes": target.stat().st_size, "sha256": digest}


def _local_blockers(office_loop: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    components = dict(office_loop.get("components") or {})
    for check_key, component_key in LOCAL_CHECKS.items():
        if dict(components.get(component_key) or {}).get("status") != "pass":
            blockers.append(check_key)
    digests = set(dict(office_loop.get("diagnostics_summary") or {}).get("channel_loop_digest_keys") or [])
    if not {"memo", "approvals", "operator"} <= digests:
        blockers.append("api_digest_local_ready")
    return blockers


def _acceptance(acceptance_evidence: dict[str, Any] | None, path: str | Path | None) -> dict[str, Any]:
    if acceptance_evidence is not None:
        return acceptance_evidence
    if path and Path(path).is_file():
        return _load(path)
    if DEFAULT_ACCEPTANCE_RECEIPT.is_file():
        return _load(DEFAULT_ACCEPTANCE_RECEIPT)
    return {"accepted_keys": [], "blocked_keys": REQUIRED_ACCEPTANCE_KEYS, "remaining_external_proofs": REQUIRED_REAL_WORLD_PROOF}


def _acceptance_rows(acceptance: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {key: _empty_row() for key in REQUIRED_ACCEPTANCE_KEYS}
    existing = acceptance.get("acceptance_keys")
    if isinstance(existing, dict):
        for key, row in existing.items():
            if key in rows and isinstance(row, dict):
                rows[key] = _normalized_existing_row(row)
    return rows


def materialize_executive_assistant_quality_readiness(
    *,
    receipt_path: str | Path,
    generated_at: str = "",
    office_loop: dict[str, Any] | None = None,
    office_loop_receipt_path: str | Path | None = None,
    acceptance_evidence: dict[str, Any] | None = None,
    acceptance_evidence_receipt_path: str | Path | None = None,
    refresh: bool = True,
) -> dict[str, Any]:
    del refresh
    if office_loop is None:
        office_loop = _load(office_loop_receipt_path or DEFAULT_OFFICE_RECEIPT)
    acceptance = _acceptance(acceptance_evidence, acceptance_evidence_receipt_path)
    local_blockers = _local_blockers(office_loop)
    accepted = set(acceptance.get("accepted_keys") or [])
    blocked_checks = [key for key in REQUIRED_ACCEPTANCE_KEYS if key not in accepted]
    acceptance_rows = _acceptance_rows(acceptance)
    local_ready = not local_blockers
    acceptance_ready = not blocked_checks or bool(office_loop.get("live_daily_use_verified") and office_loop.get("real_operator_acceptance_verified") and office_loop.get("external_provider_runtime_verified"))
    if not local_ready:
        status = "blocked_local_quality_evidence"
    elif acceptance_ready:
        status = "ready_for_good_executive_assistant_claim_review"
    else:
        status = "blocked_real_world_acceptance"
    good_claim = bool(local_ready and acceptance_ready)
    next_action = "review_good_executive_assistant_claim" if good_claim else (
        "collect_redacted_real_world_acceptance_evidence"
        if local_ready
        else "inspect_local_office_loop_quality_regression"
    )
    next_action_href = ""
    next_action_label = ""
    next_action_method = ""
    next_action_proof_key = ""
    if local_ready and not good_claim:
        next_action_href = ACCEPTANCE_CAPTURE_PATH
        next_action_label = ACCEPTANCE_CAPTURE_LABEL
        next_action_method = ACCEPTANCE_CAPTURE_METHOD.lower()
        next_action_proof_key = str(acceptance.get("next_action_proof_key") or (blocked_checks[0] if blocked_checks else "")).strip()
    elif not local_ready:
        next_action_href = LOCAL_REVIEW_PATH
        next_action_label = LOCAL_REVIEW_LABEL
        next_action_method = "get"
    receipt = {
        "contract_name": "ea.executive_assistant_quality_readiness.v1",
        "status": status,
        "generated_at": generated_at or _now(),
        "generated_by": "ea/scripts/materialize_executive_assistant_quality_readiness.py",
        "goal_completion_claim_allowed": False,
        "good_executive_assistant_claim_allowed": good_claim,
        "public_or_premium_claim_allowed": False,
        "local_quality_evidence_ready": local_ready,
        "ready_for_real_daily_use_review": local_ready,
        "local_blockers": local_blockers,
        "blocked_checks": [] if acceptance_ready else blocked_checks,
        "external_acceptance_blockers": [] if acceptance_ready else blocked_checks,
        "live_daily_use_verified": acceptance_ready,
        "real_principal_acceptance_verified": bool(acceptance.get("real_principal_acceptance_verified") or office_loop.get("live_daily_use_verified")),
        "real_operator_acceptance_verified": bool(acceptance.get("real_operator_acceptance_verified") or office_loop.get("real_operator_acceptance_verified")),
        "real_provider_recovery_verified": bool(acceptance.get("real_provider_recovery_verified") or office_loop.get("external_provider_runtime_verified")),
        "ea_is_product_truth": False,
        "ea_owns_canonical_queue_truth": False,
        "ea_owns_release_authority": False,
        "provider_telemetry_is_product_authority": False,
        "quality_dimensions": {
            "morning_brief": {"status": "ready" if local_ready else "blocked", "success_condition": "the user sees a morning brief worth reading"},
            "review_loop": {"status": "ready" if local_ready else "blocked", "success_condition": "at least one draft or decision is reviewable"},
            "commitment_visibility": {"status": "ready" if local_ready else "blocked", "success_condition": "at least one commitment or follow-up stays visible"},
            "review_boundary": {"status": "ready" if local_ready else "blocked", "success_condition": "nothing sends without review"},
            "recovery_and_traceability": {"status": "ready" if local_ready else "blocked", "success_condition": "provider and action failures produce an operator-grade recovery path"},
        },
        "acceptance_evidence": acceptance,
        "acceptance_evidence_receipt": _receipt_info(acceptance_evidence_receipt_path or DEFAULT_ACCEPTANCE_RECEIPT),
        "acceptance_capture_surface": _acceptance_capture_surface(),
        "acceptance_capture_requirements": acceptance_capture_requirements(acceptance_rows),
        "source_receipt": _receipt_info(office_loop_receipt_path or DEFAULT_OFFICE_RECEIPT),
        "required_real_world_proof": REQUIRED_REAL_WORLD_PROOF,
        "remaining_external_proofs": [] if acceptance_ready else [REMAINING_PROOF_LABELS[key] for key in blocked_checks],
        "privacy": {
            "credential_values_exposed": False,
            "env_values_exposed": False,
            "raw_acceptance_actor_exposed": False,
            "raw_acceptance_object_ref_exposed": False,
            "raw_acceptance_text_exposed": False,
            "raw_private_context_exposed": False,
            "seeded_fixture_raw_private_context_exposed": False,
        },
        "next_action": next_action,
        "next_action_href": next_action_href,
        "next_action_label": next_action_label,
        "next_action_method": next_action_method,
        "next_action_proof_key": next_action_proof_key,
    }
    _write(receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize EA quality readiness.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--office-loop-receipt")
    parser.add_argument("--acceptance-evidence-receipt")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--no-refresh", action="store_true")
    args = parser.parse_args(argv)
    receipt = materialize_executive_assistant_quality_readiness(
        receipt_path=args.receipt,
        office_loop_receipt_path=args.office_loop_receipt,
        acceptance_evidence_receipt_path=args.acceptance_evidence_receipt,
        generated_at=args.generated_at,
        refresh=not args.no_refresh,
    )
    print(json.dumps({"status": receipt["status"], "receipt": str(args.receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
