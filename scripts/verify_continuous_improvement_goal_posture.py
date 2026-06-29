#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
REQUIRED_LENSES = ["detect", "decide", "deliver", "recover", "prove"]
KNOWN_STATUSES = {
    "pass",
    "ready_local_evidence",
    "ready_local_audit",
    "ready_local_direction",
    "ready_local_packet_pending_operator_acceptance",
    "ready_for_live_epub_delivery_test",
    "audiobookshelf_imported",
    "mixed_local_progress",
    "ready_local_audit",
    "blocked_real_world_acceptance",
    "blocked_realtime_prerequisites",
    "blocked",
    "active_with_blockers",
    "command_backed_no_published_receipt",
    "missing_receipt",
    "waiting",
    "waiting_for_live_epub",
    "fail",
}
EXPECTED_COMPONENTS = {
    "deliver": {"promo_media", "manfred_speech", "telegram_audiobook", "whatsapp_audiobook"},
}
REQUIRED_PROACTIVE_OODA_RECEIPT = (
    "real proactive OODA packet accepted with action-required-only routed delivery, approved-source or transcript signal, "
    "live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, "
    "current-packet, stale-approval, and decision facts, and explicit approval outcome"
)
REQUIRED_PROOF_FIELDS = {
    "key",
    "title",
    "lens",
    "status",
    "required_next_receipt",
    "evidence_kind",
    "capture_surfaces",
    "next_action",
    "claim_boundary",
    "source_receipts",
}
KNOWN_PROOF_STATUSES = {"pending_real_world_evidence"}


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _git_head(path: Path = ROOT) -> str:
    return resolve_source_state_head(path)


def _fresh_enough(recorded_head: str, *, current_head: str) -> bool:
    recorded = str(recorded_head or "").strip()
    return bool(recorded and current_head and recorded == current_head)


def _infer_root(path: Path) -> Path:
    resolved = path.resolve()
    for marker in (".codex-studio", ".codex-design"):
        if marker in resolved.parts:
            marker_index = resolved.parts.index(marker)
            return Path(*resolved.parts[:marker_index])
    return ROOT


