#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json"
OPERATOR_SAFE_RECEIPT_FILE_MODE = 0o644
DEFAULT_OPERATOR_STATUS = ROOT / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
CONTRACT_NAME = "ea.google_workspace_oauth_readiness.v1"
DEFAULT_SCOPE_BUNDLE = "full_workspace"
GOOGLE_AUTH_AUDIENCE_PATH = "Google Auth Platform > Audience > Test users"
REQUIRED_ENV = (
    "EA_GOOGLE_OAUTH_CLIENT_ID",
    "EA_GOOGLE_OAUTH_CLIENT_SECRET",
    "EA_GOOGLE_OAUTH_REDIRECT_URI",
    "EA_GOOGLE_OAUTH_STATE_SECRET",
    "EA_PROVIDER_SECRET_KEY",
)
REQUIRED_WORKSPACE_APIS = (
    "gmail.googleapis.com",
    "calendar-json.googleapis.com",
    "people.googleapis.com",
    "drive.googleapis.com",
)
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
    "raw_observed_google_email_exposed",
    "raw_error_description_exposed",
)
RETRY_ONLY_MISSING_SETUP = {
    "oauth_access_retry_or_account_selection_required",
    "oauth_account_selection_mismatch",
}
MANUAL_CONSOLE_CHECK_ONLY_MISSING_SETUP = {
    "oauth_test_user_confirmation_pending",
}
LIVE_REAUTH_RETRY_REASONS = {
    "disconnected_by_operator",
    "google_oauth_invalid_grant",
    "google_oauth_refresh_failed",
}
RunCommand = Callable[[list[str], float], tuple[int, str, str]]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(value: str) -> str:
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _configured_expected_google_email() -> str:
    for key in ("EA_GOOGLE_WORKSPACE_EXPECTED_EMAIL", "EA_GOOGLE_OAUTH_EXPECTED_EMAIL"):
        value = str(os.environ.get(key) or "").strip().lower()
        if "@" in value:
            return value
    return ""


