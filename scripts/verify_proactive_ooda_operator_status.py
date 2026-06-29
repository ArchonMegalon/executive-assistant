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
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
EXPECTED_RULES = {
    "This receipt proves proactive OODA route, guard, and packet-runtime posture only; it does not prove a human accepted the packet.",
    "Delivery recovery hints may be mirrored here and in Teable, but they remain operator aids rather than canonical queue truth.",
    "A live sent receipt can prove one routed delivery happened, but it does not by itself prove ordinary-use usefulness or approval correctness.",
    "Gold-production claims still require accepted proactive packets, routed delivery proof, approved-source or transcript signal evidence, live browse evidence, an auditor-passed chosen candidate, staged reversible artifacts, mirrored Teable current/stale delivery and decision facts, explicit approval outcome evidence, and consent-gated irreversible actions.",
}
EXPECTED_REMAINING_PROOF = (
    "real proactive OODA packet accepted with routed delivery, approved-source or transcript signal, live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, current-packet, stale-approval, and decision facts, and explicit approval outcome"
)
KNOWN_STATUSES = {
    "blocked_delivery_route",
    "blocked_local_runtime",
    "deferred",
    "ready_local_runtime",
    "ready_with_live_receipt",
    "ready_with_recovery_action",
}


def _is_google_workspace_recovery(receipt: dict[str, Any]) -> bool:
    reason = str(receipt.get("reason") or "").strip()
    if reason.startswith("google_workspace_signal_source_unhealthy:"):
        return True
    return False


def _verify_next_action_surface(receipt: dict[str, Any], issues: list[str]) -> None:
    next_action = str(receipt.get("next_action") or "").strip()
    if next_action != "reauthorize_google_workspace_binding":
        return
    href = str(receipt.get("next_action_href") or "").strip()
    label = str(receipt.get("next_action_label") or "").strip()
    method = str(receipt.get("next_action_method") or "").strip().lower()
    if not href:
        issues.append("reauthorize_google_workspace_binding requires next_action_href")
    elif "/app/actions/google/connect?" not in href:
        issues.append("reauthorize_google_workspace_binding next_action_href must target the Google connect action")
    if not label:
        issues.append("reauthorize_google_workspace_binding requires next_action_label")
    if method != "get":
        issues.append("reauthorize_google_workspace_binding requires next_action_method=get")


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _git_head(path: Path = ROOT) -> str:
    return resolve_source_state_head(path)


