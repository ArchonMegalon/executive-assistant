from __future__ import annotations

import json
from types import SimpleNamespace

from scripts import materialize_google_workspace_oauth_readiness as materializer
from scripts import verify_google_workspace_oauth_readiness as verifier


def _patch_source_state(monkeypatch) -> None:
    monkeypatch.setattr(materializer, "resolve_source_state_head", lambda _root: "source-head")
    monkeypatch.setattr(materializer, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")
    monkeypatch.setattr(verifier, "resolve_source_state_head", lambda _root: "source-head")
    monkeypatch.setattr(verifier, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")


def _set_google_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "EA_GOOGLE_OAUTH_CLIENT_ID",
        "103036758852-clientid.apps.googleusercontent.com",
    )
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://myexternalbrain.com/google/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "provider-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_PROJECT_ID", "openclaw-concierge")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")


def test_expected_google_email_defaults_from_env(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    _set_google_env(monkeypatch)
    monkeypatch.setenv("EA_GOOGLE_WORKSPACE_EXPECTED_EMAIL", "work.tibor.girschele@gmail.com")

    receipt = materializer.build_receipt()

    assert receipt["expected_google_account"]["present"] is True
    assert receipt["expected_google_account"]["domain"] == "gmail.com"
    assert receipt["operator_action"]["expected_google_email_present"] is True
    assert verifier.verify_receipt_for_test(receipt) == []


def test_unconfirmed_full_workspace_auth_becomes_manual_console_action(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    _set_google_env(monkeypatch)

    receipt = materializer.build_receipt(
        expected_google_email="work.tibor.girschele@gmail.com",
        observed_error="",
        test_user_confirmed=False,
    )

    assert receipt["status"] == "ready_manual_console_check"
    assert receipt["missing_setup"] == ["oauth_test_user_confirmation_pending"]
    assert receipt["operator_action"]["user_action_required"] is True
    assert receipt["operator_action"]["delivery_policy"] == "action_required_only"
    assert receipt["operator_action"]["telegram_push_allowed"] is True
    assert receipt["telegram_notification"]["should_send"] is True
    assert receipt["operator_action"]["setup_checklist"][0]["key"] == "oauth_test_user_confirmation_pending"
    assert "Audience-page check" in receipt["operator_action"]["telegram_message"]
    assert verifier.verify_receipt_for_test(receipt) == []


def test_access_denied_receipt_is_action_required_and_redacted(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    _set_google_env(monkeypatch)

    receipt = materializer.build_receipt(
        expected_google_email="work.tibor.girschele@gmail.com",
        observed_error="access_denied",
        error_description="The app is currently being tested.",
    )

    serialized = json.dumps(receipt, sort_keys=True)
    assert receipt["status"] == "blocked_setup_required"
    assert receipt["blocker_kind"] == "oauth_test_user_or_verification_required"
    assert "oauth_test_user_missing_or_app_unverified" in receipt["missing_setup"]
    assert receipt["console_deep_link"] == "https://console.cloud.google.com/auth/audience?project=openclaw-concierge"
    assert "scope_bundle=full_workspace" in receipt["auth_link_template"]
    assert "%3Credacted-email%3E" in receipt["auth_link_template"]
    assert receipt["operator_action"]["user_action_required"] is True
    assert receipt["operator_action"]["telegram_push_allowed"] is True
    assert receipt["operator_action"]["raw_expected_google_email_exposed"] is False
    assert receipt["expected_google_account"]["email_sha256"]
    assert "work.tibor.girschele@gmail.com" not in serialized
    assert "client-secret" not in serialized
    assert "state-secret" not in serialized
    assert "provider-secret" not in serialized
    assert "The app is currently being tested." not in serialized
    assert verifier.verify_receipt_for_test(receipt) == []


def test_confirmed_test_user_receipt_passes_without_operator_push(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    _set_google_env(monkeypatch)

    receipt = materializer.build_receipt(
        expected_google_email="work.tibor.girschele@gmail.com",
        observed_error="",
        test_user_confirmed=True,
    )

    assert receipt["status"] == "pass"
    assert receipt["missing_setup"] == []
    assert receipt["operator_action"]["delivery_policy"] == "queue_only"
    assert receipt["operator_action"]["telegram_push_allowed"] is False
    assert verifier.verify_receipt_for_test(receipt) == []


def test_confirmed_test_user_access_denied_switches_to_retry_instead_of_add_tester(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    _set_google_env(monkeypatch)

    receipt = materializer.build_receipt(
        expected_google_email="work.tibor.girschele@gmail.com",
        observed_error="access_denied",
        test_user_confirmed=True,
    )

    assert receipt["status"] == "ready_retry_required"
    assert receipt["blocker_kind"] == "oauth_retry_or_account_selection_required"
    assert receipt["missing_setup"] == ["oauth_access_retry_or_account_selection_required"]
    assert receipt["operator_action"]["next_action"] == "retry_full_workspace_auth_with_approved_account"
    assert receipt["operator_action"]["next_action_label"] == "Retry Google auth"
    assert "already approved" in receipt["operator_action"]["telegram_message"]
    assert receipt["test_user_confirmation"]["confirmed"] is True
    assert receipt["test_user_confirmation"]["evidence_type"] == "operator_asserted"
    assert verifier.verify_receipt_for_test(receipt) == []


def test_live_google_reauth_reason_promotes_retry_without_manual_console_check(monkeypatch, tmp_path) -> None:
    _patch_source_state(monkeypatch)
    _set_google_env(monkeypatch)
    operator_status_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    operator_status_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "source_git_head": "source-head",
                "source_state_fingerprint": "source-fingerprint",
                "reason": "source_health_google_workspace:google_oauth_invalid_grant",
                "source_health": {
                    "present": True,
                    "status": "recovery_required",
                    "issues": [
                        {
                            "source_key": "google_workspace",
                            "error_code": "google_oauth_invalid_grant",
                            "operator_action_required": True,
                            "user_action_required": False,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(materializer, "DEFAULT_OPERATOR_STATUS", operator_status_path)

    receipt = materializer.build_receipt(
        expected_google_email="work.tibor.girschele@gmail.com",
        observed_error="",
        test_user_confirmed=False,
    )

    assert receipt["status"] == "ready_retry_required"
    assert receipt["reauth_required_reason"] == "google_oauth_invalid_grant"
    assert receipt["missing_setup"] == ["oauth_access_retry_or_account_selection_required"]
    assert receipt["operator_action"]["next_action"] == "retry_full_workspace_auth_with_approved_account"
    assert receipt["operator_action"]["next_action_label"] == "Retry Google auth"
    assert receipt["operator_action"]["reauth_required_reason"] == "google_oauth_invalid_grant"
    assert "reauthorization" in receipt["operator_action"]["telegram_message"]
    assert verifier.verify_receipt_for_test(receipt) == []


def test_access_denied_with_wrong_selected_account_promotes_account_selection_mismatch(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    _set_google_env(monkeypatch)

    receipt = materializer.build_receipt(
        expected_google_email="work.tibor.girschele@gmail.com",
        observed_google_email="archon.megalon@gmail.com",
        observed_error="access_denied",
        test_user_confirmed=True,
    )

    serialized = json.dumps(receipt, sort_keys=True)
    assert receipt["status"] == "ready_retry_required"
    assert receipt["blocker_kind"] == "oauth_account_selection_mismatch"
    assert receipt["missing_setup"] == ["oauth_account_selection_mismatch"]
    assert receipt["operator_action"]["next_action"] == "retry_full_workspace_auth_with_expected_account"
    assert receipt["operator_action"]["next_action_label"] == "Retry Google auth"
    assert receipt["observed_google_account"]["present"] is True
    assert receipt["observed_google_account"]["matches_expected"] is False
    assert receipt["observed_google_account"]["email_sha256"]
    assert receipt["operator_action"]["observed_google_account_matches_expected"] is False
    assert "different selected Google account" in receipt["operator_action"]["telegram_message"]
    assert "work.tibor.girschele@gmail.com" not in serialized
    assert "archon.megalon@gmail.com" not in serialized
    assert verifier.verify_receipt_for_test(receipt) == []


def test_main_returns_zero_for_ready_retry_required_status(monkeypatch, tmp_path) -> None:
    _patch_source_state(monkeypatch)
    _set_google_env(monkeypatch)
    output = tmp_path / "google-oauth.generated.json"
    monkeypatch.setattr(
        materializer,
        "parse_args",
        lambda: SimpleNamespace(
            output=output,
            expected_google_email="work.tibor.girschele@gmail.com",
            scope_bundle="full_workspace",
            observed_error="access_denied",
            error_description="",
            observed_google_email="work.tibor.girschele@gmail.com",
            test_user_confirmed=True,
            probe_gcloud=False,
            timeout_seconds=5.0,
            env_file=tmp_path / ".env",
            no_env_file=True,
            pretty=False,
        ),
    )

    result = materializer.main()

    assert result == 0
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["status"] == "ready_retry_required"


def test_gcloud_probe_is_sanitized_and_keeps_manual_console_step(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    _set_google_env(monkeypatch)
    monkeypatch.setattr(materializer.shutil, "which", lambda name: "/usr/bin/gcloud" if name == "gcloud" else None)

    def fake_runner(command: list[str], _timeout_seconds: float):
        if command[:4] == ["gcloud", "config", "get-value", "account"]:
            return 0, "tibor.girschele@gmail.com\n", ""
        if command[:4] == ["gcloud", "config", "get-value", "project"]:
            return 0, "openclaw-concierge\n", ""
        if command[:3] == ["gcloud", "projects", "describe"]:
            return 0, json.dumps({"projectNumber": "103036758852"}), ""
        if command[:3] == ["gcloud", "services", "list"]:
            return 0, "\n".join(materializer.REQUIRED_WORKSPACE_APIS), ""
        return 1, "", "unknown"

    receipt = materializer.build_receipt(
        expected_google_email="work.tibor.girschele@gmail.com",
        observed_error="access_denied",
        probe_gcloud=True,
        runner=fake_runner,
    )

    probe = receipt["gcloud_probe"]
    assert probe["status"] == "pass"
    assert probe["active_account_present"] is True
    assert probe["active_account_sha256"]
    assert probe["raw_gcloud_account_exposed"] is False
    assert receipt["google_workspace_apis"]["status"] == "pass"
    assert receipt["google_workspace_apis"]["missing_required"] == []
    assert probe["test_user_mutation_supported_by_gcloud_cli"] is False
    assert probe["manual_console_test_user_step_required"] is True
    assert "tibor.girschele@gmail.com" not in json.dumps(receipt, sort_keys=True)
    assert verifier.verify_receipt_for_test(receipt) == []


def test_gcloud_project_mismatch_is_promoted_into_setup_checklist(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    _set_google_env(monkeypatch)
    monkeypatch.setenv("EA_GOOGLE_OAUTH_PROJECT_ID", "propertyquarry-498318")
    monkeypatch.setenv(
        "EA_GOOGLE_OAUTH_CLIENT_ID",
        "95627800296-clientid.apps.googleusercontent.com",
    )
    monkeypatch.setattr(materializer.shutil, "which", lambda name: "/usr/bin/gcloud" if name == "gcloud" else None)

    def fake_runner(command: list[str], _timeout_seconds: float):
        if command[:4] == ["gcloud", "config", "get-value", "account"]:
            return 0, "tibor.girschele@gmail.com\n", ""
        if command[:4] == ["gcloud", "config", "get-value", "project"]:
            return 0, "openclaw-concierge\n", ""
        if command[:3] == ["gcloud", "projects", "describe"]:
            return 0, json.dumps({"projectNumber": "95627800296"}), ""
        if command[:3] == ["gcloud", "services", "list"]:
            return 0, "\n".join(materializer.REQUIRED_WORKSPACE_APIS), ""
        return 1, "", "unknown"

    receipt = materializer.build_receipt(
        expected_google_email="work.tibor.girschele@gmail.com",
        observed_error="access_denied",
        probe_gcloud=True,
        runner=fake_runner,
    )

    assert receipt["status"] == "blocked_setup_required"
    assert "oauth_test_user_missing_or_app_unverified" in receipt["missing_setup"]
    assert "gcloud_project_mismatch" in receipt["missing_setup"]
    assert "OAuth project" in receipt["operator_action"]["instruction"]
    assert "different OAuth project" in receipt["operator_action"]["telegram_message"]
    checklist_keys = {row["key"] for row in receipt["operator_action"]["setup_checklist"]}
    assert "gcloud_project_mismatch" in checklist_keys
    assert verifier.verify_receipt_for_test(receipt) == []


def test_missing_workspace_apis_block_full_workspace_readiness(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    _set_google_env(monkeypatch)
    monkeypatch.setattr(materializer.shutil, "which", lambda name: "/usr/bin/gcloud" if name == "gcloud" else None)

    def fake_runner(command: list[str], _timeout_seconds: float):
        if command[:4] == ["gcloud", "config", "get-value", "account"]:
            return 0, "tibor.girschele@gmail.com\n", ""
        if command[:4] == ["gcloud", "config", "get-value", "project"]:
            return 0, "openclaw-concierge\n", ""
        if command[:3] == ["gcloud", "projects", "describe"]:
            return 0, json.dumps({"projectNumber": "103036758852"}), ""
        if command[:3] == ["gcloud", "services", "list"]:
            return 0, "gmail.googleapis.com\n", ""
        return 1, "", "unknown"

    receipt = materializer.build_receipt(
        expected_google_email="work.tibor.girschele@gmail.com",
        test_user_confirmed=True,
        probe_gcloud=True,
        runner=fake_runner,
    )

    assert receipt["status"] == "blocked_setup_required"
    assert "google_workspace_apis_missing" in receipt["missing_setup"]
    assert receipt["google_workspace_apis"]["status"] == "blocked"
    assert set(receipt["google_workspace_apis"]["missing_required"]) == {
        "calendar-json.googleapis.com",
        "people.googleapis.com",
        "drive.googleapis.com",
    }
    checklist_keys = {row["key"] for row in receipt["operator_action"]["setup_checklist"]}
    assert "google_workspace_apis_missing" in checklist_keys
    assert verifier.verify_receipt_for_test(receipt) == []


def test_verifier_rejects_private_google_fields(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    _set_google_env(monkeypatch)
    receipt = materializer.build_receipt(
        expected_google_email="work.tibor.girschele@gmail.com",
        observed_error="access_denied",
    )
    receipt["privacy"]["raw_expected_google_email_exposed"] = True
    receipt["operator_action"]["raw_client_secret_exposed"] = True

    issues = verifier.verify_receipt_for_test(receipt)

    assert "privacy.raw_expected_google_email_exposed must be false" in issues
    assert "operator_action.raw_client_secret_exposed must be false" in issues