def _load_env_file(path: Path | None) -> None:
    if path is None or not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def _source_state() -> dict[str, str]:
    return {
        "source_git_head": resolve_source_state_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _source_fresh(payload: dict[str, Any], *, current_source_state: dict[str, str]) -> bool:
    source_head = str(payload.get("source_git_head") or "").strip()
    source_fingerprint = str(payload.get("source_state_fingerprint") or "").strip()
    return bool(
        (source_head and source_head == str(current_source_state.get("source_git_head") or "").strip())
        or (
            source_fingerprint
            and source_fingerprint == str(current_source_state.get("source_state_fingerprint") or "").strip()
        )
    )


def _operator_status_google_workspace_issue(
    *,
    current_source_state: dict[str, str],
    operator_status_path: Path | None = None,
) -> dict[str, Any]:
    operator_status_path = operator_status_path or DEFAULT_OPERATOR_STATUS
    payload = _load_json(operator_status_path)
    if not payload or not _source_fresh(payload, current_source_state=current_source_state):
        return {}
    source_health = dict(payload.get("source_health") or {})
    for raw_issue in list(source_health.get("issues") or []):
        issue = dict(raw_issue or {}) if isinstance(raw_issue, dict) else {}
        source_key = str(issue.get("source_key") or issue.get("source_type") or "").strip()
        if source_key != "google_workspace":
            continue
        error_code = str(issue.get("error_code") or "").strip()
        if error_code:
            try:
                cooldown_seconds_remaining = max(int(issue.get("cooldown_seconds_remaining") or 0), 0)
            except Exception:
                cooldown_seconds_remaining = 0
            return {
                "error_code": error_code,
                "recovery_mode": str(issue.get("recovery_mode") or "").strip(),
                "blocked_until": str(issue.get("blocked_until") or issue.get("cooldown_until") or "").strip(),
                "cooldown_active": bool(issue.get("cooldown_active")),
                "cooldown_seconds_remaining": cooldown_seconds_remaining,
                "last_observed_at": str(issue.get("last_observed_at") or "").strip(),
                "source": "source_health_issue",
            }
    reason = str(payload.get("reason") or "").strip()
    for prefix in ("source_health_google_workspace:", "google_workspace_signal_source_unhealthy:"):
        if reason.startswith(prefix):
            return {
                "error_code": reason[len(prefix) :].strip(),
                "recovery_mode": "",
                "blocked_until": "",
                "cooldown_active": False,
                "cooldown_seconds_remaining": 0,
                "last_observed_at": "",
                "source": "reason_prefix",
            }
    return {}


def _operator_status_reauth_required_reason(
    *,
    current_source_state: dict[str, str],
    operator_status_path: Path | None = None,
) -> str:
    return str(
        _operator_status_google_workspace_issue(
            current_source_state=current_source_state,
            operator_status_path=operator_status_path,
        ).get("error_code")
        or ""
    ).strip()


def _project_number_from_client_id(client_id: str) -> str:
    match = re.match(r"^(\d+)-", str(client_id or "").strip())
    return match.group(1) if match else ""


def _public_app_base_url() -> str:
    return (_env("EA_PUBLIC_APP_BASE_URL") or "https://myexternalbrain.com").rstrip("/")


def _connect_link_template(*, scope_bundle: str, expected_google_email_present: bool) -> str:
    query: dict[str, str] = {
        "return_to": "/app/settings/google",
        "scope_bundle": scope_bundle or DEFAULT_SCOPE_BUNDLE,
    }
    if expected_google_email_present:
        query["expected_google_email"] = "<redacted-email>"
    return f"{_public_app_base_url()}/app/actions/google/connect?{urllib.parse.urlencode(query)}"


def _console_deep_link(project_id: str) -> str:
    normalized = str(project_id or "").strip()
    if not normalized:
        return "https://console.cloud.google.com/auth/audience"
    return "https://console.cloud.google.com/auth/audience?" + urllib.parse.urlencode({"project": normalized})


def _email_domain(email: str) -> str:
    normalized = str(email or "").strip().lower()
    return normalized.rsplit("@", 1)[1] if "@" in normalized else ""


def _run_command(command: list[str], timeout_seconds: float) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(float(timeout_seconds or 5.0), 1.0),
        )
    except Exception as exc:
        return 124, "", type(exc).__name__
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _gcloud_probe(
    *,
    oauth_project_id: str,
    oauth_project_number: str,
    timeout_seconds: float,
    runner: RunCommand | None = None,
) -> dict[str, Any]:
    runner = runner or _run_command
    available = shutil.which("gcloud") is not None
    probe: dict[str, Any] = {
        "enabled": True,
        "gcloud_available": available,
        "active_account_present": False,
        "active_account_sha256": "",
        "active_account_domain": "",
        "active_project": "",
        "active_project_matches_oauth_project": False,
        "oauth_project_id": oauth_project_id,
        "oauth_project_number": oauth_project_number,
        "project_describe_status": "skipped",
        "project_number_matches_client_id": False,
        "required_workspace_apis": list(REQUIRED_WORKSPACE_APIS),
        "enabled_required_workspace_apis": [],
        "missing_required_workspace_apis": list(REQUIRED_WORKSPACE_APIS),
        "workspace_api_probe_status": "skipped",
        "test_user_mutation_supported_by_gcloud_cli": False,
        "test_user_mutation_command": "",
        "manual_console_test_user_step_required": True,
        "raw_gcloud_account_exposed": False,
        "raw_gcloud_token_exposed": False,
    }
    if not available:
        probe["status"] = "blocked"
        probe["reason"] = "gcloud_not_available"
        return probe

    code, stdout, _stderr = runner(["gcloud", "config", "get-value", "account"], timeout_seconds)
    active_account = stdout.splitlines()[0].strip() if code == 0 and stdout else ""
    if active_account and active_account != "(unset)":
        probe["active_account_present"] = True
        probe["active_account_sha256"] = _sha256(active_account.lower())
        probe["active_account_domain"] = _email_domain(active_account)

    code, stdout, _stderr = runner(["gcloud", "config", "get-value", "project"], timeout_seconds)
    active_project = stdout.splitlines()[0].strip() if code == 0 and stdout else ""
    if active_project and active_project != "(unset)":
        probe["active_project"] = active_project
        probe["active_project_matches_oauth_project"] = bool(oauth_project_id and active_project == oauth_project_id)

    project_to_describe = oauth_project_id or active_project
    if project_to_describe:
        code, stdout, _stderr = runner(
            ["gcloud", "projects", "describe", project_to_describe, "--format=json"],
            timeout_seconds,
        )
        probe["project_describe_status"] = "pass" if code == 0 and stdout else "blocked"
        try:
            described = json.loads(stdout) if stdout else {}
        except Exception:
            described = {}
        described_number = str(dict(described).get("projectNumber") or "").strip()
        probe["described_project_number_present"] = bool(described_number)
        probe["project_number_matches_client_id"] = bool(
            described_number and oauth_project_number and described_number == oauth_project_number
        )
        code, stdout, _stderr = runner(
            [
                "gcloud",
                "services",
                "list",
                "--enabled",
                f"--project={project_to_describe}",
                "--format=value(config.name)",
            ],
            timeout_seconds,
        )
        if code == 0:
            enabled = {
                str(line or "").strip()
                for line in str(stdout or "").splitlines()
                if str(line or "").strip()
            }
            enabled_required = [api for api in REQUIRED_WORKSPACE_APIS if api in enabled]
            missing_required = [api for api in REQUIRED_WORKSPACE_APIS if api not in enabled]
            probe["workspace_api_probe_status"] = "pass" if not missing_required else "blocked"
            probe["enabled_required_workspace_apis"] = enabled_required
            probe["missing_required_workspace_apis"] = missing_required
        else:
            probe["workspace_api_probe_status"] = "blocked"

    probe["status"] = (
        "pass"
        if probe["active_account_present"]
        and (not oauth_project_id or probe["active_project_matches_oauth_project"])
        and probe["workspace_api_probe_status"] == "pass"
        else "blocked"
    )
    probe["reason"] = (
        "gcloud_project_ready_but_manual_auth_platform_test_user_step_required"
        if probe["status"] == "pass"
        else "gcloud_project_or_account_not_ready"
    )
    return probe


