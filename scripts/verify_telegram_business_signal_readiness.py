#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/telegram_business_signal_readiness.generated.json"
CONTRACT_NAME = "ea.telegram_business_signal_readiness.v1"
ALLOWED_UPDATES = [
    "business_connection",
    "business_message",
    "edited_business_message",
    "deleted_business_messages",
]


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def verify(path: Path = DEFAULT_RECEIPT, *, root: Path = ROOT) -> list[str]:
    receipt = _json(path)
    issues: list[str] = []
    if not receipt:
        return [f"telegram_business_signal_readiness receipt missing or unreadable: {path}"]
    if receipt.get("contract_name") != CONTRACT_NAME:
        issues.append("contract_name mismatch")
    if receipt.get("head_semantics") != "source_state":
        issues.append("head_semantics must be source_state")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("source_state_fingerprint_semantics mismatch")
    current_head = resolve_source_state_head(root)
    current_fingerprint = resolve_source_worktree_fingerprint(root)
    source_head = str(receipt.get("source_git_head") or "").strip()
    source_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    if not source_head:
        issues.append("source_git_head missing")
    elif source_head != current_head and source_fingerprint != current_fingerprint:
        issues.append("source state stale")
    if not source_fingerprint:
        issues.append("source_state_fingerprint missing")
    elif source_fingerprint != current_fingerprint:
        issues.append("source_state_fingerprint stale")
    if receipt.get("business_mode") is not True:
        issues.append("business_mode must be true")
    if receipt.get("allowed_updates") != ALLOWED_UPDATES:
        issues.append("allowed_updates must be exactly Telegram Business update types")
    if str(receipt.get("webhook_path") or "").strip() not in {
        "/v1/channels/telegram/business/ingest",
        "/v1/channels/telegram/business/ingest/default",
    } and "/v1/channels/telegram/business/ingest/" not in str(receipt.get("webhook_path") or ""):
        issues.append("webhook_path must target the Telegram Business ingest endpoint")
    privacy = dict(receipt.get("privacy") or {})
    for key in (
        "raw_token_exposed",
        "raw_secret_exposed",
        "raw_chat_ids_exposed",
        "raw_webhook_url_exposed",
        "raw_payload_exposed",
    ):
        if privacy.get(key) is not False:
            issues.append(f"privacy flag must be false: {key}")
    bot_registry = dict(receipt.get("bot_registry") or {})
    for key in ("raw_token_exposed", "raw_secret_exposed", "raw_principal_id_exposed"):
        if bot_registry.get(key) is not False:
            issues.append(f"bot_registry privacy flag must be false: {key}")
    allowlist = dict(receipt.get("chat_allowlist") or {})
    for key in ("raw_chat_ids_exposed", "raw_chat_hashes_exposed"):
        if allowlist.get(key) is not False:
            issues.append(f"allowlist privacy flag must be false: {key}")
    code = dict(receipt.get("code") or {})
    for key in (
        "endpoint_present",
        "normalizer_present",
        "normalizer_allowed_updates_present",
        "normalizer_read_only_guards_present",
        "bootstrap_business_mode_present",
        "verifier_present",
    ):
        if code.get(key) is not True:
            issues.append(f"code check failed: {key}")
    status = str(receipt.get("status") or "").strip()
    if status not in {"pass", "blocked_setup_required"}:
        issues.append("status must be pass or blocked_setup_required")
    missing_setup = [str(item).strip() for item in list(receipt.get("missing_setup") or []) if str(item).strip()]
    operator_action = dict(receipt.get("operator_action") or {})
    if status == "pass" and missing_setup:
        issues.append("pass receipt must not include missing_setup")
    if status == "blocked_setup_required" and not missing_setup:
        issues.append("blocked_setup_required receipt must include missing_setup")
    if bool(operator_action.get("user_action_required")) != bool(missing_setup):
        issues.append("operator_action.user_action_required must match missing_setup")
    if operator_action.get("non_action_progress_push_allowed") is not False:
        issues.append("operator_action must disallow non-action progress pushes")
    if operator_action.get("irreversible_actions_consent_gated") is not True:
        issues.append("operator_action must preserve irreversible-action consent gate")
    if "does_not_prove" not in str(receipt.get("claim_boundary") or ""):
        issues.append("claim_boundary must keep an explicit does_not_prove statement")
    setup_commands = " ".join(str(item) for item in list(receipt.get("setup_commands") or []))
    if "--business --set-webhook" not in setup_commands:
        issues.append("setup_commands must include the Business webhook bootstrap command")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Telegram Business/Secretary signal ingest readiness.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    issues = verify(args.receipt)
    result = {
        "contract_name": "ea.telegram_business_signal_readiness_verification.v1",
        "status": "fail" if issues else "pass",
        "issues": issues,
    }
    print(json.dumps(result, sort_keys=True))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
