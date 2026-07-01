from __future__ import annotations

import json

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
