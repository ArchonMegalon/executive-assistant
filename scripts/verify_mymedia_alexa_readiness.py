#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts import ea_live_ops
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import ea_live_ops  # type: ignore
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint

DEFAULT_RECEIPT = ROOT / ".codex-studio/published/mymedia_alexa_readiness.generated.json"
CONTRACT_NAME = "ea.mymedia_alexa_readiness.v1"
KNOWN_STATUSES = {
    "ready",
    "blocked_runtime_unavailable",
    "blocked_console_unreachable",
    "blocked_pairing_required",
    "blocked_watch_folder_missing",
    "blocked_watch_folder_error",
    "blocked_external_access_not_ready",
    "blocked_connection_pending",
    "blocked_connection_not_ready",
    "ready_library_scan_in_progress",
    "blocked_library_scan_pending",
    "blocked_library_empty",
    "probe_failed",
}
KNOWN_TELEGRAM_DELIVERY_STATUSES = {
    "already_paired",
    "blocked_pairing_required",
    "blocked_runtime_unavailable",
    "blocked_console_unreachable",
    "blocked_watch_folder_missing",
    "blocked_watch_folder_error",
    "blocked_external_access_not_ready",
    "blocked_connection_pending",
    "blocked_connection_not_ready",
    "blocked_library_scan_pending",
    "blocked_library_empty",
    "waiting_for_code",
    "consent_required",
    "dry_run",
}
KNOWN_PUBLIC_CONSOLE_SURFACE_STATUSES = {
    "not_configured",
    "not_public",
    "reachable",
    "redirecting",
    "access_protected",
    "blocked_by_cloudflare",
    "route_not_found",
    "origin_error",
    "access_denied",
    "http_error",
    "probe_failed",
}