def _setup_checklist(missing: list[str], *, console_link: str, auth_link_template: str) -> list[dict[str, str]]:
    entries = {
        "oauth_test_user_confirmation_pending": {
            "label": "Confirm the work Google account is allowed in OAuth Audience",
            "how": (
                f"Open {console_link}, go to {GOOGLE_AUTH_AUDIENCE_PATH}, confirm the requested account is listed there "
                f"or add it if missing, save, then retry {auth_link_template}."
            ),
        },
        "oauth_test_user_missing_or_app_unverified": {
            "label": "Confirm the work Google account is allowed in OAuth Audience",
            "how": (
                f"Open {console_link}, go to {GOOGLE_AUTH_AUDIENCE_PATH}, confirm the requested account is listed there "
                f"or add it if missing, save, then retry {auth_link_template}."
            ),
        },
        "oauth_access_retry_or_account_selection_required": {
            "label": "Retry Full Workspace auth with the approved Google account",
            "how": (
                f"Open {auth_link_template}, explicitly choose the approved work Google account, finish consent, "
                f"and if Google still denies access reopen {console_link} to confirm the Audience save and selected OAuth project."
            ),
        },
        "oauth_account_selection_mismatch": {
            "label": "Retry Full Workspace auth with the intended Google account",
            "how": (
                f"Open {auth_link_template}, switch to the intended work Google account in the account chooser, "
                f"then finish consent. If Google still denies access, reopen {console_link} to confirm that exact account is listed."
            ),
        },
        "expected_google_email_missing": {
            "label": "Choose the expected work Google account",
            "how": "Pass --expected-google-email when building the auth-readiness receipt so the retry link can force account selection.",
        },
        "oauth_project_id_missing": {
            "label": "Record the Google OAuth project ID",
            "how": "Set EA_GOOGLE_OAUTH_PROJECT_ID to the project that owns the OAuth client.",
        },
        "gcloud_project_mismatch": {
            "label": "Select the OAuth project in gcloud",
            "how": "Run gcloud config set project <oauth-project-id>, then rerun the readiness materializer.",
        },
        "google_workspace_apis_missing": {
            "label": "Enable the required Google Workspace APIs",
            "how": (
                "Enable Gmail API, Google Calendar API, People API, and Google Drive API on the OAuth project, "
                "then rerun the readiness materializer."
            ),
        },
        "google_workspace_api_probe_unavailable": {
            "label": "Verify required Google Workspace APIs",
            "how": (
                "Run gcloud services list --enabled on the OAuth project and confirm Gmail, Calendar, People, "
                "and Drive APIs are enabled."
            ),
        },
    }
    for env_key in REQUIRED_ENV:
        entries[f"env_{env_key.lower()}_missing"] = {
            "label": f"Set {env_key}",
            "how": f"Add {env_key} to the EA environment without committing the secret value.",
        }
    result: list[dict[str, str]] = []
    for key in missing:
        if key in entries:
            result.append({"key": key, **entries[key]})
        elif key:
            result.append({"key": key, "label": "Complete Google OAuth setup", "how": f"Resolve setup check: {key}."})
    return result