def verify(path: Path = DEFAULT_RECEIPT, *, root: Path = ROOT) -> list[str]:
    issues: list[str] = []
    receipt = _json(path)
    if not receipt:
        return [f"proactive OODA operator status missing or invalid: {path}"]

    if receipt.get("contract_name") != "ea.proactive_ooda_operator_status.v1":
        issues.append("contract_name must be ea.proactive_ooda_operator_status.v1")
    if receipt.get("generated_by") != "scripts/materialize_proactive_ooda_operator_status.py":
        issues.append("generated_by must point at the proactive OODA operator-status materializer")
    if receipt.get("head_semantics") != "source_state":
        issues.append("head_semantics must remain source_state")

    current_head = _git_head(root)
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    if not recorded_head:
        issues.append("source_git_head missing")
    elif current_head and recorded_head != current_head:
        issues.append("receipt is stale relative to current source HEAD")

    status = str(receipt.get("status") or "").strip()
    if status not in KNOWN_STATUSES:
        issues.append(f"status must stay within known proactive OODA operator states: {status or 'missing'}")
    if not str(receipt.get("next_action") or "").strip():
        issues.append("next_action must be present")
    _verify_next_action_surface(receipt, issues)
    if not str(receipt.get("summary") or "").strip():
        issues.append("summary must be present")
    if receipt.get("goal_completion_claim_allowed") is not False:
        issues.append("goal_completion_claim_allowed must remain false")
    if receipt.get("live_delivery_claim_allowed") is not False:
        issues.append("live_delivery_claim_allowed must remain false")
    route_probe_source = str(receipt.get("route_probe_source") or "").strip()
    if not route_probe_source:
        issues.append("route_probe_source must be present")
    if route_probe_source == "docker_compose_exec":
        if not str(receipt.get("route_probe_runtime_service") or "").strip():
            issues.append("docker_compose_exec route probes require route_probe_runtime_service")
        if not str(receipt.get("route_probe_observed_at") or "").strip():
            issues.append("docker_compose_exec route probes require route_probe_observed_at")

    rules = set(str(item).strip() for item in list(receipt.get("rules") or []) if str(item).strip())
    if rules != EXPECTED_RULES:
        issues.append("rules drifted")

    delivery_route = dict(receipt.get("delivery_route") or {})
    if "ready" not in delivery_route:
        issues.append("delivery_route.ready missing")
    if "route_error" not in delivery_route:
        issues.append("delivery_route.route_error missing")
    if "next_action" not in delivery_route:
        issues.append("delivery_route.next_action missing")

    delivery_guard = dict(receipt.get("delivery_guard") or {})
    if "delivery_state" not in delivery_guard:
        issues.append("delivery_guard.delivery_state missing")

    stage_packets = dict(receipt.get("stage_packets") or {})
    safe_work_results = dict(receipt.get("safe_work_results") or {})
    if "ready" not in stage_packets:
        issues.append("stage_packets.ready missing")
    if "ready" not in safe_work_results:
        issues.append("safe_work_results.ready missing")

    live_receipt_checked = bool(receipt.get("live_receipt_checked"))
    live_receipt = dict(receipt.get("live_receipt") or {})
    if live_receipt_checked:
        if "ok" not in live_receipt:
            issues.append("live_receipt.ok missing when live receipt is checked")
        if not str(live_receipt.get("receipt_path") or "").strip():
            issues.append("live_receipt.receipt_path missing when live receipt is checked")
    if status == "ready_with_live_receipt" and not bool(live_receipt.get("ok")):
        issues.append("ready_with_live_receipt status requires live_receipt.ok=true")
    if status == "ready_with_recovery_action" and not str(receipt.get("delivery_route_error") or "").strip() and not _is_google_workspace_recovery(
        receipt
    ):
        issues.append("ready_with_recovery_action requires delivery_route_error")
    if status == "blocked_delivery_route" and bool(receipt.get("delivery_route_ready")):
        issues.append("blocked_delivery_route must not claim delivery_route_ready=true")
    if status == "deferred" and str(delivery_guard.get("delivery_state") or "").strip() != "deferred":
        issues.append("deferred status requires delivery_guard.delivery_state=deferred")

    approval_capture_surface = dict(receipt.get("approval_capture_surface") or {})
    if approval_capture_surface:
        if bool(approval_capture_surface.get("ready")):
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
            if status == "ready_with_live_receipt":
                if str(receipt.get("next_action") or "").strip() != "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome":
                    issues.append("ready approval_capture_surface with ready_with_live_receipt requires approval-capture next_action")
                if str(receipt.get("operator_action_state") or "").strip() != "approval_capture_pending":
                    issues.append("ready approval_capture_surface with ready_with_live_receipt requires operator_action_state=approval_capture_pending")
                if str(delivery_guard.get("delivery_state") or "").strip() != "approval_capture_pending":
                    issues.append("ready approval_capture_surface with ready_with_live_receipt requires delivery_guard.delivery_state=approval_capture_pending")
                if delivery_guard.get("user_action_required") is not True:
                    issues.append("ready approval_capture_surface with ready_with_live_receipt requires delivery_guard.user_action_required=true")
                if int(receipt.get("actionable_count") or 0) < int(approval_capture_surface.get("current_packet_live_pending_count") or 0):
                    issues.append("ready approval_capture_surface with ready_with_live_receipt requires actionable_count to include pending approval surfaces")

    commands = [str(item).strip() for item in list(receipt.get("verifier_commands") or []) if str(item).strip()]
    for expected in (
        "make verify-proactive-ooda",
        "make verify-proactive-ooda-live-receipt",
        "make verify-proactive-ooda-operator-status",
    ):
        if expected not in commands:
            issues.append(f"verifier_commands missing: {expected}")

    remaining = [str(item).strip() for item in list(receipt.get("remaining_external_proofs") or []) if str(item).strip()]
    if EXPECTED_REMAINING_PROOF not in remaining:
        issues.append("remaining_external_proofs must keep the proactive OODA routed-delivery proof")
    return issues


def main() -> int:
    if any(flag in __import__("sys").argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python scripts/verify_proactive_ooda_operator_status.py [options]\n\n"
            "Verify the proactive OODA operator-status receipt."
        )
        return 0
    parser = argparse.ArgumentParser(description="Verify the proactive OODA operator-status receipt.")
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