def _json(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _fresh_enough(receipt: dict[str, Any], *, root: Path) -> list[str]:
    issues: list[str] = []
    current_head = resolve_source_state_head(root)
    current_fingerprint = resolve_source_worktree_fingerprint(root)
    source_head = str(receipt.get("source_git_head") or "").strip()
    source_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    if receipt.get("head_semantics") != "source_state":
        issues.append("head_semantics must be source_state")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("source_state_fingerprint_semantics mismatch")
    if not source_head:
        issues.append("source_git_head missing")
    elif source_head != current_head and source_fingerprint != current_fingerprint:
        issues.append("receipt is stale relative to current source HEAD")
    if not source_fingerprint:
        issues.append("source_state_fingerprint missing")
    elif source_fingerprint != current_fingerprint:
        issues.append("receipt is stale relative to current source fingerprint")
    return issues


def verify_receipt_for_test(receipt: dict[str, Any], *, root: Path = ROOT) -> list[str]:
    issues: list[str] = []
    if not receipt:
        return ["mymedia alexa readiness receipt missing or invalid"]
    if receipt.get("contract_name") != CONTRACT_NAME:
        issues.append("contract_name mismatch")
    if receipt.get("generated_by") != "scripts/materialize_mymedia_alexa_readiness.py":
        issues.append("generated_by mismatch")
    issues.extend(_fresh_enough(receipt, root=root))

    status = str(receipt.get("status") or "").strip()
    if status not in KNOWN_STATUSES:
        issues.append(f"status must be one of {sorted(KNOWN_STATUSES)}")
    ready = bool(receipt.get("ready"))
    probe = dict(receipt.get("probe") or {})
    if not probe:
        issues.append("probe missing")
    if probe and str(probe.get("status") or "").strip() != status:
        issues.append("probe.status must match receipt status")
    if probe and bool(probe.get("ready")) != ready:
        issues.append("probe.ready must match receipt ready")
    if probe and bool(probe.get("probe_ok")) != bool(receipt.get("probe_ok")):
        issues.append("probe.probe_ok must match receipt probe_ok")
    if probe and str(probe.get("reason") or "").strip() != str(receipt.get("reason") or "").strip():
        issues.append("probe.reason must match receipt reason")
    if probe and str(probe.get("next_action") or "").strip() != str(receipt.get("next_action") or "").strip():
        issues.append("probe.next_action must match receipt next_action")
    if str(receipt.get("next_action_href") or "").strip() != ea_live_ops._operator_readiness_public_href(receipt.get("next_action_href")):
        issues.append("receipt next_action_href must be public/host-local sanitized")
    if receipt.get("echo_playback_claim_allowed") is not False:
        issues.append("echo_playback_claim_allowed must be false")

    privacy = dict(receipt.get("privacy") or {})
    for key in (
        "raw_refresh_token_exposed",
        "raw_paired_user_exposed",
        "raw_watch_folder_paths_exposed",
        "raw_public_ip_exposed",
        "raw_pairing_resume_url_exposed",
    ):
        if privacy.get(key) is not False:
            issues.append(f"privacy.{key} must be false")

    probe_privacy = dict(probe.get("privacy") or {})
    for key in (
        "raw_refresh_token_exposed",
        "raw_paired_user_exposed",
        "raw_watch_folder_paths_exposed",
        "raw_public_ip_exposed",
        "raw_pairing_resume_url_exposed",
    ):
        if probe_privacy.get(key) is not False:
            issues.append(f"probe.privacy.{key} must be false")
    for key in ("raw_public_surface_redirect_exposed", "raw_public_surface_response_body_exposed"):
        if probe_privacy.get(key, False) is not False:
            issues.append(f"probe.privacy.{key} must be false")

    public_console_surface = dict(receipt.get("public_console_surface") or {})
    if not public_console_surface:
        issues.append("public_console_surface missing")
    else:
        public_status = str(public_console_surface.get("status") or "").strip()
        if public_status not in KNOWN_PUBLIC_CONSOLE_SURFACE_STATUSES:
            issues.append(
                f"public_console_surface.status must be one of {sorted(KNOWN_PUBLIC_CONSOLE_SURFACE_STATUSES)}"
            )
        if bool(public_console_surface.get("configured")) != bool(probe.get("public_surface_configured")):
            issues.append("public_console_surface.configured must match probe.public_surface_configured")
        if str(public_console_surface.get("base_url_scope") or "").strip() != str(probe.get("public_surface_scope") or "").strip():
            issues.append("public_console_surface.base_url_scope must match probe.public_surface_scope")
        if bool(public_console_surface.get("probe_attempted")) != bool(probe.get("public_surface_probe_attempted")):
            issues.append("public_console_surface.probe_attempted must match probe.public_surface_probe_attempted")
        if bool(public_console_surface.get("ready")) != bool(probe.get("public_surface_ready")):
            issues.append("public_console_surface.ready must match probe.public_surface_ready")
        if public_status != str(probe.get("public_surface_status") or "").strip():
            issues.append("public_console_surface.status must match probe.public_surface_status")
        if str(public_console_surface.get("reason") or "").strip() != str(probe.get("public_surface_reason") or "").strip():
            issues.append("public_console_surface.reason must match probe.public_surface_reason")
        if int(public_console_surface.get("http_status_code") or 0) != int(probe.get("public_surface_http_status_code") or 0):
            issues.append("public_console_surface.http_status_code must match probe.public_surface_http_status_code")
        if bool(public_console_surface.get("access_protected")) != bool(probe.get("public_surface_access_protected")):
            issues.append("public_console_surface.access_protected must match probe.public_surface_access_protected")
        if bool(public_console_surface.get("cloudflare_blocked")) != bool(probe.get("public_surface_cloudflare_blocked")):
            issues.append("public_console_surface.cloudflare_blocked must match probe.public_surface_cloudflare_blocked")
        if str(public_console_surface.get("redirect_host") or "").strip() != str(probe.get("public_surface_redirect_host") or "").strip():
            issues.append("public_console_surface.redirect_host must match probe.public_surface_redirect_host")
        if str(public_console_surface.get("content_type") or "").strip() != str(probe.get("public_surface_content_type") or "").strip():
            issues.append("public_console_surface.content_type must match probe.public_surface_content_type")
        if str(public_console_surface.get("next_action") or "").strip() != str(probe.get("public_surface_next_action") or "").strip():
            issues.append("public_console_surface.next_action must match probe.public_surface_next_action")
        if str(public_console_surface.get("next_action_href") or "").strip() != str(probe.get("public_surface_next_action_href") or "").strip():
            issues.append("public_console_surface.next_action_href must match probe.public_surface_next_action_href")
        if str(public_console_surface.get("next_action_href") or "").strip() != ea_live_ops._operator_readiness_public_href(public_console_surface.get("next_action_href")):
            issues.append("public_console_surface.next_action_href must be public/host-local sanitized")
        if str(public_console_surface.get("next_action_label") or "").strip() != str(probe.get("public_surface_next_action_label") or "").strip():
            issues.append("public_console_surface.next_action_label must match probe.public_surface_next_action_label")
        if str(public_console_surface.get("next_action_method") or "").strip() != str(probe.get("public_surface_next_action_method") or "").strip():
            issues.append("public_console_surface.next_action_method must match probe.public_surface_next_action_method")
        if str(public_console_surface.get("source") or "").strip() != str(probe.get("public_surface_source") or "").strip():
            issues.append("public_console_surface.source must match probe.public_surface_source")
        if str(public_console_surface.get("source") or "").strip() != ea_live_ops._operator_readiness_public_source_ref(public_console_surface.get("source")):
            issues.append("public_console_surface.source must be public-source sanitized")
        public_surface_privacy = dict(public_console_surface.get("privacy") or {})
        for key in ("raw_redirect_url_exposed", "raw_response_headers_exposed", "raw_response_body_exposed"):
            if public_surface_privacy.get(key) is not False:
                issues.append(f"public_console_surface.privacy.{key} must be false")
        if bool(public_console_surface.get("ready")):
            if public_status not in {"reachable", "redirecting", "access_protected"}:
                issues.append("public_console_surface.ready=true requires a reachable status")
            if str(public_console_surface.get("reason") or "").strip():
                issues.append("public_console_surface.ready=true must not include a reason")
        elif bool(public_console_surface.get("configured")) and bool(public_console_surface.get("probe_attempted")):
            if public_status in {"reachable", "redirecting", "access_protected"}:
                issues.append("public_console_surface.ready=false cannot use a reachable status")
            if not str(public_console_surface.get("reason") or "").strip():
                issues.append("public_console_surface.ready=false with a probed configured surface requires a reason")

    operator_action = dict(receipt.get("operator_action") or {})
    expected_policy = "queue_only" if ready else "action_required_only"
    expected_budget = "none" if ready else "action_required"
    if operator_action.get("user_action_required") is not (not ready):
        issues.append("operator_action.user_action_required must match ready")
    if operator_action.get("delivery_policy") != expected_policy:
        issues.append("operator_action.delivery_policy mismatch")
    if operator_action.get("interruption_budget") != expected_budget:
        issues.append("operator_action.interruption_budget mismatch")
    if operator_action.get("next_action") != receipt.get("next_action"):
        issues.append("operator_action.next_action must match receipt")
    if operator_action.get("raw_private_context_exposed") is not False:
        issues.append("operator_action.raw_private_context_exposed must be false")
    if operator_action.get("telegram_delivery_ready") is not bool(
        dict(dict(receipt.get("pairing_telegram_delivery") or {}).get("telegram_delivery") or {}).get("ready")
    ):
        issues.append("operator_action.telegram_delivery_ready must match pairing_telegram_delivery.telegram_delivery.ready")

    pairing_resume_ready = bool(receipt.get("pairing_resume_ready"))
    if pairing_resume_ready != bool(operator_action.get("pairing_resume_ready")):
        issues.append("operator_action.pairing_resume_ready must match receipt")
    if pairing_resume_ready and not str(receipt.get("pairing_resume_command") or "").strip():
        issues.append("pairing_resume_command required when pairing_resume_ready")
    if not pairing_resume_ready and str(receipt.get("pairing_resume_command") or "").strip():
        issues.append("pairing_resume_command must be empty when pairing_resume_ready=false")
    if pairing_resume_ready and status != "blocked_pairing_required":
        issues.append("pairing_resume_ready is only valid while status=blocked_pairing_required")
    if pairing_resume_ready and receipt.get("next_action") not in {
        "enter_mymedia_amazon_pairing_code",
        "approve_mymedia_amazon_consent",
    }:
        issues.append("pairing_resume_ready requires a pairing resume next_action")

    pairing_telegram_delivery = dict(receipt.get("pairing_telegram_delivery") or {})
    if not pairing_telegram_delivery:
        issues.append("pairing_telegram_delivery missing")
    else:
        if pairing_telegram_delivery.get("dry_run") is not True:
            issues.append("pairing_telegram_delivery.dry_run must be true")
        if pairing_telegram_delivery.get("live_message_claim_allowed") is not False:
            issues.append("pairing_telegram_delivery.live_message_claim_allowed must be false")
        telegram_status = str(pairing_telegram_delivery.get("status") or "").strip()
        if telegram_status not in KNOWN_TELEGRAM_DELIVERY_STATUSES:
            issues.append(f"pairing_telegram_delivery.status must be one of {sorted(KNOWN_TELEGRAM_DELIVERY_STATUSES)}")
        if str(pairing_telegram_delivery.get("next_action_href") or "").strip() != ea_live_ops._operator_readiness_public_href(pairing_telegram_delivery.get("next_action_href")):
            issues.append("pairing_telegram_delivery.next_action_href must be public/host-local sanitized")
        if str(pairing_telegram_delivery.get("source") or "").strip() != ea_live_ops._operator_readiness_public_source_ref(pairing_telegram_delivery.get("source")):
            issues.append("pairing_telegram_delivery.source must be public-source sanitized")
        if bool(pairing_telegram_delivery.get("pairing_resume_ready")) != pairing_resume_ready:
            issues.append("pairing_telegram_delivery.pairing_resume_ready must match receipt")
        if bool(pairing_telegram_delivery.get("pairing_session_pending")) != bool(probe.get("pairing_session_pending")):
            issues.append("pairing_telegram_delivery.pairing_session_pending must match probe")
        if json.dumps(pairing_telegram_delivery.get("privacy") or {}, sort_keys=True):
            delivery_privacy = dict(pairing_telegram_delivery.get("privacy") or {})
            for key in ("raw_chat_ref_exposed", "raw_message_ids_exposed", "raw_message_text_exposed"):
                if delivery_privacy.get(key) is not False:
                    issues.append(f"pairing_telegram_delivery.privacy.{key} must be false")
        delivery = dict(pairing_telegram_delivery.get("telegram_delivery") or {})
        for forbidden_key in ("principal_id", "binding_id", "message_ids"):
            if forbidden_key in delivery:
                issues.append(f"pairing_telegram_delivery.telegram_delivery must not expose {forbidden_key}")
        if str(delivery.get("next_action_href") or "").strip() != ea_live_ops._operator_readiness_public_href(delivery.get("next_action_href")):
            issues.append("pairing_telegram_delivery.telegram_delivery.next_action_href must be public/host-local sanitized")
        if str(delivery.get("source") or "").strip() != ea_live_ops._operator_readiness_public_source_ref(delivery.get("source")):
            issues.append("pairing_telegram_delivery.telegram_delivery.source must be public-source sanitized")
        delivery_reason = str(delivery.get("reason") or "").strip()
        if delivery and delivery_reason == "dry_run":
            if bool(delivery.get("sent")):
                issues.append("pairing_telegram_delivery.telegram_delivery.sent must be false for dry_run")
            if delivery.get("delivery_transport") != "telegram_bot":
                issues.append("pairing_telegram_delivery.telegram_delivery.delivery_transport must be telegram_bot")
        if str(receipt.get("status") or "").strip() == "blocked_pairing_required" and receipt.get("next_action") in {
            "enter_mymedia_amazon_pairing_code",
            "approve_mymedia_amazon_consent",
        }:
            if pairing_telegram_delivery.get("next_action") != receipt.get("next_action"):
                issues.append("pairing_telegram_delivery.next_action must match receipt next_action during actionable pairing")
            if delivery_reason not in {"dry_run", "no_operator_action_required"}:
                issues.append("pairing_telegram_delivery.telegram_delivery.reason must be dry_run or no_operator_action_required")
            if not str(pairing_telegram_delivery.get("delivery_transport") or "").strip():
                issues.append("pairing_telegram_delivery.delivery_transport missing")
        if str(pairing_telegram_delivery.get("source") or "").strip() == "mymedia_setup.saved_session":
            if pairing_telegram_delivery.get("uses_saved_session") is not True:
                issues.append("pairing_telegram_delivery.uses_saved_session must be true when source is mymedia_setup.saved_session")

    if status == "ready":
        if not ready:
            issues.append("ready status requires ready=true")
        if str(receipt.get("reason") or "").strip():
            issues.append("ready status must not include a reason")
        if str(receipt.get("next_action") or "").strip():
            issues.append("ready status must not include next_action")
    elif status == "ready_library_scan_in_progress":
        if not ready:
            issues.append("ready_library_scan_in_progress requires ready=true")
        if str(receipt.get("reason") or "").strip() != "mymedia_library_scan_in_progress":
            issues.append("ready_library_scan_in_progress requires the scan-in-progress reason")
        if str(receipt.get("next_action") or "").strip() != "wait_for_mymedia_library_scan":
            issues.append("ready_library_scan_in_progress requires wait_for_mymedia_library_scan")
    else:
        if ready:
            issues.append("blocked status requires ready=false")
        if not str(receipt.get("reason") or "").strip():
            issues.append("blocked status requires reason")
        if not str(receipt.get("next_action") or "").strip():
            issues.append("blocked status requires next_action")

    serialized = json.dumps(receipt, sort_keys=True)
    if "rangersofB5" in serialized:
        issues.append("receipt appears to expose secret material")
    return issues


def verify(path: Path = DEFAULT_RECEIPT, *, root: Path = ROOT) -> list[str]:
    return verify_receipt_for_test(_json(path), root=root)


def main(argv: list[str] | None = None) -> int:
    if argv is None and any(flag in __import__("sys").argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python scripts/verify_mymedia_alexa_readiness.py [options]\n\n"
            "Verify the My Media for Alexa no-secret readiness receipt."
        )
        return 0
    parser = argparse.ArgumentParser(description="Verify the My Media for Alexa no-secret readiness receipt.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    issues = verify(Path(args.receipt))
    payload = {"status": "pass" if not issues else "fail", "issues": issues}
    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