def _instruction_text(
    *,
    missing: list[str],
    reauth_required_reason: str = "",
    runtime_recovery: Mapping[str, Any] | None = None,
) -> str:
    recovery = dict(runtime_recovery or {})
    blocked_until = str(recovery.get("blocked_until") or "").strip()
    if reauth_required_reason in LIVE_REAUTH_RETRY_REASONS and "oauth_access_retry_or_account_selection_required" in missing:
        cooldown_suffix = f" A bounded recovery cooldown is active until {blocked_until}." if blocked_until else ""
        return (
            "Google Workspace auth needs reauthorization before EA can rely on that source. "
            "Retry the Full Workspace auth link with the approved work Google account."
            f"{cooldown_suffix}"
        )
    if "oauth_account_selection_mismatch" in missing:
        return (
            "Retry the Full Workspace auth link and switch to the intended work Google account in the Google account chooser. "
            "The selected Google account observed on the failed consent attempt did not match the expected work account."
        )
    if "oauth_test_user_confirmation_pending" in missing:
        return (
            "Open the Google Auth Platform Audience page, confirm the requested work Google account is allowed there, "
            "add it if missing, save, then retry the Full Workspace auth link."
        )
    if "gcloud_project_mismatch" in missing:
        return (
            "Open the Google Auth Platform Audience page for the OAuth project, confirm the requested work Google account "
            "is allowed there, then retry the Full Workspace auth link."
        )
    if "oauth_access_retry_or_account_selection_required" in missing:
        return (
            "Retry the Full Workspace auth link and explicitly choose the approved work Google account. "
            "If Google still denies access, reopen the Google Auth Platform Audience page and confirm the tester save has propagated."
        )
    if "google_workspace_apis_missing" in missing:
        return (
            "Enable the required Google Workspace APIs on the OAuth project, then retry the Full Workspace auth link."
        )
    return (
        "Open the Google Auth Platform Audience page, confirm the requested work Google account is allowed there, "
        "add it if missing, save, then retry the Full Workspace auth link."
    )


