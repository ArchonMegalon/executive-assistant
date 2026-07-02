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
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json"
CONTRACT_NAME = "ea.google_workspace_oauth_readiness.v1"
KNOWN_STATUSES = {"pass", "ready_manual_console_check", "blocked_setup_required"}
REQUIRED_WORKSPACE_APIS = {
    "gmail.googleapis.com",
    "calendar-json.googleapis.com",
    "people.googleapis.com",
    "drive.googleapis.com",
}
PRIVATE_FLAGS = (
    "raw_expected_google_email_exposed",
    "raw_client_id_exposed",
    "raw_client_secret_exposed",
    "raw_state_secret_exposed",
    "raw_provider_secret_exposed",
    "raw_google_code_exposed",
    "raw_access_token_exposed",
    "raw_refresh_token_exposed",
    "raw_gcloud_token_exposed",
    "raw_gcloud_account_exposed",
    "raw_error_description_exposed",
)


def _expected_operator_next_action(missing_setup: list[str]) -> tuple[str, str]:
    if "gcloud_project_mismatch" in missing_setup:
        return "select_google_oauth_project_and_retry_full_workspace_auth", "Open Google setup"
    if "oauth_access_retry_or_account_selection_required" in missing_setup:
        return "retry_full_workspace_auth_with_approved_account", "Retry Google auth"
    return "add_google_oauth_test_user_and_retry_full_workspace_auth", "Open Google setup"


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


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
        return ["google workspace oauth readiness receipt missing or invalid"]
    if receipt.get("contract_name") != CONTRACT_NAME:
        issues.append("contract_name mismatch")
    issues.extend(_fresh_enough(receipt, root=root))
    status = str(receipt.get("status") or "").strip()
    if status not in KNOWN_STATUSES:
        issues.append(f"status must be one of {sorted(KNOWN_STATUSES)}")
    if str(receipt.get("scope_bundle") or "").strip() != "full_workspace":
        issues.append("scope_bundle must be full_workspace for this readiness receipt")
    if "Google Auth Platform > Audience > Test users" not in str(receipt.get("google_auth_platform_path") or ""):
        issues.append("google_auth_platform_path must name the test-user console path")
    console_link = str(receipt.get("console_deep_link") or "").strip()
    if not console_link.startswith("https://console.cloud.google.com/auth/audience"):
        issues.append("console_deep_link must target Google Auth Platform Audience")
    auth_link_template = str(receipt.get("auth_link_template") or "").strip()
    if "/app/actions/google/connect?" not in auth_link_template:
        issues.append("auth_link_template must target the local Google connect action")
    if "scope_bundle=full_workspace" not in auth_link_template:
        issues.append("auth_link_template must include full_workspace scope bundle")

    privacy = dict(receipt.get("privacy") or {})
    for key in PRIVATE_FLAGS:
        if privacy.get(key) is not False:
            issues.append(f"privacy.{key} must be false")

    expected = dict(receipt.get("expected_google_account") or {})
    if expected.get("present") is True and not str(expected.get("email_sha256") or "").strip():
        issues.append("expected_google_account.email_sha256 must be present when expected account is present")
    if expected.get("raw_expected_google_email_exposed") is not False:
        issues.append("expected_google_account must not expose raw email")

    test_user_confirmation = dict(receipt.get("test_user_confirmation") or {})
    if test_user_confirmation.get("confirmed") not in {True, False}:
        issues.append("test_user_confirmation.confirmed must be boolean")
    if test_user_confirmation.get("raw_source_exposed") is not False:
        issues.append("test_user_confirmation.raw_source_exposed must be false")
    evidence_type = str(test_user_confirmation.get("evidence_type") or "").strip()
    if evidence_type not in {"operator_asserted", "unconfirmed"}:
        issues.append("test_user_confirmation.evidence_type must be operator_asserted or unconfirmed")

    oauth_client = dict(receipt.get("oauth_client") or {})
    for key in (
        "raw_client_id_exposed",
        "raw_client_secret_exposed",
        "raw_state_secret_exposed",
        "raw_provider_secret_exposed",
    ):
        if oauth_client.get(key) is not False:
            issues.append(f"oauth_client.{key} must be false")
    if not str(oauth_client.get("client_project_id") or "").strip():
        issues.append("oauth_client.client_project_id must be present")
    if not str(oauth_client.get("client_project_number") or "").strip():
        issues.append("oauth_client.client_project_number must be present")

    gcloud = dict(receipt.get("gcloud_probe") or {})
    for key in ("raw_gcloud_account_exposed", "raw_gcloud_token_exposed"):
        if gcloud.get(key) is not False:
            issues.append(f"gcloud_probe.{key} must be false")
    if gcloud.get("enabled") is True:
        if "test_user_mutation_supported_by_gcloud_cli" not in gcloud:
            issues.append("gcloud_probe must record whether gcloud supports test-user mutation")
        if gcloud.get("test_user_mutation_supported_by_gcloud_cli") is not False:
            issues.append("gcloud_probe must not claim an unsupported gcloud test-user mutation")
        if gcloud.get("manual_console_test_user_step_required") is not True:
            issues.append("gcloud_probe must preserve the manual console test-user step")

    workspace_apis = dict(receipt.get("google_workspace_apis") or {})
    required_apis = {
        str(item or "").strip()
        for item in list(workspace_apis.get("required") or [])
        if str(item or "").strip()
    }
    missing_apis = [
        str(item or "").strip()
        for item in list(workspace_apis.get("missing_required") or [])
        if str(item or "").strip()
    ]
    enabled_apis = {
        str(item or "").strip()
        for item in list(workspace_apis.get("enabled_required") or [])
        if str(item or "").strip()
    }
    if required_apis != REQUIRED_WORKSPACE_APIS:
        issues.append("google_workspace_apis.required must include Gmail, Calendar, People, and Drive APIs")
    if workspace_apis.get("probe_enabled") is True:
        if str(workspace_apis.get("status") or "").strip() not in {"pass", "blocked"}:
            issues.append("google_workspace_apis.status must be pass or blocked when probed")
        if missing_apis and "google_workspace_apis_missing" not in list(receipt.get("missing_setup") or []):
            issues.append("missing Google Workspace APIs must block setup")
        if str(workspace_apis.get("status") or "").strip() == "pass":
            if missing_apis:
                issues.append("google_workspace_apis pass must not include missing APIs")
            if enabled_apis != REQUIRED_WORKSPACE_APIS:
                issues.append("google_workspace_apis pass must prove all required APIs enabled")
    else:
        if str(workspace_apis.get("status") or "").strip() not in {"not_probed", ""}:
            issues.append("google_workspace_apis.status must be not_probed when probe is disabled")

    missing_setup = [
        str(item).strip()
        for item in list(receipt.get("missing_setup") or [])
        if str(item).strip()
    ]
    if status == "blocked_setup_required" and not missing_setup:
        issues.append("blocked_setup_required receipt must include missing_setup")
    if status != "blocked_setup_required" and missing_setup:
        issues.append("non-blocked receipt must not include missing_setup")
    if str(receipt.get("observed_error") or "").strip() == "access_denied":
        expected_blocker = (
            "oauth_retry_or_account_selection_required"
            if "oauth_access_retry_or_account_selection_required" in missing_setup
            else "oauth_test_user_or_verification_required"
        )
        if receipt.get("blocker_kind") != expected_blocker:
            issues.append(f"access_denied must map to {expected_blocker}")
        if (
            "oauth_test_user_missing_or_app_unverified" not in missing_setup
            and "oauth_access_retry_or_account_selection_required" not in missing_setup
            and status != "pass"
        ):
            issues.append("access_denied must require either OAuth tester setup or an explicit retry/account-selection step")

    operator_action = dict(receipt.get("operator_action") or {})
    if operator_action.get("user_action_required") is not bool(missing_setup):
        issues.append("operator_action.user_action_required must match missing_setup")
    if operator_action.get("delivery_policy") != ("action_required_only" if missing_setup else "queue_only"):
        issues.append("operator_action.delivery_policy mismatch")
    if operator_action.get("telegram_push_allowed") is not bool(missing_setup):
        issues.append("operator_action.telegram_push_allowed must match missing_setup")
    if operator_action.get("interruption_budget") != ("action_required" if missing_setup else "none"):
        issues.append("operator_action.interruption_budget mismatch")
    if operator_action.get("quiet_hours_respected") is not True:
        issues.append("operator_action.quiet_hours_respected must be true")
    if operator_action.get("non_action_progress_push_allowed") is not False:
        issues.append("operator_action must disallow non-action progress pushes")
    if operator_action.get("irreversible_actions_consent_gated") is not True:
        issues.append("operator_action must keep irreversible actions consent-gated")
    expected_next_action, expected_next_action_label = _expected_operator_next_action(missing_setup)
    if operator_action.get("next_action") != expected_next_action:
        issues.append("operator_action.next_action mismatch")
    if operator_action.get("next_action_href") != "/integrations/google":
        issues.append("operator_action.next_action_href must target /integrations/google")
    if operator_action.get("next_action_label") != expected_next_action_label:
        issues.append("operator_action.next_action_label mismatch")
    if str(operator_action.get("next_action_method") or "").strip().lower() != "get":
        issues.append("operator_action.next_action_method must be get")
    if operator_action.get("console_deep_link") != console_link:
        issues.append("operator_action.console_deep_link must mirror receipt console_deep_link")
    if operator_action.get("auth_link_template") != auth_link_template:
        issues.append("operator_action.auth_link_template must mirror receipt auth_link_template")
    if operator_action.get("raw_expected_google_email_exposed") is not False:
        issues.append("operator_action must not expose raw expected Google email")
    for key in (
        "raw_private_context_exposed",
        "raw_client_id_exposed",
        "raw_client_secret_exposed",
        "raw_token_exposed",
        "raw_secret_exposed",
        "raw_error_description_exposed",
    ):
        if operator_action.get(key) is not False:
            issues.append(f"operator_action.{key} must be false")
    if missing_setup:
        checklist = operator_action.get("setup_checklist")
        if not isinstance(checklist, list) or not checklist:
            issues.append("operator_action.setup_checklist must be present while blocked")
        else:
            checklist_keys = {
                str(dict(item).get("key") or "").strip()
                for item in checklist
                if isinstance(item, dict)
            }
            for key in missing_setup:
                if key not in checklist_keys:
                    issues.append(f"operator_action.setup_checklist missing key: {key}")
        if not str(operator_action.get("telegram_message") or "").strip():
            issues.append("operator_action.telegram_message must be present while blocked")

    notification = dict(receipt.get("telegram_notification") or {})
    if notification.get("should_send") is not bool(missing_setup):
        issues.append("telegram_notification.should_send must match missing_setup")
    if notification.get("delivery_policy") != "action_required_only":
        issues.append("telegram_notification.delivery_policy must be action_required_only")
    if notification.get("non_action_progress_push_allowed") is not False:
        issues.append("telegram_notification must disallow non-action progress pushes")
    if notification.get("raw_private_context_exposed") is not False:
        issues.append("telegram_notification must not expose raw private context")
    if notification.get("raw_expected_google_email_exposed") is not False:
        issues.append("telegram_notification must not expose raw expected Google email")

    setup_commands = " ".join(str(item) for item in list(receipt.get("setup_commands") or []))
    if "materialize_google_workspace_oauth_readiness.py" not in setup_commands:
        issues.append("setup_commands must include the Google OAuth readiness materializer")
    if "verify_google_workspace_oauth_readiness.py" not in setup_commands:
        issues.append("setup_commands must include the Google OAuth readiness verifier")
    if "does_not_prove" not in str(receipt.get("claim_boundary") or ""):
        issues.append("claim_boundary must keep an explicit does_not_prove statement")
    return issues


def verify(path: Path = DEFAULT_RECEIPT, *, root: Path = ROOT) -> list[str]:
    receipt = _json(path)
    if not receipt:
        return [f"google workspace oauth readiness receipt missing or invalid: {path}"]
    return verify_receipt_for_test(receipt, root=root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Google Workspace OAuth readiness.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    issues = verify(args.receipt)
    result = {
        "contract_name": "ea.google_workspace_oauth_readiness_verification.v1",
        "status": "fail" if issues else "pass",
        "issues": issues,
    }
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
