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
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json"
CONTRACT_NAME = "ea.pushbullet_delivery_readiness.v1"
KNOWN_STATUSES = {"blocked_setup_required", "ready_configured", "ready_live_verified"}


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
        issues.append("source state stale")
    if not source_fingerprint:
        issues.append("source_state_fingerprint missing")
    elif source_fingerprint != current_fingerprint:
        issues.append("source_state_fingerprint stale")
    return issues


def verify_receipt_for_test(receipt: dict[str, Any], *, root: Path = ROOT) -> list[str]:
    issues: list[str] = []
    if not receipt:
        return ["pushbullet delivery readiness receipt missing or invalid"]
    if receipt.get("contract_name") != CONTRACT_NAME:
        issues.append("contract_name mismatch")
    if receipt.get("generated_by") != "scripts/materialize_pushbullet_delivery_readiness.py":
        issues.append("generated_by mismatch")
    issues.extend(_fresh_enough(receipt, root=root))

    status = str(receipt.get("status") or "").strip()
    if status not in KNOWN_STATUSES:
        issues.append(f"status must be one of {sorted(KNOWN_STATUSES)}")
    if receipt.get("provider") != "pushbullet":
        issues.append("provider must be pushbullet")
    if str(receipt.get("api_base_url") or "").strip() != "https://api.pushbullet.com":
        issues.append("api_base_url mismatch")
    if not str(receipt.get("account_settings_url") or "").startswith("https://www.pushbullet.com/"):
        issues.append("account_settings_url must target Pushbullet")
    if not str(receipt.get("docs_url") or "").startswith("https://docs.pushbullet.com/"):
        issues.append("docs_url must target Pushbullet docs")

    clients = receipt.get("clients")
    if not isinstance(clients, list):
        issues.append("clients must be a list")
        clients = []
    if int(receipt.get("client_count") or 0) != len(clients):
        issues.append("client_count must match clients")

    by_key: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(clients):
        if not isinstance(row, dict):
            issues.append(f"clients[{index}] must be an object")
            continue
        if not str(row.get("client_key") or "").strip():
            issues.append(f"clients[{index}].client_key missing")
        else:
            by_key[str(row.get("client_key") or "").strip()] = row
        if bool(row.get("email_present")) and not str(row.get("email_sha256") or "").strip():
            issues.append(f"clients[{index}].email_sha256 missing")
        if not str(row.get("token_env") or "").strip():
            issues.append(f"clients[{index}].token_env missing")
        if row.get("raw_email_exposed") is not False:
            issues.append(f"clients[{index}].raw_email_exposed must be false")
        if row.get("raw_token_exposed") is not False:
            issues.append(f"clients[{index}].raw_token_exposed must be false")

    required_client_keys = [
        str(item or "").strip()
        for item in list(receipt.get("required_client_keys") or [])
        if str(item or "").strip()
    ]
    if not required_client_keys:
        issues.append("required_client_keys must include at least one client")
    multi_client_expected = bool(receipt.get("multi_client_expected"))
    coverage = dict(receipt.get("client_coverage") or {})
    if coverage.get("multi_client_expected") is not multi_client_expected:
        issues.append("client_coverage.multi_client_expected must match receipt")

    missing_client_keys = [key for key in required_client_keys if key not in by_key]
    missing_token_keys = [
        key
        for key in required_client_keys
        if key in by_key and not bool(by_key[key].get("token_present"))
    ]
    configured_required_count = len([key for key in required_client_keys if key in by_key])
    token_present_required_count = len(
        [
            key
            for key in required_client_keys
            if key in by_key and bool(by_key[key].get("token_present"))
        ]
    )
    expected_multi_ready = (
        bool(multi_client_expected)
        and len(required_client_keys) >= 2
        and not missing_client_keys
        and not missing_token_keys
    )
    if int(coverage.get("expected_client_count") or 0) != len(required_client_keys):
        issues.append("client_coverage.expected_client_count must match required_client_keys")
    if int(coverage.get("configured_client_count") or 0) != len(clients):
        issues.append("client_coverage.configured_client_count must match clients")
    if int(coverage.get("configured_required_client_count") or 0) != configured_required_count:
        issues.append("client_coverage.configured_required_client_count mismatch")
    if int(coverage.get("token_present_required_client_count") or 0) != token_present_required_count:
        issues.append("client_coverage.token_present_required_client_count mismatch")
    if sorted(list(coverage.get("missing_client_keys") or [])) != sorted(missing_client_keys):
        issues.append("client_coverage.missing_client_keys mismatch")
    if sorted(list(coverage.get("missing_token_keys") or [])) != sorted(missing_token_keys):
        issues.append("client_coverage.missing_token_keys mismatch")
    if bool(coverage.get("multi_client_ready")) != expected_multi_ready:
        issues.append("client_coverage.multi_client_ready mismatch")
    if multi_client_expected and len(required_client_keys) < 2:
        issues.append("multi_client_expected requires at least two required_client_keys")

    missing_setup = [str(item or "").strip() for item in list(receipt.get("missing_setup") or []) if str(item or "").strip()]
    for key in missing_client_keys:
        if f"pushbullet_client_missing:{key}" not in missing_setup:
            issues.append(f"missing_setup must include pushbullet_client_missing:{key}")
    for key in missing_token_keys:
        if f"pushbullet_token_missing:{key}" not in missing_setup:
            issues.append(f"missing_setup must include pushbullet_token_missing:{key}")
    if status == "blocked_setup_required" and not missing_setup:
        issues.append("blocked_setup_required receipt must include missing_setup")
    if status != "blocked_setup_required" and missing_setup:
        issues.append("non-blocked receipt must not include missing_setup")
    if status in {"ready_configured", "ready_live_verified"} and multi_client_expected and not expected_multi_ready:
        issues.append("ready Pushbullet receipt must cover every expected multi-client account")

    privacy = dict(receipt.get("privacy") or {})
    for key in ("raw_email_exposed", "raw_token_exposed", "raw_push_body_exposed", "raw_push_ids_exposed"):
        if privacy.get(key) is not False:
            issues.append(f"privacy.{key} must be false")

    claim = dict(receipt.get("delivery_claim") or {})
    if claim.get("irreversible_actions_consent_gated") is not True:
        issues.append("delivery_claim must keep irreversible actions consent-gated")
    if claim.get("non_action_progress_push_allowed") is not False:
        issues.append("delivery_claim must disallow non-action progress pushes")
    if bool(claim.get("pushbullet_note_delivery_ready")) != (status in {"ready_configured", "ready_live_verified"}):
        issues.append("pushbullet_note_delivery_ready must match status")
    if bool(claim.get("multi_client_delivery_ready")) != (
        status in {"ready_configured", "ready_live_verified"} and expected_multi_ready
    ):
        issues.append("multi_client_delivery_ready must match status and expected-client coverage")
    if bool(claim.get("live_token_account_verified")) != (status == "ready_live_verified"):
        issues.append("live_token_account_verified must match status")

    operator_action = dict(receipt.get("operator_action") or {})
    if operator_action.get("missing_setup") is not None:
        action_missing_setup = [
            str(item or "").strip()
            for item in list(operator_action.get("missing_setup") or [])
            if str(item or "").strip()
        ]
        if sorted(action_missing_setup) != sorted(missing_setup):
            issues.append("operator_action.missing_setup must match receipt")
    if operator_action.get("required_client_keys") is not None:
        action_required_keys = [
            str(item or "").strip()
            for item in list(operator_action.get("required_client_keys") or [])
            if str(item or "").strip()
        ]
        if action_required_keys != required_client_keys:
            issues.append("operator_action.required_client_keys must match receipt")
    if operator_action.get("user_action_required") is not bool(missing_setup):
        issues.append("operator_action.user_action_required must match missing_setup")
    if operator_action.get("delivery_policy") != ("action_required_only" if missing_setup else "queue_only"):
        issues.append("operator_action.delivery_policy mismatch")
    if operator_action.get("telegram_push_allowed") is not bool(missing_setup):
        issues.append("operator_action.telegram_push_allowed must match missing_setup")
    if operator_action.get("interruption_budget") != ("action_required" if missing_setup else "none"):
        issues.append("operator_action.interruption_budget mismatch")
    if operator_action.get("raw_email_exposed") is not False:
        issues.append("operator_action.raw_email_exposed must be false")
    if operator_action.get("raw_token_exposed") is not False:
        issues.append("operator_action.raw_token_exposed must be false")
    if operator_action.get("raw_private_context_exposed") is not False:
        issues.append("operator_action.raw_private_context_exposed must be false")
    if missing_setup and not operator_action.get("setup_checklist"):
        issues.append("operator_action.setup_checklist must be present while blocked")

    for index, probe in enumerate(list(receipt.get("live_probes") or [])):
        if not isinstance(probe, dict):
            issues.append(f"live_probes[{index}] must be an object")
            continue
        if probe.get("raw_email_exposed") is not False:
            issues.append(f"live_probes[{index}].raw_email_exposed must be false")
        if probe.get("raw_token_exposed") is not False:
            issues.append(f"live_probes[{index}].raw_token_exposed must be false")

    serialized = json.dumps(receipt, sort_keys=True)
    if "PB_TOKEN_ELISABETH=" in serialized or "rangersofB5" in serialized:
        issues.append("receipt appears to expose secret material")
    return issues


def verify(path: Path = DEFAULT_RECEIPT, *, root: Path = ROOT) -> list[str]:
    return verify_receipt_for_test(_json(path), root=root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify EA Pushbullet multi-client delivery readiness.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    issues = verify(Path(args.receipt))
    payload = {"status": "pass" if not issues else "fail", "issues": issues}
    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