def _telegram_message(
    *,
    missing: list[str],
    console_link: str,
    reauth_required_reason: str = "",
    runtime_recovery: Mapping[str, Any] | None = None,
) -> str:
    recovery = dict(runtime_recovery or {})
    if not missing:
        return ""
    if reauth_required_reason in LIVE_REAUTH_RETRY_REASONS and "oauth_access_retry_or_account_selection_required" in missing:
        blocked_until = str(recovery.get("blocked_until") or "").strip()
        cooldown_suffix = f" Cooldown active until {blocked_until}." if blocked_until else ""
        return (
            "Action needed: Google Workspace auth needs reauthorization before EA can rely on that source. "
            "Retry the Full Workspace auth link with the approved work account. "
            f"If Google still blocks it, re-open the Audience page and confirm the tester/project setup.{cooldown_suffix} Console: {console_link}"
        )
    if "oauth_account_selection_mismatch" in missing:
        return (
            "Action needed: Google Full Workspace auth was attempted with a different selected Google account than the intended work account. "
            "Retry the auth link and switch to the intended work account in the Google account chooser. "
            f"If it still fails, confirm that exact account on the Audience page. Console: {console_link}"
        )
    if "gcloud_project_mismatch" in missing:
        return (
            "Action needed: Google Full Workspace auth is tied to a different OAuth project than the current gcloud default. "
            f"Open the OAuth project's Audience page, confirm the work account is a test user there, then retry the auth link. Console: {console_link}"
        )
    if "oauth_test_user_confirmation_pending" in missing:
        return (
            "Action needed: Google Full Workspace auth still needs a manual Audience-page check. "
            "Open Google Auth Platform, confirm the requested work account is allowed there, add it if missing, save, then retry the auth link. "
            f"Console: {console_link}"
        )
    if "oauth_test_user_missing_or_app_unverified" in missing:
        return (
            "Action needed: Google Full Workspace auth is blocked because the OAuth app is still in testing. "
            "Open Google Auth Platform, confirm the requested work Google account is allowed there, "
            f"add it if missing, then retry the auth link. Console: {console_link}"
        )
    if "oauth_access_retry_or_account_selection_required" in missing:
        return (
            "Action needed: Google Full Workspace auth is still denied even though the work account is already approved. "
            "Retry the auth link, explicitly choose the approved account, and if Google still blocks it re-open the Audience page to confirm the save. "
            f"Console: {console_link}"
        )
    if "google_workspace_apis_missing" in missing:
        return (
            "Action needed: Google Full Workspace auth is not ready because required APIs are missing on the OAuth project. "
            "Enable Gmail, Calendar, People, and Drive APIs, then retry the auth link."
        )
    return "Action needed: Google Workspace OAuth setup is incomplete. Open the Google integration setup and clear the listed checks."


def _operator_next_action(missing: list[str]) -> tuple[str, str]:
    if "gcloud_project_mismatch" in missing:
        return "select_google_oauth_project_and_retry_full_workspace_auth", "Open Google setup"
    if "oauth_account_selection_mismatch" in missing:
        return "retry_full_workspace_auth_with_expected_account", "Retry Google auth"
    if "oauth_access_retry_or_account_selection_required" in missing:
        return "retry_full_workspace_auth_with_approved_account", "Retry Google auth"
    return "add_google_oauth_test_user_and_retry_full_workspace_auth", "Open Google setup"