def verify(path: Path = DEFAULT_RECEIPT, *, root: Path | None = None) -> list[str]:
    issues: list[str] = []
    receipt = _json(path)
    if not receipt:
        return [f"continuous-improvement goal posture missing or invalid: {path}"]
    repo_root = root or _infer_root(path)

    if receipt.get("contract_name") != "ea.continuous_improvement_goal_posture.v1":
        issues.append("contract_name must be ea.continuous_improvement_goal_posture.v1")
    if receipt.get("goal_doc") != ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md":
        issues.append("goal_doc must point at the continuous-improvement goal doc")
    if receipt.get("goal_completion_claim_allowed") is not False:
        issues.append("goal_completion_claim_allowed must remain false")
    if "governed by owning truth planes" not in str(receipt.get("goal_shorthand") or ""):
        issues.append("goal_shorthand drifted away from the governed north-star wording")
    if "proactive ooda" not in str(receipt.get("goal_shorthand") or "").lower():
        issues.append("goal_shorthand must keep the proactive OODA posture explicit")

    current_head = _git_head(repo_root)
    if current_head and not _fresh_enough(str(receipt.get("source_git_head") or ""), current_head=current_head):
        issues.append("goal posture receipt is stale relative to current HEAD")

    execution_lenses = list(receipt.get("execution_lenses") or [])
    if execution_lenses != REQUIRED_LENSES:
        issues.append("execution_lenses must stay ordered as detect/decide/deliver/recover/prove")

    lenses = receipt.get("lenses")
    if not isinstance(lenses, list):
        return issues + ["lenses must be a list"]
    by_key = {str(lens.get("key") or ""): lens for lens in lenses if isinstance(lens, dict)}
    if sorted(by_key) != sorted(REQUIRED_LENSES):
        issues.append("receipt must contain exactly the required lenses")

    for key in REQUIRED_LENSES:
        lens = by_key.get(key) or {}
        status = str(lens.get("status") or "").strip()
        if not status:
            issues.append(f"{key} lens status missing")
        elif status not in KNOWN_STATUSES:
            issues.append(f"{key} lens status uses unknown value: {status}")
        commands = list(lens.get("verifier_commands") or [])
        if not commands:
            issues.append(f"{key} lens must list verifier commands")
        if key in {"detect", "decide", "prove"}:
            sources = list(lens.get("source_receipts") or [])
            if len(sources) != 1:
                issues.append(f"{key} lens must have exactly one primary source receipt")
            for source in sources:
                path_text = str(source.get("path") or "").strip()
                if not path_text:
                    issues.append(f"{key} source receipt path missing")
                    continue
                source_path = repo_root / path_text
                if bool(source.get("present")) != source_path.exists():
                    issues.append(f"{key} source receipt presence drifted for {path_text}")
                if source_path.exists():
                    payload = _json(source_path)
                    source_status = str(source.get("status") or "").strip().lower()
                    payload_status = str(payload.get("status") or "missing_receipt").strip().lower()
                    if source_status != payload_status:
                        issues.append(f"{key} source receipt status drifted for {path_text}")
                    if status != source_status:
                        issues.append(f"{key} lens status must mirror {path_text}")
        if key == "deliver":
            components = list(lens.get("components") or [])
            component_keys = {str(component.get("key") or "") for component in components if isinstance(component, dict)}
            if component_keys != EXPECTED_COMPONENTS["deliver"]:
                issues.append("deliver lens components drifted")
            for component in components:
                if not isinstance(component, dict):
                    issues.append("deliver lens components must be objects")
                    continue
                component_key = str(component.get("key") or "").strip() or "unknown"
                component_status = str(component.get("status") or "").strip()
                if not component_status:
                    issues.append(f"deliver component status missing for {component_key}")
                elif component_status not in KNOWN_STATUSES:
                    issues.append(f"deliver component status uses unknown value for {component_key}: {component_status}")
            if status not in {"mixed_local_progress", "ready_local_evidence", "pass"}:
                issues.append("deliver lens must stay conservative (mixed_local_progress, ready_local_evidence, or pass)")
        if key == "recover":
            sources = list(lens.get("source_receipts") or [])
            if not sources:
                if status != "command_backed_no_published_receipt":
                    issues.append("recover lens without a source receipt must stay command-backed")
            else:
                if len(sources) != 1:
                    issues.append("recover lens must have exactly one mirrored recovery readiness receipt")
                source = dict(sources[0]) if sources else {}
                path_text = str(source.get("path") or "").strip()
                if not path_text:
                    issues.append("recover source receipt path missing")
                else:
                    source_path = repo_root / path_text
                    if bool(source.get("present")) != source_path.exists():
                        issues.append(f"recover source receipt presence drifted for {path_text}")
                    if source_path.exists():
                        payload = _json(source_path)
                        source_status = str(source.get("status") or "").strip().lower()
                        payload_status = str(payload.get("status") or "missing_receipt").strip().lower()
                        if source_status != payload_status:
                            issues.append(f"recover source receipt status drifted for {path_text}")
                        if status != source_status:
                            issues.append(f"recover lens status must mirror {path_text}")
                if status not in {"ready_local_audit", "blocked", "pass"}:
                    issues.append("recover lens with a mirrored receipt must stay conservative")

    blocking_reasons = [str(item) for item in list(receipt.get("blocking_reasons") or []) if str(item).strip()]
    if by_key.get("prove", {}).get("status") == "blocked_real_world_acceptance" and receipt.get("overall_status") != "blocked_real_world_acceptance":
        issues.append("overall_status must stay blocked_real_world_acceptance while the prove lens is blocked_real_world_acceptance")
    if "The recover lens may use a mirrored local readiness receipt, but it must not claim pass until a fresh-host Teable recovery drill receipt is mirrored." not in "\n".join(
        str(item) for item in list(receipt.get("rules") or [])
    ):
        issues.append("missing recover rule about mirrored Teable recovery receipts")
    if "Irreversible purchases, bookings, cancellations, outbound commitments, and sent messages must stay consent-gated even when proactive OODA staging is automated." not in "\n".join(
        str(item) for item in list(receipt.get("rules") or [])
    ):
        issues.append("missing proactive OODA consent-gate rule")
    if "Telegram is an action surface, not a progress log; proactive delivery must stay quiet unless the user needs to approve, choose, unblock, review, or answer something." not in "\n".join(
        str(item) for item in list(receipt.get("rules") or [])
    ):
        issues.append("missing action-required-only Telegram rule")
    if "Proactive OODA packets must pass a context/provider-fit auditor before user delivery; reachable URLs, extracted email addresses, or generic search hits are not sufficient." not in "\n".join(
        str(item) for item in list(receipt.get("rules") or [])
    ):
        issues.append("missing proactive OODA auditor-before-delivery rule")
    if "Pocket.ai or other consented audio transcripts may feed OODA only as approved signals with privacy, retention, source, and current/stale status preserved." not in "\n".join(
        str(item) for item in list(receipt.get("rules") or [])
    ):
        issues.append("missing transcript-ingest rule")
    if "Teable may mirror important proactive OODA facts and blockers, but it remains an admin projection rather than canonical truth." not in "\n".join(
        str(item) for item in list(receipt.get("rules") or [])
    ):
        issues.append("missing Teable projection rule for proactive OODA")
    required_next_receipts = set(str(item) for item in list(receipt.get("required_next_receipts") or []) if str(item).strip())
    if REQUIRED_PROACTIVE_OODA_RECEIPT not in required_next_receipts:
        issues.append("required_next_receipts must include proactive OODA Teable proof")
    acceptance_proof_requirements = receipt.get("acceptance_proof_requirements")
    if not isinstance(acceptance_proof_requirements, list) or not acceptance_proof_requirements:
        issues.append("acceptance_proof_requirements must be a non-empty list")
        acceptance_proof_requirements = []
    proof_receipts: set[str] = set()
    proof_keys: set[str] = set()
    proof_by_key: dict[str, dict[str, Any]] = {}
    for index, requirement in enumerate(acceptance_proof_requirements):
        if not isinstance(requirement, dict):
            issues.append(f"acceptance_proof_requirements[{index}] must be an object")
            continue
        missing_fields = sorted(field for field in REQUIRED_PROOF_FIELDS if field not in requirement)
        if missing_fields:
            issues.append(f"acceptance proof requirement missing fields at index {index}: {', '.join(missing_fields)}")
        key = str(requirement.get("key") or "").strip()
        if not key:
            issues.append(f"acceptance proof requirement key missing at index {index}")
        elif key in proof_keys:
            issues.append(f"duplicate acceptance proof requirement key: {key}")
        else:
            proof_keys.add(key)
            proof_by_key[key] = requirement
        lens = str(requirement.get("lens") or "").strip()
        if lens not in REQUIRED_LENSES:
            issues.append(f"acceptance proof requirement {key or index} uses unknown lens: {lens}")
        status = str(requirement.get("status") or "").strip()
        if status not in KNOWN_PROOF_STATUSES:
            issues.append(f"acceptance proof requirement {key or index} uses unknown status: {status}")
        required_receipt = str(requirement.get("required_next_receipt") or "").strip()
        if required_receipt:
            proof_receipts.add(required_receipt)
        else:
            issues.append(f"acceptance proof requirement {key or index} missing required_next_receipt")
        capture_surfaces = [
            str(surface or "").strip()
            for surface in list(requirement.get("capture_surfaces") or [])
            if str(surface or "").strip()
        ]
        if not capture_surfaces:
            issues.append(f"acceptance proof requirement {key or index} must list capture_surfaces")
        if "does_not_prove" not in str(requirement.get("claim_boundary") or ""):
            issues.append(f"acceptance proof requirement {key or index} must keep an explicit does_not_prove claim boundary")
        if not str(requirement.get("evidence_kind") or "").strip():
            issues.append(f"acceptance proof requirement {key or index} missing evidence_kind")
        if not str(requirement.get("next_action") or "").strip():
            issues.append(f"acceptance proof requirement {key or index} missing next_action")
        sources = list(requirement.get("source_receipts") or [])
        if not sources:
            issues.append(f"acceptance proof requirement {key or index} must include source_receipts")
        for source in sources:
            if not isinstance(source, dict):
                issues.append(f"acceptance proof requirement {key or index} source_receipts must be objects")
                continue
            path_text = str(source.get("path") or "").strip()
            if not path_text:
                issues.append(f"acceptance proof requirement {key or index} source receipt path missing")
                continue
            source_path = repo_root / path_text
            if bool(source.get("present")) != source_path.exists():
                issues.append(f"acceptance proof requirement {key or index} source receipt presence drifted for {path_text}")
    if proof_receipts != required_next_receipts:
        issues.append("acceptance_proof_requirements must cover every required_next_receipts item exactly")
    proactive_requirement = proof_by_key.get("proactive_ooda_packet_acceptance") or {}
    if not proactive_requirement:
        issues.append("acceptance_proof_requirements must include proactive_ooda_packet_acceptance")
    else:
        if proactive_requirement.get("required_next_receipt") != REQUIRED_PROACTIVE_OODA_RECEIPT:
            issues.append("proactive_ooda_packet_acceptance must cover the proactive OODA proof receipt")
        if proactive_requirement.get("evidence_kind") != "approval_outcome":
            issues.append("proactive_ooda_packet_acceptance evidence_kind must be approval_outcome")
        next_action = str(proactive_requirement.get("next_action") or "")
        if "record_proactive_ooda_approval_outcome" not in next_action and "tap_proactive_telegram_approval_button" not in next_action:
            issues.append("proactive_ooda_packet_acceptance must point at the Telegram approval outcome capture")
        capture_surfaces = " ".join(str(surface or "") for surface in list(proactive_requirement.get("capture_surfaces") or []))
        if "ea_proactive_ooda_gold_acceptance.generated.json" not in capture_surfaces:
            issues.append("proactive_ooda_packet_acceptance must cite the gold acceptance receipt capture surface")
    recovery_requirement = proof_by_key.get("fresh_host_teable_recovery_drill") or {}
    if not recovery_requirement:
        issues.append("acceptance_proof_requirements must include fresh_host_teable_recovery_drill")
    else:
        capture_surfaces = " ".join(str(surface or "") for surface in list(recovery_requirement.get("capture_surfaces") or []))
        if "teable_env_recovery_readiness.generated.json" not in capture_surfaces:
            issues.append("fresh_host_teable_recovery_drill must cite the Teable recovery readiness surface")
    if by_key.get("recover", {}).get("status") == "command_backed_no_published_receipt" and "recover=command_backed_no_published_receipt" not in blocking_reasons:
        issues.append("blocking_reasons must include the command-backed recover posture")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the continuous-improvement goal posture receipt.")
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
