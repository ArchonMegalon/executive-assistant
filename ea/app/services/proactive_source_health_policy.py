from __future__ import annotations

from typing import Any, Mapping


GOOGLE_WORKSPACE_REAUTH_USER_ACTION_ERROR_CODES = frozenset(
    {
        "disconnected_by_operator",
        "google_oauth_access_denied",
        "google_oauth_access_token_missing",
        "google_oauth_account_mismatch",
        "google_oauth_binding_not_found",
        "google_oauth_invalid_grant",
        "google_oauth_refresh_failed",
        "google_oauth_unauthorized_client",
    }
)
SOURCE_HEALTH_USER_ACTION_NEXT_ACTIONS = frozenset(
    {
        "reauthorize_google_workspace_binding",
    }
)


def source_health_issue_requires_user_action(issue: Mapping[str, Any] | None) -> bool:
    row = dict(issue or {})
    if str(row.get("action_owner") or "").strip().lower() == "operator":
        return False
    if bool(row.get("user_action_required")):
        return True
    source_key = str(row.get("source_key") or "").strip()
    source_type = str(row.get("source_type") or "").strip()
    error_code = str(row.get("error_code") or row.get("reason_code") or "").strip()
    next_action = str(row.get("next_action") or "").strip()
    if next_action in SOURCE_HEALTH_USER_ACTION_NEXT_ACTIONS:
        return True
    if "google_workspace" in {source_key, source_type} and error_code in GOOGLE_WORKSPACE_REAUTH_USER_ACTION_ERROR_CODES:
        return True
    return False