def build_receipt(
    *,
    expected_google_email: str = "",
    scope_bundle: str = DEFAULT_SCOPE_BUNDLE,
    observed_error: str = "",
    error_description: str = "",
    observed_google_email: str = "",
    test_user_confirmed: bool = False,
    reauth_required_reason: str = "",
    probe_gcloud: bool = False,
    include_env_file: Path | None = None,
    runner: RunCommand | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    _load_env_file(include_env_file)
    normalized_scope = str(scope_bundle or DEFAULT_SCOPE_BUNDLE).strip() or DEFAULT_SCOPE_BUNDLE
    normalized_email = str(expected_google_email or "").strip().lower() or _configured_expected_google_email()
    normalized_observed_google_email = str(observed_google_email or "").strip().lower()
    expected_email_present = "@" in normalized_email
    observed_email_present = "@" in normalized_observed_google_email
    observed_matches_expected = bool(
        observed_email_present
        and expected_email_present
        and normalized_observed_google_email == normalized_email
    )
    client_id = _env("EA_GOOGLE_OAUTH_CLIENT_ID")
    project_id = _env("EA_GOOGLE_OAUTH_PROJECT_ID")
    project_number = _project_number_from_client_id(client_id)
    current_source_state = _source_state()
    operator_status_issue = _operator_status_google_workspace_issue(
        current_source_state=current_source_state,
    )
    normalized_reauth_required_reason = str(reauth_required_reason or "").strip() or str(
        operator_status_issue.get("error_code") or ""
    ).strip()
    reauth_retry_required = normalized_reauth_required_reason in LIVE_REAUTH_RETRY_REASONS
    console_link = _console_deep_link(project_id)
    auth_link_template = _connect_link_template(
        scope_bundle=normalized_scope,
        expected_google_email_present=expected_email_present,
    )
    runtime_recovery = {
        "active": bool(operator_status_issue.get("cooldown_active")),
        "mode": str(operator_status_issue.get("recovery_mode") or "").strip(),
        "blocked_until": str(operator_status_issue.get("blocked_until") or "").strip(),
        "cooldown_seconds_remaining": max(int(operator_status_issue.get("cooldown_seconds_remaining") or 0), 0),
        "last_observed_at": str(operator_status_issue.get("last_observed_at") or "").strip(),
        "reason": normalized_reauth_required_reason,
        "source": str(operator_status_issue.get("source") or "").strip(),
        "raw_private_state_exposed": False,
    }

    missing = [
        f"env_{key.lower()}_missing"
        for key in REQUIRED_ENV
        if not _env(key)
    ]
    if not project_id:
        missing.append("oauth_project_id_missing")
    if not expected_email_present:
        missing.append("expected_google_email_missing")
    access_denied = str(observed_error or "").strip() == "access_denied"
    # A real Google access_denied must stay operator-actionable until a fresh retry succeeds.
    # Being listed as a tester is not enough evidence on its own because the wrong project,
    # a stale audience save, or the wrong selected account all surface as the same denial.
    if access_denied:
        if observed_email_present and expected_email_present and not observed_matches_expected:
            missing.append("oauth_account_selection_mismatch")
        else:
            missing.append(
                "oauth_access_retry_or_account_selection_required"
                if test_user_confirmed
                else "oauth_test_user_missing_or_app_unverified"
            )
    elif reauth_retry_required:
        if observed_email_present and expected_email_present and not observed_matches_expected:
            missing.append("oauth_account_selection_mismatch")
        else:
            missing.append("oauth_access_retry_or_account_selection_required")
    elif expected_email_present and not test_user_confirmed:
        missing.append("oauth_test_user_confirmation_pending")

    gcloud = {"enabled": False, "raw_gcloud_account_exposed": False, "raw_gcloud_token_exposed": False}
    workspace_api_status = {
        "probe_enabled": False,
        "status": "not_probed",
        "required": list(REQUIRED_WORKSPACE_APIS),
        "enabled_required": [],
        "missing_required": list(REQUIRED_WORKSPACE_APIS),
    }
    if probe_gcloud:
        gcloud = _gcloud_probe(
            oauth_project_id=project_id,
            oauth_project_number=project_number,
            timeout_seconds=timeout_seconds,
            runner=runner,
        )
        workspace_api_status = {
            "probe_enabled": True,
            "status": str(gcloud.get("workspace_api_probe_status") or "blocked").strip() or "blocked",
            "required": list(REQUIRED_WORKSPACE_APIS),
            "enabled_required": list(gcloud.get("enabled_required_workspace_apis") or []),
            "missing_required": list(gcloud.get("missing_required_workspace_apis") or []),
        }
        if (
            gcloud.get("enabled") is True
            and str(gcloud.get("active_project") or "").strip()
            and project_id
            and gcloud.get("active_project_matches_oauth_project") is False
        ):
            missing.append("gcloud_project_mismatch")
        if workspace_api_status["status"] == "blocked":
            if workspace_api_status["missing_required"]:
                missing.append("google_workspace_apis_missing")
            else:
                missing.append("google_workspace_api_probe_unavailable")
    missing = list(dict.fromkeys(item for item in missing if item))
    retry_only_missing = {item for item in missing if item}
    if missing and retry_only_missing.issubset(RETRY_ONLY_MISSING_SETUP):
        status = "ready_retry_required"
    elif missing and retry_only_missing.issubset(MANUAL_CONSOLE_CHECK_ONLY_MISSING_SETUP):
        status = "ready_manual_console_check"
    elif missing:
        status = "blocked_setup_required"
    elif test_user_confirmed:
        status = "pass"
    else:
        status = "ready_manual_console_check"
    setup_checklist = _setup_checklist(missing, console_link=console_link, auth_link_template=auth_link_template)
    action_required = bool(missing)
    next_action, next_action_label = _operator_next_action(missing)
    error_description_hash = _sha256(error_description)
    blocker_kind = ""
    if access_denied:
        if "oauth_account_selection_mismatch" in missing:
            blocker_kind = "oauth_account_selection_mismatch"
        elif test_user_confirmed:
            blocker_kind = "oauth_retry_or_account_selection_required"
        else:
            blocker_kind = "oauth_test_user_or_verification_required"
    return {
        "contract_name": CONTRACT_NAME,
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_google_workspace_oauth_readiness.py",
        **current_source_state,
        "status": status,
        "scope_bundle": normalized_scope,
        "observed_error": str(observed_error or "").strip(),
        "observed_error_description_present": bool(str(error_description or "").strip()),
        "observed_error_description_sha256": error_description_hash,
        "blocker_kind": blocker_kind,
        "reauth_required_reason": normalized_reauth_required_reason,
        "google_auth_platform_path": GOOGLE_AUTH_AUDIENCE_PATH,
        "console_deep_link": console_link,
        "auth_link_template": auth_link_template,
        "test_user_confirmation": {
            "confirmed": bool(test_user_confirmed),
            "evidence_type": "operator_asserted" if test_user_confirmed else "unconfirmed",
            "raw_source_exposed": False,
        },
        "expected_google_account": {
            "present": expected_email_present,
            "email_sha256": _sha256(normalized_email),
            "domain": _email_domain(normalized_email),
            "raw_expected_google_email_exposed": False,
        },
        "observed_google_account": {
            "present": observed_email_present,
            "email_sha256": _sha256(normalized_observed_google_email),
            "domain": _email_domain(normalized_observed_google_email),
            "expected_account_present": expected_email_present,
            "matches_expected": observed_matches_expected,
            "raw_observed_google_email_exposed": False,
        },
        "oauth_client": {
            "client_id_present": bool(client_id),
            "client_project_id": project_id,
            "client_project_number": project_number,
            "redirect_uri_present": bool(_env("EA_GOOGLE_OAUTH_REDIRECT_URI")),
            "client_secret_present": bool(_env("EA_GOOGLE_OAUTH_CLIENT_SECRET")),
            "state_secret_present": bool(_env("EA_GOOGLE_OAUTH_STATE_SECRET")),
            "provider_secret_present": bool(_env("EA_PROVIDER_SECRET_KEY")),
            "raw_client_id_exposed": False,
            "raw_client_secret_exposed": False,
            "raw_state_secret_exposed": False,
            "raw_provider_secret_exposed": False,
        },
        "google_workspace_apis": workspace_api_status,
        "gcloud_probe": gcloud,
        "missing_setup": missing,
        "operator_action": {
            "user_action_required": action_required,
            "instruction": _instruction_text(
                missing=missing,
                reauth_required_reason=normalized_reauth_required_reason,
                runtime_recovery=runtime_recovery,
            ),
            "next_action": next_action,
            "next_action_href": "/integrations/google",
            "next_action_label": next_action_label,
            "next_action_method": "get",
            "reauth_required_reason": normalized_reauth_required_reason,
            "runtime_recovery": runtime_recovery,
            "missing_setup": missing,
            "setup_checklist": setup_checklist,
            "console_deep_link": console_link,
            "auth_link_template": auth_link_template,
            "scope_bundle": normalized_scope,
            "expected_google_email_present": expected_email_present,
            "expected_google_email_sha256": _sha256(normalized_email),
            "expected_google_domain": _email_domain(normalized_email),
            "observed_google_email_present": observed_email_present,
            "observed_google_email_sha256": _sha256(normalized_observed_google_email),
            "observed_google_domain": _email_domain(normalized_observed_google_email),
            "observed_google_account_matches_expected": observed_matches_expected,
            "telegram_message": _telegram_message(
                missing=missing,
                console_link=console_link,
                reauth_required_reason=normalized_reauth_required_reason,
                runtime_recovery=runtime_recovery,
            ),
            "delivery_policy": "action_required_only" if action_required else "queue_only",
            "telegram_push_allowed": action_required,
            "interruption_budget": "action_required" if action_required else "none",
            "quiet_hours_respected": True,
            "non_action_progress_push_allowed": False,
            "irreversible_actions_consent_gated": True,
            "raw_private_context_exposed": False,
            "raw_expected_google_email_exposed": False,
            "raw_observed_google_email_exposed": False,
            "raw_client_id_exposed": False,
            "raw_client_secret_exposed": False,
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
            "raw_error_description_exposed": False,
        },
        "runtime_recovery": runtime_recovery,
        "telegram_notification": {
            "should_send": action_required,
            "reason": "user_action_required" if action_required else "no_operator_action_required",
            "delivery_policy": "action_required_only",
            "non_action_progress_push_allowed": False,
            "raw_private_context_exposed": False,
            "raw_expected_google_email_exposed": False,
        },
        "setup_commands": [
            "gcloud config get-value account",
            "gcloud config get-value project",
            "gcloud projects describe <oauth-project-id> --format=json",
            "python3 scripts/materialize_google_workspace_oauth_readiness.py --observed-error access_denied --observed-google-email <redacted-email> --probe-gcloud",
            "python3 scripts/verify_google_workspace_oauth_readiness.py",
        ],
        "privacy": {key: False for key in PRIVATE_FLAGS},
        "claim_boundary": (
            "does_not_prove_google_workspace_signal_ingest_until_the_requested_account_can_complete_full_workspace_oauth"
        ),
        "rules": [
            "Google OAuth test-user setup is an operator action, not an autonomous external mutation.",
            "Published receipts may include project IDs, hashes, and console paths, but not raw Google accounts, OAuth codes, tokens, or secrets.",
            "EA may retry the Full Workspace auth link only after the account is allowed as a test user or the OAuth app is published/verified, and the approved account is selected during consent.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize Google Workspace OAuth readiness.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected-google-email", default="")
    parser.add_argument("--scope-bundle", default=DEFAULT_SCOPE_BUNDLE)
    parser.add_argument("--observed-error", default="")
    parser.add_argument("--error-description", default="")
    parser.add_argument("--observed-google-email", default="")
    parser.add_argument("--test-user-confirmed", action="store_true")
    parser.add_argument("--reauth-required-reason", default="")
    parser.add_argument("--probe-gcloud", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--no-env-file", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    receipt = build_receipt(
        expected_google_email=args.expected_google_email,
        scope_bundle=args.scope_bundle,
        observed_error=args.observed_error,
        error_description=args.error_description,
        observed_google_email=args.observed_google_email,
        test_user_confirmed=bool(args.test_user_confirmed),
        reauth_required_reason=getattr(args, "reauth_required_reason", ""),
        probe_gcloud=bool(args.probe_gcloud),
        include_env_file=None if args.no_env_file else args.env_file,
        timeout_seconds=float(args.timeout_seconds or 5.0),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        temp_path = Path(handle.name)
    try:
        temp_path.chmod(OPERATOR_SAFE_RECEIPT_FILE_MODE)
    except OSError:
        pass
    temp_path.replace(output_path)
    print(json.dumps(receipt, indent=2, sort_keys=True) if args.pretty else output_path)
    return 0 if str(receipt.get("status") or "") in {"pass", "ready_manual_console_check", "ready_retry_required", "blocked_setup_required"} else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
