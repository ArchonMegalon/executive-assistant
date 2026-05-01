from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client(*, principal_id: str, operator: bool = False) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    if operator:
        os.environ["EA_API_TOKEN"] = "test-token"
        os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
        os.environ["EA_OPERATOR_PRINCIPAL_IDS"] = principal_id
    else:
        os.environ["EA_API_TOKEN"] = ""
        os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
        os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    if operator:
        client.headers.update({"Authorization": "Bearer test-token"})
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def _assert_no_product_drift(text: str) -> None:
    lower = text.lower()
    assert "chummer" not in lower
    assert "gm_creator_ops" not in lower
    assert "gm / creator / campaign ops" not in lower
    assert "campaign or community ops" not in lower


def _internal_links(html: str) -> list[str]:
    refs = sorted(set(re.findall(r'href="([^"]+)"', html)))
    return [ref for ref in refs if ref.startswith("/") and not ref.startswith("//")]


def test_onemin_browseract_failure_code_detects_invalid_credentials() -> None:
    from app.api.routes import providers as providers_route

    assert providers_route._onemin_browseract_failure_code(
        "ui_lane_failure:onemin_billing_usage:invalid_credentials"
    ) == "invalid_credentials"
    assert providers_route._onemin_browseract_failure_code(
        "The email or password you entered is incorrect. Please try again."
    ) == "invalid_credentials"


def test_onemin_browseract_failure_code_detects_onemin_auth_cors_block_as_challenge() -> None:
    from app.api.routes import providers as providers_route

    assert providers_route._onemin_browseract_failure_code(
        "template_worker_failed: Submit Login:auth_request_failed:console:Access to XMLHttpRequest at "
        "'https://api.1min.ai/auth/login' from origin 'https://app.1min.ai' has been blocked by "
        "CORS policy: No 'Access-Control-Allow-Origin' header is present on the requested resource."
    ) == "challenge_required"


def test_onemin_browseract_failure_code_detects_onemin_auth_csp_block_as_challenge() -> None:
    from app.api.routes import providers as providers_route

    assert providers_route._onemin_browseract_failure_code(
        "template_worker_failed: Submit Login:auth_request_failed:console:[Report Only] Refused to connect to "
        "'https://api.1min.ai/auth/login' because it violates the following Content Security Policy directive: "
        "\"connect-src 'none'\"."
    ) == "challenge_required"


def test_provider_bindings_are_principal_scoped_and_support_probe_updates() -> None:
    owner = _client(principal_id="exec-1")
    created = owner.post(
        "/v1/providers/bindings",
        json={
            "provider_key": "browseract",
            "status": "enabled",
            "priority": 15,
            "scope_json": {"allowed_tools": ["browseract.extract_account_inventory"]},
            "probe_state": "ready",
            "probe_details_json": {"last_check": "unit"},
        },
    )
    assert created.status_code == 200
    created_body = created.json()
    assert created_body["principal_id"] == "exec-1"
    assert created_body["provider_key"] == "browseract"
    assert created_body["probe_state"] == "ready"
    binding_id = created_body["binding_id"]

    listed = owner.get("/v1/providers/bindings")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) >= 1
    assert any(row["binding_id"] == binding_id for row in rows)

    updated_probe = owner.post(
        f"/v1/providers/bindings/{binding_id}/probe",
        json={"probe_state": "degraded", "probe_details_json": {"reason": "quota_depleted"}},
    )
    assert updated_probe.status_code == 200
    assert updated_probe.json()["probe_state"] == "degraded"
    assert updated_probe.json()["probe_details_json"]["reason"] == "quota_depleted"

    state = owner.get("/v1/providers/states/browseract")
    assert state.status_code == 200
    state_body = state.json()
    assert state_body["provider_key"] == "browseract"
    assert state_body["binding_id"] == binding_id
    assert state_body["health_state"] == "degraded"

    denied = owner.get(
        f"/v1/providers/bindings/{binding_id}",
        headers={"X-EA-Principal-ID": "exec-2"},
    )
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "provider_binding_not_found"


def test_google_oauth_routes_create_and_disconnect_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://ea.example/v1/providers/google/oauth/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "provider-secret-key")

    owner = _client(principal_id="exec-google")

    started = owner.post("/v1/providers/google/oauth/start", json={"scope_bundle": "send"})
    assert started.status_code == 200
    started_body = started.json()
    assert started_body["provider_key"] == "google_gmail"
    assert "https://accounts.google.com/o/oauth2/v2/auth" in started_body["auth_url"]
    assert "https://www.googleapis.com/auth/gmail.send" in started_body["requested_scopes"]

    from app.services import google_oauth as google_service

    monkeypatch.setattr(
        google_service,
        "_exchange_google_code_for_tokens",
        lambda **kwargs: {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "scope": "openid email profile https://www.googleapis.com/auth/gmail.send",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        google_service,
        "_fetch_google_userinfo",
        lambda access_token: {
            "sub": "google-sub-123",
            "email": "runner@gmail.example",
            "hd": "gmail.example",
        },
    )

    callback = owner.get(
        "/v1/providers/google/oauth/callback",
        params={"code": "code-123", "state": started_body["state"]},
    )
    assert callback.status_code == 200
    callback_body = callback.json()
    assert callback_body["principal_id"] == "exec-google"
    assert callback_body["google_email"] == "runner@gmail.example"
    assert callback_body["consent_stage"] == "send"
    assert callback_body["token_status"] == "active"
    assert callback_body["connector_binding_id"]

    accounts = owner.get("/v1/providers/google/accounts")
    assert accounts.status_code == 200
    rows = accounts.json()
    assert len(rows) == 1
    assert rows[0]["google_subject"] == "google-sub-123"
    assert rows[0]["granted_scopes"] == ["email", "https://www.googleapis.com/auth/gmail.send", "openid", "profile"]

    monkeypatch.setattr(
        google_service,
        "_refresh_google_access_token",
        lambda **kwargs: {
            "access_token": "fresh-access-token",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        google_service,
        "_gmail_send_message",
        lambda **kwargs: "gmail-message-123",
    )

    smoke = owner.post("/v1/providers/google/gmail/smoke-test", json={})
    assert smoke.status_code == 200
    smoke_body = smoke.json()
    assert smoke_body["sender_email"] == "runner@gmail.example"
    assert smoke_body["recipient_email"] == "runner@gmail.example"
    assert smoke_body["gmail_message_id"] == "gmail-message-123"
    assert smoke_body["rfc822_message_id"].startswith("<ea-smoke-")

    disconnected = owner.post("/v1/providers/google/oauth/disconnect", json={})
    assert disconnected.status_code == 200
    disconnected_body = disconnected.json()
    assert disconnected_body["token_status"] == "revoked"
    assert disconnected_body["reauth_required_reason"] == "disconnected_by_operator"


def test_onboarding_google_start_reports_missing_oauth_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EA_GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("EA_GOOGLE_OAUTH_REDIRECT_URI", raising=False)
    monkeypatch.delenv("EA_GOOGLE_OAUTH_STATE_SECRET", raising=False)
    monkeypatch.delenv("EA_PROVIDER_SECRET_KEY", raising=False)
    owner = _client(principal_id="exec-onboarding-missing")

    owner.post(
        "/v1/onboarding/start",
        json={
            "workspace_name": "No Config",
            "workspace_mode": "personal",
            "region": "AT",
            "language": "en",
            "timezone": "Europe/Vienna",
            "selected_channels": ["google"],
        },
    )

    google = owner.post("/v1/onboarding/google/start", json={"scope_bundle": "core"})
    assert google.status_code == 200
    body = google.json()
    google_start = dict(body["google_start"])
    assert google_start["ready"] is False
    assert google_start["error"] == "google_oauth_client_id_missing"
    assert "Set EA_GOOGLE_OAUTH_CLIENT_ID and EA_GOOGLE_OAUTH_CLIENT_SECRET." in google_start["detail"]
    assert body["channels"]["google"]["status"] == "credentials_missing"


def test_onboarding_routes_persist_workspace_and_honest_channel_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://ea.example/v1/providers/google/oauth/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "provider-secret-key")

    owner = _client(principal_id="exec-onboarding")

    started = owner.post(
        "/v1/onboarding/start",
        json={
            "workspace_name": "Ops Desk",
            "workspace_mode": "team",
            "region": "AT",
            "language": "en",
            "timezone": "Europe/Vienna",
            "selected_channels": ["google", "telegram", "whatsapp"],
        },
    )
    assert started.status_code == 200
    started_body = started.json()
    assert started_body["status"] == "started"
    assert started_body["workspace"]["name"] == "Ops Desk"
    assert started_body["selected_channels"] == ["google", "telegram", "whatsapp"]

    google = owner.post("/v1/onboarding/google/start", json={"scope_bundle": "core"})
    assert google.status_code == 200
    google_body = google.json()
    assert google_body["google_start"]["ready"] is True
    assert google_body["google_start"]["requested_bundle"] == "core"
    assert google_body["google_start"]["oauth_bundle"] == "core"
    assert "https://www.googleapis.com/auth/gmail.metadata" in google_body["google_start"]["requested_scopes"]
    assert "https://www.googleapis.com/auth/calendar.readonly" in google_body["google_start"]["requested_scopes"]
    assert "https://www.googleapis.com/auth/contacts.readonly" in google_body["google_start"]["requested_scopes"]
    assert google_body["google_start"]["bundle_label"] == "Google Core"
    assert google_body["channels"]["google"]["status"] == "ready_to_connect"
    google_query = urllib.parse.parse_qs(urllib.parse.urlparse(google_body["google_start"]["auth_url"]).query)
    assert google_query["redirect_uri"][0] == "https://ea.example/v1/providers/google/oauth/callback"

    telegram = owner.post(
        "/v1/onboarding/telegram/start",
        json={
            "telegram_ref": "@opsdesk",
            "history_mode": "future_only",
            "assistant_surfaces": ["dm", "group"],
        },
    )
    assert telegram.status_code == 200
    telegram_body = telegram.json()
    assert telegram_body["telegram_start"]["status"] == "guided_manual"
    assert telegram_body["channels"]["telegram"]["status"] == "guided_manual"

    whatsapp = owner.post(
        "/v1/onboarding/whatsapp/import-export",
        json={
            "export_label": "March export",
            "selected_chat_labels": ["Family", "Ops"],
            "include_media": True,
        },
    )
    assert whatsapp.status_code == 200
    whatsapp_body = whatsapp.json()
    assert whatsapp_body["whatsapp_export"]["status"] == "export_planned"
    assert whatsapp_body["channels"]["whatsapp"]["status"] == "export_planned"

    finalized = owner.post(
        "/v1/onboarding/finalize",
        json={
            "retention_mode": "metadata_first",
            "metadata_only_channels": ["telegram"],
            "allow_drafts": True,
            "allow_action_suggestions": True,
            "allow_auto_briefs": True,
            "auto_brief_cadence": "weekdays_morning",
            "auto_brief_delivery_time_local": "07:30",
            "auto_brief_quiet_hours_start": "21:00",
            "auto_brief_quiet_hours_end": "06:30",
            "auto_brief_recipient_email": "briefs@example.com",
        },
    )
    assert finalized.status_code == 200
    finalized_body = finalized.json()
    assert finalized_body["status"] == "ready_for_brief"
    assert finalized_body["privacy"]["retention_mode"] == "metadata_first"
    assert finalized_body["privacy"]["metadata_only_channels"] == ["telegram"]
    assert finalized_body["brief_preview"]["headline"].startswith("Ops Desk")
    assert finalized_body["brief_preview"]["top_themes"]
    assert finalized_body["brief_preview"]["first_brief_preview"]
    assert finalized_body["delivery_preferences"]["morning_memo"]["cadence"] == "weekdays_morning"
    assert finalized_body["delivery_preferences"]["morning_memo"]["delivery_time_local"] == "07:30"
    assert finalized_body["delivery_preferences"]["morning_memo"]["quiet_hours_start"] == "21:00"
    assert finalized_body["delivery_preferences"]["morning_memo"]["quiet_hours_end"] == "06:30"
    assert finalized_body["delivery_preferences"]["morning_memo"]["recipient_email"] == "briefs@example.com"
    assert finalized_body["delivery_preferences"]["morning_memo"]["resolved_recipient_email"] == "briefs@example.com"
    stored_preferences = owner.app.state.container.memory_runtime.list_delivery_preferences(  # type: ignore[attr-defined]
        principal_id="exec-onboarding",
        limit=10,
    )
    assert len(stored_preferences) == 1
    assert stored_preferences[0].status == "active"
    assert stored_preferences[0].format_json["schedule_kind"] == "morning_memo"
    assert stored_preferences[0].quiet_hours_json["delivery_time_local"] == "07:30"

    status = owner.get("/v1/onboarding/status")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["workspace"]["mode"] == "team"
    assert status_body["channels"]["google"]["status"] == "ready_to_connect"
    assert status_body["channels"]["telegram"]["status"] == "guided_manual"
    assert status_body["channels"]["whatsapp"]["status"] == "export_planned"
    assert status_body["next_step"] == "Complete Google Core consent to unlock the first real connected channel."
    assert status_body["storage_posture"]["source_of_truth"] == "EA Postgres"
    assert status_body["delivery_preferences"]["morning_memo"]["recipient_email"] == "briefs@example.com"
    assert status_body["brief_preview"]["first_brief"] == status_body["brief_preview"]["first_brief_preview"]


def test_onboarding_google_callback_returns_api_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://ea.example/v1/onboarding/google/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "provider-secret-key")

    owner = _client(principal_id="exec-onboarding-callback")

    started = owner.post(
        "/v1/onboarding/google/start",
        json={"scope_bundle": "full_workspace"},
    )
    assert started.status_code == 200
    started_body = started.json()
    assert started_body["google_start"]["ready"] is True
    state = urllib.parse.parse_qs(urllib.parse.urlparse(started_body["google_start"]["auth_url"]).query)["state"][0]

    from app.services import google_oauth as google_service

    monkeypatch.setattr(
        google_service,
        "_exchange_google_code_for_tokens",
        lambda **kwargs: {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "scope": "openid email profile https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.metadata https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/contacts.readonly",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        google_service,
        "_fetch_google_userinfo",
        lambda access_token: {
            "sub": "google-sub-onboarding",
            "email": "onboarding@gmail.example",
            "hd": "gmail.example",
        },
    )

    callback = owner.get(
        "/v1/onboarding/google/callback",
        params={"code": "code-123", "state": state},
    )
    assert callback.status_code == 200
    callback_body = callback.json()
    assert callback_body["provider_key"] == "google_gmail"
    assert callback_body["principal_id"] == "exec-onboarding-callback"
    assert callback_body["google_email"] == "onboarding@gmail.example"
    assert callback_body["connector_binding_id"]
    assert "https://www.googleapis.com/auth/gmail.metadata" in callback_body["granted_scopes"]
    assert "https://www.googleapis.com/auth/calendar.readonly" in callback_body["granted_scopes"]


def test_browser_landing_exposes_google_onboarding_and_html_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://ea.example/v1/providers/google/oauth/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "provider-secret-key")

    owner = _client(principal_id="exec-browser")

    landing = owner.get("/")
    assert landing.status_code == 200
    _assert_no_product_drift(landing.text)
    assert "Wake up to a clear brief, not a wall of inbox noise." in landing.text
    assert "Create personal workspace" in landing.text
    assert "Nothing sends without your review." in landing.text
    for href in _internal_links(landing.text):
        resolved = owner.get(href, follow_redirects=False)
        assert resolved.status_code in {200, 303, 307}, href

    setup = owner.get("/register")
    assert setup.status_code == 200
    _assert_no_product_drift(setup.text)
    assert "Start a workspace that shows the first useful loop." in setup.text
    assert "Workspace shape" in setup.text
    assert "Google Core" in setup.text

    sign_in = owner.get("/sign-in")
    assert sign_in.status_code == 200
    _assert_no_product_drift(sign_in.text)
    assert "Sign in if you already have workspace access." in sign_in.text
    assert "New customers should create a personal workspace first." in sign_in.text

    legacy_setup = owner.get("/setup", follow_redirects=False)
    assert legacy_setup.status_code == 307
    assert legacy_setup.headers["location"] == "/register"

    privacy = owner.get("/security")
    assert privacy.status_code == 200
    _assert_no_product_drift(privacy.text)
    assert "Trust should show up in the product before it shows up on a policy page." in privacy.text

    for path in ("/product", "/integrations", "/pricing", "/docs"):
        page = owner.get(path)
        assert page.status_code == 200
        _assert_no_product_drift(page.text)

    legacy_privacy = owner.get("/privacy", follow_redirects=False)
    assert legacy_privacy.status_code == 307
    assert legacy_privacy.headers["location"] == "/security"

    started = owner.post(
        "/google/connect",
        data={"scope_bundle": "send", "api_token": ""},
        follow_redirects=False,
    )
    assert started.status_code == 303
    location = started.headers["location"]
    assert "https://accounts.google.com/o/oauth2/v2/auth" in location
    parsed = urllib.parse.urlparse(location)
    query = urllib.parse.parse_qs(parsed.query)
    state = query["state"][0]
    assert query["redirect_uri"][0] == "https://ea.example/v1/providers/google/oauth/callback"

    from app.services import google_oauth as google_service

    monkeypatch.setattr(
        google_service,
        "_exchange_google_code_for_tokens",
        lambda **kwargs: {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "scope": "openid email profile https://www.googleapis.com/auth/gmail.send",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        google_service,
        "_fetch_google_userinfo",
        lambda access_token: {
            "sub": "google-sub-browser",
            "email": "browser@gmail.example",
            "hd": "gmail.example",
        },
    )

    callback = owner.get("/google/callback", params={"code": "code-123", "state": state})
    assert callback.status_code == 200
    assert "Google is connected. The next step is to use it." in callback.text
    assert "browser@gmail.example" in callback.text
    assert "gmail.send" in callback.text


def test_browser_landing_uses_cloudflare_access_identity_for_gmail_onboarding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://ea.example/v1/providers/google/oauth/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "provider-secret-key")
    monkeypatch.setenv("EA_CF_ACCESS_TEAM_DOMAIN", "girschele.cloudflareaccess.com")
    monkeypatch.setenv("EA_CF_ACCESS_AUD", "aud-123")

    from app.api import dependencies as deps
    from app.services.cloudflare_access import CloudflareAccessIdentity

    monkeypatch.setattr(
        deps,
        "resolve_access_identity",
        lambda **kwargs: CloudflareAccessIdentity(
            principal_id="cf-email:browser@gmail.com",
            email="browser@gmail.com",
            subject="subject-browser",
            display_name="Browser Gmail",
            issuer="https://girschele.cloudflareaccess.com",
            idp_name="google",
            audiences=("aud-123",),
            claims={"email": "browser@gmail.com", "sub": "subject-browser"},
        ),
    )

    owner = _client(principal_id="ignored-browser")

    landing = owner.get("/")
    assert landing.status_code == 200
    assert "Open workspace" in landing.text
    assert "Wake up to a clear brief, not a wall of inbox noise." in landing.text
    assert "browser@gmail.com" not in landing.text

    started = owner.post(
        "/google/connect",
        data={"scope_bundle": "send"},
        follow_redirects=False,
    )
    assert started.status_code == 303
    parsed = urllib.parse.urlparse(started.headers["location"])
    query = urllib.parse.parse_qs(parsed.query)
    assert query["redirect_uri"][0] == "https://ea.example/v1/providers/google/oauth/callback"
    state = query["state"][0]

    from app.services import google_oauth as google_service

    monkeypatch.setattr(
        google_service,
        "_exchange_google_code_for_tokens",
        lambda **kwargs: {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "scope": "openid email profile https://www.googleapis.com/auth/gmail.send",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        google_service,
        "_fetch_google_userinfo",
        lambda access_token: {
            "sub": "google-sub-browser",
            "email": "browser@gmail.com",
            "hd": "gmail.com",
        },
    )

    callback = owner.get("/google/callback", params={"code": "code-123", "state": state})
    assert callback.status_code == 200
    assert "Google is connected. The next step is to use it." in callback.text
    assert "browser@gmail.com" in callback.text
    assert "cf-email:browser@gmail.com" not in callback.text


def test_browser_shell_routes_and_nav_links_resolve() -> None:
    user = _client(principal_id="exec-browser-shell")
    operator = _client(principal_id="operator-browser-shell", operator=True)

    for path in (
        "/app/today",
        "/app/briefing",
        "/app/inbox",
        "/app/follow-ups",
        "/app/memory",
        "/app/contacts",
        "/app/channels",
        "/app/automations",
        "/app/activity",
        "/app/settings",
    ):
        page = user.get(path)
        assert page.status_code == 200
        _assert_no_product_drift(page.text)
        for href in _internal_links(page.text):
            resolved = user.get(href, follow_redirects=False)
            assert resolved.status_code in {200, 303, 307}, (path, href)

    for path in (
        "/admin/office",
        "/admin/policies",
        "/admin/providers",
        "/admin/audit-trail",
        "/admin/operators",
        "/admin/community",
        "/admin/api",
    ):
        page = operator.get(path)
        assert page.status_code == 200
        _assert_no_product_drift(page.text)
        for href in _internal_links(page.text):
            resolved = operator.get(href, follow_redirects=False)
            assert resolved.status_code in {200, 303, 307}, (path, href)


def test_provider_bindings_reject_cross_principal_query_scope() -> None:
    owner = _client(principal_id="exec-1", operator=True)
    response = owner.get("/v1/providers/bindings?principal_id=exec-2")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "principal_scope_mismatch"


def test_onemin_probe_all_endpoint_returns_slot_results(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    from app.services import responses_upstream as upstream

    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "probe-primary")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "probe-deleted")
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {
                        "secret_sha256": hashlib.sha256(b"probe-primary").hexdigest(),
                        "owner_email": "probe@example.com",
                    }
                ]
            }
        ),
    )

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        if headers["API-KEY"] == "probe-primary":
            return (
                200,
                {
                    "aiRecord": {
                        "model": "gpt-4.1",
                        "aiRecordDetail": {"resultObject": "OK"},
                    }
                },
            )
        return (401, {"errorCode": "HTTP_EXCEPTION", "message": "API Key has been deleted"})

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    response = owner.post("/v1/providers/onemin/probe-all", json={"include_reserve": True})
    assert response.status_code == 200
    body = response.json()
    assert body["provider_key"] == "onemin"
    assert body["result_counts"] == {"ok": 1, "revoked": 1}
    primary = next(slot for slot in body["slots"] if slot["account_name"] == "ONEMIN_AI_API_KEY")
    assert primary["owner_email"] == "probe@example.com"
    assert primary["result"] == "ok"


def test_onemin_billing_refresh_executes_browseract_tools_and_maps_owner_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {
                        "account_name": "ONEMIN_AI_API_KEY",
                        "owner_email": "owner@example.com",
                    }
                ]
            }
        ),
    )

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "owner@example.com",
            "scope_json": {"scopes": ["billing", "inventory"]},
            "auth_metadata_json": {
                "onemin_billing_usage_run_url": "https://browseract.example/run/billing",
                "onemin_members_run_url": "https://browseract.example/run/members",
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200
    binding_id = created.json()["binding_id"]

    container = owner.app.state.container
    container.tool_execution._browseract_onemin_billing_usage = lambda **_: {
        "remaining_credits": "12345",
        "max_credits": "20000",
        "next_topup_at": "2026-03-31T00:00:00Z",
        "topup_amount": "20000",
        "used_percent": "38.3",
    }
    container.tool_execution._browseract_onemin_member_reconciliation = lambda **_: {
        "members": [
            {
                "email": "owner@example.com",
                "status": "active",
                "credit_limit": "5000",
            }
        ]
    }

    response = owner.post(
        "/v1/providers/onemin/billing-refresh",
        json={"include_members": True, "include_provider_api": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider_key"] == "onemin"
    assert body["connector_binding_count"] == 1
    assert body["billing_refresh_count"] == 1
    assert body["member_reconciliation_count"] == 1
    assert body["errors"] == []
    assert body["billing_results"][0]["binding_id"] == binding_id
    assert body["billing_results"][0]["account_label"] == "ONEMIN_AI_API_KEY"
    assert body["billing_results"][0]["next_topup_at"] == "2026-03-31T00:00:00Z"
    assert body["member_results"][0]["account_label"] == "ONEMIN_AI_API_KEY"
    assert body["member_results"][0]["matched_owner_slots"] == 1


def test_onemin_billing_refresh_forwards_default_browser_proxy_settings_to_browseract_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv("EA_UI_BROWSER_PROXY_SERVER", "http://ea-fastestvpn-proxy:3128")
    monkeypatch.setenv("EA_UI_BROWSER_PROXY_USERNAME", "vpn-user")
    monkeypatch.setenv("EA_UI_BROWSER_PROXY_PASSWORD", "vpn-pass")
    monkeypatch.setenv("EA_UI_BROWSER_PROXY_BYPASS", "localhost,127.0.0.1,ea-api")

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {
                "onemin_account_names": ["ONEMIN_AI_API_KEY"],
                "onemin_billing_usage_run_url": "https://browseract.example/run/billing",
                "onemin_members_run_url": "https://browseract.example/run/members",
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    from app.api.routes import providers as providers_route

    monkeypatch.setattr(owner.app.state.container.onemin_manager, "begin_billing_refresh", lambda: (True, 0.0, ""))
    monkeypatch.setattr(owner.app.state.container.onemin_manager, "finish_billing_refresh", lambda: None)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", lambda **_: ([], [], [], 0, 0, False))

    observed: list[tuple[str, dict[str, object]]] = []

    def fake_invoke_browseract_tool(**kwargs):
        tool_name = str(kwargs.get("tool_name") or "")
        payload_json = dict(kwargs.get("payload_json") or {})
        observed.append((tool_name, payload_json))
        if tool_name == "browseract.onemin_billing_usage":
            return {"refresh_backend": "browseract", "remaining_credits": "12345"}
        return {"refresh_backend": "browseract", "matched_owner_slots": 1}

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)

    response = owner.post(
        "/v1/providers/onemin/billing-refresh",
        json={"include_members": True, "include_provider_api": False},
    )
    assert response.status_code == 200
    assert [tool_name for tool_name, _payload in observed] == [
        "browseract.onemin_billing_usage",
        "browseract.onemin_member_reconciliation",
    ]
    for _tool_name, payload_json in observed:
        assert payload_json["browser_proxy_server"] == "http://ea-fastestvpn-proxy:3128"
        assert payload_json["browser_proxy_username"] == "vpn-user"
        assert payload_json["browser_proxy_password"] == "vpn-pass"
        assert payload_json["browser_proxy_bypass"] == "localhost,127.0.0.1,ea-api"


def test_onemin_billing_refresh_prefers_binding_browser_proxy_settings_over_env_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv("EA_UI_BROWSER_PROXY_SERVER", "http://ea-fastestvpn-proxy:3128")
    monkeypatch.setenv("EA_UI_BROWSER_PROXY_USERNAME", "vpn-user")
    monkeypatch.setenv("EA_UI_BROWSER_PROXY_PASSWORD", "vpn-pass")
    monkeypatch.setenv("EA_UI_BROWSER_PROXY_BYPASS", "localhost,127.0.0.1,ea-api")

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {
                "onemin_account_names": ["ONEMIN_AI_API_KEY"],
                "onemin_billing_usage_run_url": "https://browseract.example/run/billing",
                "proxy_server": "http://binding-proxy:8080",
                "browser_proxy_username": "binding-user",
                "browser_proxy_password": "binding-pass",
                "proxy_bypass": "localhost,internal.service",
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    from app.api.routes import providers as providers_route

    monkeypatch.setattr(owner.app.state.container.onemin_manager, "begin_billing_refresh", lambda: (True, 0.0, ""))
    monkeypatch.setattr(owner.app.state.container.onemin_manager, "finish_billing_refresh", lambda: None)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", lambda **_: ([], [], [], 0, 0, False))

    observed: dict[str, object] = {}

    def fake_invoke_browseract_tool(**kwargs):
        payload_json = dict(kwargs.get("payload_json") or {})
        observed.update(payload_json)
        return {"refresh_backend": "browseract", "remaining_credits": "12345"}

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)

    response = owner.post(
        "/v1/providers/onemin/billing-refresh",
        json={"include_members": False, "include_provider_api": False},
    )
    assert response.status_code == 200
    assert observed["browser_proxy_server"] == "http://binding-proxy:8080"
    assert observed["browser_proxy_username"] == "binding-user"
    assert observed["browser_proxy_password"] == "binding-pass"
    assert observed["browser_proxy_bypass"] == "localhost,internal.service"


def test_onemin_billing_refresh_rotates_fastestvpn_proxy_and_retries_browseract_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv("EA_UI_BROWSER_PROXY_SERVER", "http://ea-fastestvpn-proxy:3128")

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {
                "onemin_account_names": ["ONEMIN_AI_API_KEY"],
                "onemin_billing_usage_run_url": "https://browseract.example/run/billing",
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    from app.api.routes import providers as providers_route

    monkeypatch.setattr(owner.app.state.container.onemin_manager, "begin_billing_refresh", lambda: (True, 0.0, ""))
    monkeypatch.setattr(owner.app.state.container.onemin_manager, "finish_billing_refresh", lambda: None)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", lambda **_: ([], [], [], 0, 0, False))

    calls = 0
    rotations: list[str] = []

    def fake_invoke_browseract_tool(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise providers_route.ToolExecutionError("ui_service_worker_failed:onemin_billing_usage:auth_request_failed")
        return {"refresh_backend": "browseract", "remaining_credits": "12345"}

    def fake_rotate_fastestvpn_proxy(*, reason: str):
        rotations.append(reason)
        return {
            "reason": reason,
            "returncode": 0,
            "duration_seconds": 0.25,
            "stdout": "rotated",
            "stderr": "",
        }

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)
    monkeypatch.setattr(providers_route, "_rotate_fastestvpn_proxy", fake_rotate_fastestvpn_proxy)

    response = owner.post(
        "/v1/providers/onemin/billing-refresh",
        json={"include_members": False, "include_provider_api": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert calls == 2
    assert len(rotations) == 1
    assert body["billing_refresh_count"] == 1
    assert body["errors"] == []
    assert body["browseract_proxy_rotation_count"] == 1
    assert body["browseract_proxy_recovered_labels"] == ["ONEMIN_AI_API_KEY"]
    assert "FastestVPN proxy rotated 1 time" in body["note"]


def test_onemin_billing_refresh_uses_direct_api_when_no_browseract_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {
                        "account_name": "ONEMIN_AI_API_KEY",
                        "owner_email": "owner@example.com",
                    }
                ]
            }
        ),
    )

    from app.api.routes import providers as providers_route

    monkeypatch.setattr(
        providers_route,
        "_refresh_onemin_via_provider_api",
        lambda **_: (
            [
                {
                    "refresh_backend": "onemin_api",
                    "account_label": "ONEMIN_AI_API_KEY",
                    "owner_email": "owner@example.com",
                    "next_topup_at": "2026-03-19T22:00:00Z",
                    "topup_amount": 15000.0,
                    "basis": "actual_provider_api",
                }
            ],
            [
                {
                    "refresh_backend": "onemin_api",
                    "account_label": "ONEMIN_AI_API_KEY",
                    "owner_email": "owner@example.com",
                    "matched_owner_slots": 1,
                    "basis": "actual_provider_api",
                }
            ],
            [],
            1,
            0,
            False,
        ),
    )

    response = owner.post(
        "/v1/providers/onemin/billing-refresh",
        json={"include_members": True, "provider_api_all_accounts": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider_key"] == "onemin"
    assert body["connector_binding_count"] == 0
    assert body["api_account_count"] == 1
    assert body["billing_refresh_count"] == 1
    assert body["member_reconciliation_count"] == 1
    assert body["api_billing_refresh_count"] == 1
    assert body["api_member_reconciliation_count"] == 1
    assert body["billing_results"][0]["refresh_backend"] == "onemin_api"
    assert body["member_results"][0]["refresh_backend"] == "onemin_api"
    assert "direct 1min API" in body["note"]


def test_onemin_billing_refresh_forwards_full_provider_api_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {
                        "account_name": "ONEMIN_AI_API_KEY",
                        "owner_email": "owner@example.com",
                    }
                ]
            }
        ),
    )

    from app.api.routes import providers as providers_route

    observed: dict[str, object] = {}

    def fake_refresh(**kwargs):
        observed.update(kwargs)
        return ([], [], [], 1, 0, False)

    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", fake_refresh)

    response = owner.post(
        "/v1/providers/onemin/billing-refresh",
        json={
            "provider_api_all_accounts": True,
            "provider_api_continue_on_rate_limit": True,
        },
    )
    assert response.status_code == 200
    assert observed["include_members"] is True
    assert observed["all_accounts"] is False
    assert observed["account_labels"] == {"ONEMIN_AI_API_KEY"}
    assert observed["continue_on_rate_limit"] is True


def test_onemin_billing_refresh_is_throttled_to_one_run_per_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    from app.api.routes import providers as providers_route
    monkeypatch.setattr(
        providers_route.upstream,
        "onemin_owner_rows",
        lambda: (
            {
                "account_name": "ONEMIN_AI_API_KEY",
                "owner_email": "owner@example.com",
            },
        ),
    )

    begin_states = iter([(True, 0.0, ""), (False, 40.0, "cadence")])
    monkeypatch.setattr(owner.app.state.container.onemin_manager, "begin_billing_refresh", lambda: next(begin_states))
    monkeypatch.setattr(owner.app.state.container.onemin_manager, "finish_billing_refresh", lambda: None)

    call_count = 0

    def fake_refresh(**_kwargs):
        nonlocal call_count
        call_count += 1
        return (
            [{"refresh_backend": "onemin_api", "account_label": "ONEMIN_AI_API_KEY"}],
            [{"refresh_backend": "onemin_api", "account_label": "ONEMIN_AI_API_KEY"}],
            [],
            1,
            0,
            False,
        )

    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", fake_refresh)

    first = owner.post(
        "/v1/providers/onemin/billing-refresh",
        json={"include_members": True, "provider_api_all_accounts": True},
    )
    assert first.status_code == 200
    assert first.json()["billing_refresh_count"] == 1
    assert first.json()["refresh_throttled"] is False

    second = owner.post(
        "/v1/providers/onemin/billing-refresh",
        json={"include_members": True, "provider_api_all_accounts": True},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert call_count == 1
    assert second_body["refresh_throttled"] is True
    assert second_body["refresh_throttle_seconds_remaining"] == 40
    assert second_body["billing_refresh_count"] == 0
    assert second_body["member_reconciliation_count"] == 0
    assert second_body["api_account_attempted"] == 0
    assert second_body["api_account_skipped"] == 1
    assert "throttled to one run per minute" in second_body["note"]


def test_onemin_billing_refresh_forwards_bound_account_login_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {
                        "account_name": "ONEMIN_AI_API_KEY",
                        "owner_email": "owner@example.com",
                    }
                ]
            }
        ),
    )

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {
                "onemin_account_name": "ONEMIN_AI_API_KEY",
                "onemin_account_credentials_json": {
                    "ONEMIN_AI_API_KEY": {
                        "login_email": "slot@example.com",
                        "login_password": "slotpass",
                        "team_id": "team-123",
                        "team_name": "Finland Office",
                    }
                },
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    from app.api.routes import providers as providers_route

    observed: dict[str, object] = {}

    def fake_refresh(**kwargs):
        observed.update(kwargs)
        return ([], [], [], 1, 0, False)

    def fake_invoke_browseract_tool(**_kwargs):
        raise providers_route.ToolExecutionError("browseract_unavailable")

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", fake_refresh)

    response = owner.post(
        "/v1/providers/onemin/billing-refresh",
        json={"include_members": True},
    )
    assert response.status_code == 200
    assert observed["account_labels"] == {"ONEMIN_AI_API_KEY"}
    assert observed["account_login_credentials"] == {
        "ONEMIN_AI_API_KEY": {
            "login_email": "slot@example.com",
            "login_password": "slotpass",
            "team_id": "team-123",
            "team_name": "Finland Office",
        }
    }


def test_onemin_billing_refresh_uses_browseract_login_fallback_and_skips_direct_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {
                        "account_name": "ONEMIN_AI_API_KEY",
                        "owner_email": "owner@example.com",
                    }
                ]
            }
        ),
    )
    monkeypatch.setenv("BROWSERACT_PASSWORD", "slotpass")

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {
                "onemin_account_name": "ONEMIN_AI_API_KEY",
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    from app.api.routes import providers as providers_route

    invoked: list[str] = []
    observed: dict[str, object] = {}

    def fake_invoke_browseract_tool(**kwargs):
        invoked.append(str(kwargs.get("tool_name") or ""))
        tool_name = str(kwargs.get("tool_name") or "")
        if tool_name == "browseract.onemin_billing_usage":
            return {
                "refresh_backend": "browseract",
                "remaining_credits": "12345",
                "max_credits": "20000",
                "next_topup_at": "2026-03-31T00:00:00Z",
                "topup_amount": "20000",
            }
        return {
            "refresh_backend": "browseract",
            "matched_owner_slots": 1,
        }

    def fake_refresh(**kwargs):
        observed.update(kwargs)
        return (
            [{"account_label": "ONEMIN_AI_API_KEY", "refresh_backend": "onemin_api"}],
            [{"account_label": "ONEMIN_AI_API_KEY", "refresh_backend": "onemin_api"}],
            [],
            1,
            0,
            False,
        )

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", fake_refresh)

    response = owner.post(
        "/v1/providers/onemin/billing-refresh",
        json={"include_members": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert invoked == [
        "browseract.onemin_billing_usage",
        "browseract.onemin_member_reconciliation",
    ]
    assert observed == {}
    assert body["billing_refresh_count"] == 1
    assert body["member_reconciliation_count"] == 1
    assert body["api_account_attempted"] == 0
    assert body["api_account_skipped"] == 1
    assert "BrowserAct login-backed billing pages" in body["note"]


def test_onemin_billing_refresh_uses_owner_ledger_browseract_scope_for_global_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner-1@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "owner_email": "owner-2@example.com"},
                ]
            }
        ),
    )
    monkeypatch.setenv("BROWSERACT_PASSWORD", "slotpass")

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {
                "service_accounts_json": {"BrowserAct": {"tier": "Tier 3"}},
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    from app.api.routes import providers as providers_route

    invoked: list[tuple[str, str]] = []
    observed: dict[str, object] = {}

    def fake_invoke_browseract_tool(**kwargs):
        tool_name = str(kwargs.get("tool_name") or "")
        payload_json = dict(kwargs.get("payload_json") or {})
        account_label = str(payload_json.get("account_label") or "")
        invoked.append((tool_name, account_label))
        if tool_name == "browseract.onemin_billing_usage":
            return {"refresh_backend": "browseract", "remaining_credits": "12345"}
        return {"refresh_backend": "browseract", "matched_owner_slots": 1}

    def fake_refresh(**kwargs):
        observed.update(kwargs)
        return ([], [], [], 0, 0, False)

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", fake_refresh)

    response = owner.post(
        "/v1/providers/onemin/billing-refresh",
        json={"include_members": True, "provider_api_all_accounts": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert observed == {}
    assert body["browseract_scope"] == "all_owner_accounts"
    assert body["browseract_target_labels"] == ["ONEMIN_AI_API_KEY", "ONEMIN_AI_API_KEY_FALLBACK_1"]
    assert body["provider_api_scope"] == "global"
    assert body["provider_api_target_labels"] == []
    assert body["global_aggregate_snapshot"]["provider_key"] == "onemin"
    assert invoked == [
        ("browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY"),
        ("browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY_FALLBACK_1"),
        ("browseract.onemin_member_reconciliation", "ONEMIN_AI_API_KEY"),
        ("browseract.onemin_member_reconciliation", "ONEMIN_AI_API_KEY_FALLBACK_1"),
    ]


def test_onemin_billing_refresh_uses_fleet_browseract_binding_for_operator_targeted_owner_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "owner_email": "owner-2@example.com"},
                ]
            }
        ),
    )
    monkeypatch.setenv("BROWSERACT_PASSWORD", "slotpass")

    from app.api.routes import providers as providers_route

    owner_binding = SimpleNamespace(
        binding_id="owner-binding",
        principal_id="exec-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        auth_metadata_json={
            "trusted_onemin_mapping": True,
            "service_accounts_json": {"BrowserAct": {"tier": "Tier 3"}},
        },
        status="enabled",
    )
    fleet_binding = SimpleNamespace(
        binding_id="fleet-binding",
        principal_id="codex-fleet",
        connector_name="browseract",
        external_account_ref="browseract-main",
        auth_metadata_json={
            "trusted_onemin_mapping": True,
            "onemin_account_names": ["ONEMIN_AI_API_KEY_FALLBACK_1"],
        },
        status="enabled",
    )

    monkeypatch.setattr(owner.app.state.container.onemin_manager, "begin_billing_refresh", lambda: (True, 0.0, ""))
    monkeypatch.setattr(owner.app.state.container.onemin_manager, "finish_billing_refresh", lambda: None)
    monkeypatch.setattr(providers_route, "_browseract_onemin_login_ready", lambda **_: True)
    monkeypatch.setattr(
        providers_route,
        "_normalized_onemin_owner_rows",
        lambda account_labels=None: [
            {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "owner_email": "owner-2@example.com"}
        ],
    )
    monkeypatch.setattr(providers_route, "_enabled_browseract_bindings", lambda _container, _principal_id: [owner_binding])
    monkeypatch.setattr(providers_route, "_all_enabled_browseract_bindings", lambda _container: [owner_binding, fleet_binding])
    observed: dict[str, object] = {}

    def fake_invoke_browseract_tool(**kwargs):
        observed["principal_id"] = kwargs.get("principal_id")
        payload_json = dict(kwargs.get("payload_json") or {})
        observed["binding_id"] = payload_json.get("binding_id")
        observed["account_label"] = payload_json.get("account_label")
        return {"refresh_backend": "browseract", "remaining_credits": "12345"}

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)

    response = owner.post(
        "/v1/providers/onemin/billing-refresh",
        json={
            "include_members": False,
            "include_provider_api": False,
            "account_labels": ["ONEMIN_AI_API_KEY_FALLBACK_1"],
        },
        )
    assert response.status_code == 200
    body = response.json()
    assert observed["principal_id"] == "codex-fleet"
    assert observed["binding_id"] == "fleet-binding"
    assert observed["account_label"] == "ONEMIN_AI_API_KEY_FALLBACK_1"
    assert body["selected_binding_ids"] == ["fleet-binding"]
    assert body["billing_refresh_count"] == 1
    assert body["browseract_target_labels"] == ["ONEMIN_AI_API_KEY_FALLBACK_1"]


def test_onemin_billing_refresh_caps_browseract_login_pass_per_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner-1@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "owner_email": "owner-2@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_2", "owner_email": "owner-3@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_3", "owner_email": "owner-4@example.com"},
                ]
            }
        ),
    )
    monkeypatch.setenv("BROWSERACT_PASSWORD", "slotpass")
    monkeypatch.setenv("ONEMIN_BROWSERACT_MAX_ACCOUNTS_PER_REFRESH", "2")

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {
                "onemin_account_names": [
                    "ONEMIN_AI_API_KEY",
                    "ONEMIN_AI_API_KEY_FALLBACK_1",
                    "ONEMIN_AI_API_KEY_FALLBACK_2",
                    "ONEMIN_AI_API_KEY_FALLBACK_3",
                ]
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    from app.api.routes import providers as providers_route

    invoked: list[tuple[str, str]] = []
    observed: dict[str, object] = {}

    def fake_invoke_browseract_tool(**kwargs):
        tool_name = str(kwargs.get("tool_name") or "")
        payload_json = dict(kwargs.get("payload_json") or {})
        account_label = str(payload_json.get("account_label") or "")
        invoked.append((tool_name, account_label))
        if tool_name == "browseract.onemin_billing_usage":
            return {"refresh_backend": "browseract", "remaining_credits": "12345"}
        return {"refresh_backend": "browseract", "matched_owner_slots": 1}

    def fake_refresh(**kwargs):
        observed.update(kwargs)
        return ([], [], [], 0, 0, False)

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", fake_refresh)

    response = owner.post("/v1/providers/onemin/billing-refresh", json={"include_members": True})
    assert response.status_code == 200
    body = response.json()
    assert observed == {
        "include_members": True,
        "timeout_seconds": 75,
        "all_accounts": False,
        "continue_on_rate_limit": False,
        "account_labels": {"ONEMIN_AI_API_KEY_FALLBACK_2", "ONEMIN_AI_API_KEY_FALLBACK_3"},
        "account_login_credentials": {},
    }
    assert invoked == [
        ("browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY"),
        ("browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY_FALLBACK_1"),
        ("browseract.onemin_member_reconciliation", "ONEMIN_AI_API_KEY"),
        ("browseract.onemin_member_reconciliation", "ONEMIN_AI_API_KEY_FALLBACK_1"),
    ]
    assert body["billing_refresh_count"] == 2
    assert body["member_reconciliation_count"] == 2
    assert body["api_account_attempted"] == 0
    assert body["api_account_skipped"] == 0
    assert body["provider_api_target_labels"] == ["ONEMIN_AI_API_KEY_FALLBACK_2", "ONEMIN_AI_API_KEY_FALLBACK_3"]
    assert "skipped 2 bound 1min account(s)" in body["note"]


def test_onemin_billing_refresh_can_target_specific_account_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner-1@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "owner_email": "owner-2@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_2", "owner_email": "owner-3@example.com"},
                ]
            }
        ),
    )
    monkeypatch.setenv("BROWSERACT_PASSWORD", "slotpass")

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {
                "onemin_account_names": [
                    "ONEMIN_AI_API_KEY",
                    "ONEMIN_AI_API_KEY_FALLBACK_1",
                    "ONEMIN_AI_API_KEY_FALLBACK_2",
                ]
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    from app.api.routes import providers as providers_route

    invoked: list[tuple[str, str]] = []

    def fake_invoke_browseract_tool(**kwargs):
        tool_name = str(kwargs.get("tool_name") or "")
        payload_json = dict(kwargs.get("payload_json") or {})
        account_label = str(payload_json.get("account_label") or "")
        invoked.append((tool_name, account_label))
        if tool_name == "browseract.onemin_billing_usage":
            return {"refresh_backend": "browseract", "remaining_credits": "12345"}
        return {"refresh_backend": "browseract", "matched_owner_slots": 1}

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", lambda **_: ([], [], [], 0, 0, False))

    response = owner.post(
        "/v1/providers/onemin/billing-refresh",
        json={
            "include_members": False,
            "account_labels": ["ONEMIN_AI_API_KEY_FALLBACK_2", "UNKNOWN_SLOT"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert invoked == [("browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY_FALLBACK_2")]
    assert body["billing_refresh_count"] == 1
    assert any(
        row.get("account_label") == "UNKNOWN_SLOT" and row.get("reason") == "account_label_not_bound"
        for row in body["skipped"]
    )


def test_onemin_billing_refresh_skips_targeted_fresh_actual_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_2", "owner_email": "owner-2@example.com"},
                ]
            }
        ),
    )
    monkeypatch.setenv("BROWSERACT_PASSWORD", "slotpass")

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {
                "onemin_account_names": [
                    "ONEMIN_AI_API_KEY_FALLBACK_2",
                ]
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    from app.api.routes import providers as providers_route

    monkeypatch.setattr(owner.app.state.container.onemin_manager, "begin_billing_refresh", lambda: (True, 0.0, ""))
    monkeypatch.setattr(owner.app.state.container.onemin_manager, "finish_billing_refresh", lambda: None)
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        owner.app.state.container.onemin_manager,
        "accounts_snapshot",
        lambda **_: [
            {
                "account_label": "ONEMIN_AI_API_KEY_FALLBACK_2",
                "has_actual_billing": True,
                "last_billing_snapshot_at": now.isoformat(),
                "details_json": {
                    "billing_next_topup_at": (now + timedelta(hours=12)).isoformat(),
                },
            },
        ],
    )

    invoked: list[tuple[str, str]] = []
    provider_api_called = False

    def fake_invoke_browseract_tool(**kwargs):
        tool_name = str(kwargs.get("tool_name") or "")
        payload_json = dict(kwargs.get("payload_json") or {})
        account_label = str(payload_json.get("account_label") or "")
        invoked.append((tool_name, account_label))
        return {"refresh_backend": "browseract", "remaining_credits": "12345"}

    def fake_refresh(**kwargs):
        nonlocal provider_api_called
        provider_api_called = True
        return ([], [], [], 0, 0, False)

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", fake_refresh)

    response = owner.post(
        "/v1/providers/onemin/billing-refresh",
        json={
            "include_members": False,
            "account_labels": ["ONEMIN_AI_API_KEY_FALLBACK_2"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert invoked == []
    assert provider_api_called is False
    assert body["provider_api_target_labels"] == []
    assert body["billing_refresh_count"] == 0
    assert "fresh actual billing snapshots" in body["note"]


def test_onemin_billing_refresh_rotates_browseract_login_pass_across_cycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner-1@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "owner_email": "owner-2@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_2", "owner_email": "owner-3@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_3", "owner_email": "owner-4@example.com"},
                ]
            }
        ),
    )
    monkeypatch.setenv("BROWSERACT_PASSWORD", "slotpass")
    monkeypatch.setenv("ONEMIN_BROWSERACT_MAX_ACCOUNTS_PER_REFRESH", "2")

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {
                "onemin_account_names": [
                    "ONEMIN_AI_API_KEY",
                    "ONEMIN_AI_API_KEY_FALLBACK_1",
                    "ONEMIN_AI_API_KEY_FALLBACK_2",
                    "ONEMIN_AI_API_KEY_FALLBACK_3",
                ]
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    from app.api.routes import providers as providers_route

    begin_states = iter([(True, 0.0, ""), (True, 0.0, "")])
    monkeypatch.setattr(owner.app.state.container.onemin_manager, "begin_billing_refresh", lambda: next(begin_states))
    monkeypatch.setattr(owner.app.state.container.onemin_manager, "finish_billing_refresh", lambda: None)

    invoked: list[tuple[str, str]] = []

    def fake_invoke_browseract_tool(**kwargs):
        tool_name = str(kwargs.get("tool_name") or "")
        payload_json = dict(kwargs.get("payload_json") or {})
        account_label = str(payload_json.get("account_label") or "")
        invoked.append((tool_name, account_label))
        if tool_name == "browseract.onemin_billing_usage":
            return {"refresh_backend": "browseract", "remaining_credits": "12345"}
        return {"refresh_backend": "browseract", "matched_owner_slots": 1}

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", lambda **_: ([], [], [], 0, 0, False))

    first = owner.post("/v1/providers/onemin/billing-refresh", json={"include_members": False})
    second = owner.post("/v1/providers/onemin/billing-refresh", json={"include_members": False})

    assert first.status_code == 200
    assert second.status_code == 200
    assert invoked == [
        ("browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY"),
        ("browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY_FALLBACK_1"),
        ("browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY_FALLBACK_2"),
        ("browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY_FALLBACK_3"),
    ]


def test_onemin_billing_refresh_fans_out_browseract_jobs_in_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv("ONEMIN_BROWSERACT_PARALLELISM", "3")
    for index, account_label in enumerate(
        [
            "ONEMIN_AI_API_KEY",
            "ONEMIN_AI_API_KEY_FALLBACK_1",
            "ONEMIN_AI_API_KEY_FALLBACK_2",
        ],
        start=1,
    ):
        created = owner.post(
            "/v1/connectors/bindings",
            json={
                "connector_name": "browseract",
                "external_account_ref": f"browseract-main-{index}",
                "scope_json": {"services": ["BrowserAct"]},
                "auth_metadata_json": {
                    "onemin_account_name": account_label,
                },
                "status": "enabled",
            },
        )
        assert created.status_code == 200

    from app.api.routes import providers as providers_route

    monkeypatch.setattr(owner.app.state.container.onemin_manager, "begin_billing_refresh", lambda: (True, 0.0, ""))
    monkeypatch.setattr(owner.app.state.container.onemin_manager, "finish_billing_refresh", lambda: None)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", lambda **_: ([], [], [], 0, 0, False))
    monkeypatch.setattr(providers_route, "_browseract_onemin_login_ready", lambda **_: True)

    barrier = threading.Barrier(3)
    invoked: list[tuple[str, str]] = []

    def fake_invoke_browseract_tool(**kwargs):
        tool_name = str(kwargs.get("tool_name") or "")
        payload_json = dict(kwargs.get("payload_json") or {})
        account_label = str(payload_json.get("account_label") or "")
        if tool_name == "browseract.onemin_billing_usage":
            barrier.wait(timeout=1.0)
            invoked.append((tool_name, account_label))
            return {"refresh_backend": "browseract", "remaining_credits": "12345"}
        return {"refresh_backend": "browseract", "matched_owner_slots": 1}

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)

    response = owner.post("/v1/providers/onemin/billing-refresh", json={"include_members": False})

    assert response.status_code == 200
    assert response.json()["billing_refresh_count"] == 3
    assert sorted(invoked) == [
        ("browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY"),
        ("browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY_FALLBACK_1"),
        ("browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY_FALLBACK_2"),
    ]


def test_onemin_billing_refresh_only_reconciles_members_after_successful_billing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {
                "onemin_account_names": [
                    "ONEMIN_AI_API_KEY",
                    "ONEMIN_AI_API_KEY_FALLBACK_1",
                ]
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    from app.api.routes import providers as providers_route

    monkeypatch.setattr(owner.app.state.container.onemin_manager, "begin_billing_refresh", lambda: (True, 0.0, ""))
    monkeypatch.setattr(owner.app.state.container.onemin_manager, "finish_billing_refresh", lambda: None)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", lambda **_: ([], [], [], 0, 0, False))
    monkeypatch.setattr(providers_route, "_browseract_onemin_login_ready", lambda **_: True)

    invoked: list[tuple[str, str]] = []

    def fake_invoke_browseract_tool(**kwargs):
        tool_name = str(kwargs.get("tool_name") or "")
        payload_json = dict(kwargs.get("payload_json") or {})
        account_label = str(payload_json.get("account_label") or "")
        invoked.append((tool_name, account_label))
        if tool_name == "browseract.onemin_billing_usage" and account_label == "ONEMIN_AI_API_KEY_FALLBACK_1":
            raise providers_route.ToolExecutionError("login_failed")
        if tool_name == "browseract.onemin_billing_usage":
            return {"refresh_backend": "browseract", "remaining_credits": "12345"}
        return {"refresh_backend": "browseract", "matched_owner_slots": 1}

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)

    response = owner.post("/v1/providers/onemin/billing-refresh", json={"include_members": True})

    assert response.status_code == 200
    assert ("browseract.onemin_member_reconciliation", "ONEMIN_AI_API_KEY") in invoked
    assert ("browseract.onemin_member_reconciliation", "ONEMIN_AI_API_KEY_FALLBACK_1") not in invoked
    assert response.json()["member_reconciliation_count"] == 1


def test_onemin_billing_refresh_stops_after_systemic_browseract_failures_and_targets_remaining_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    monkeypatch.setenv("ONEMIN_BROWSERACT_SYSTEMIC_FAILURE_THRESHOLD", "2")

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {
                "onemin_account_names": [
                    "ONEMIN_AI_API_KEY",
                    "ONEMIN_AI_API_KEY_FALLBACK_1",
                    "ONEMIN_AI_API_KEY_FALLBACK_2",
                    "ONEMIN_AI_API_KEY_FALLBACK_3",
                ]
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    from app.api.routes import providers as providers_route

    observed: dict[str, object] = {}
    invoked: list[str] = []

    monkeypatch.setattr(owner.app.state.container.onemin_manager, "begin_billing_refresh", lambda: (True, 0.0, ""))
    monkeypatch.setattr(owner.app.state.container.onemin_manager, "finish_billing_refresh", lambda: None)
    monkeypatch.setattr(providers_route, "_browseract_onemin_login_ready", lambda **_: True)

    def fake_invoke_browseract_tool(**kwargs):
        payload_json = dict(kwargs.get("payload_json") or {})
        account_label = str(payload_json.get("account_label") or "")
        invoked.append(account_label)
        raise providers_route.ToolExecutionError("ui_service_worker_failed:onemin_billing_usage:auth_request_failed")

    def fake_refresh(**kwargs):
        observed.update(kwargs)
        return ([], [], [], 0, 0, False)

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", fake_refresh)

    response = owner.post("/v1/providers/onemin/billing-refresh", json={"include_members": False})

    assert response.status_code == 200
    body = response.json()
    assert invoked == [
        "ONEMIN_AI_API_KEY",
        "ONEMIN_AI_API_KEY_FALLBACK_1",
    ]
    assert body["browseract_failed_labels"] == [
        "ONEMIN_AI_API_KEY",
        "ONEMIN_AI_API_KEY_FALLBACK_1",
    ]
    assert body["provider_api_target_labels"] == [
        "ONEMIN_AI_API_KEY",
        "ONEMIN_AI_API_KEY_FALLBACK_1",
        "ONEMIN_AI_API_KEY_FALLBACK_2",
        "ONEMIN_AI_API_KEY_FALLBACK_3",
    ]
    assert observed["account_labels"] == {
        "ONEMIN_AI_API_KEY",
        "ONEMIN_AI_API_KEY_FALLBACK_1",
        "ONEMIN_AI_API_KEY_FALLBACK_2",
        "ONEMIN_AI_API_KEY_FALLBACK_3",
    }


def test_onemin_billing_refresh_recovers_browseract_failures_via_targeted_provider_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {
                "onemin_account_names": [
                    "ONEMIN_AI_API_KEY",
                    "ONEMIN_AI_API_KEY_FALLBACK_1",
                ]
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    from app.api.routes import providers as providers_route

    monkeypatch.setattr(owner.app.state.container.onemin_manager, "begin_billing_refresh", lambda: (True, 0.0, ""))
    monkeypatch.setattr(owner.app.state.container.onemin_manager, "finish_billing_refresh", lambda: None)
    monkeypatch.setattr(
        providers_route,
        "_resolve_onemin_account_labels",
        lambda _binding: ("ONEMIN_AI_API_KEY", "ONEMIN_AI_API_KEY_FALLBACK_1"),
    )
    monkeypatch.setattr(providers_route, "_browseract_onemin_login_ready", lambda **_: True)
    monkeypatch.setattr(
        providers_route.upstream,
        "_provider_health_report",
        lambda: {
            "providers": {
                "onemin": {
                    "configured_slots": 2,
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot_env_name": "ONEMIN_AI_API_KEY",
                            "slot": "slot-1",
                            "state": "ready",
                            "estimated_remaining_credits": 12345.0,
                        },
                        {
                            "account_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                            "slot_env_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                            "slot": "slot-2",
                            "state": "ready",
                            "estimated_remaining_credits": 12000.0,
                        },
                    ],
                }
            }
        },
    )

    invoked: list[tuple[str, str]] = []
    observed: dict[str, object] = {}

    def fake_invoke_browseract_tool(**kwargs):
        tool_name = str(kwargs.get("tool_name") or "")
        payload_json = dict(kwargs.get("payload_json") or {})
        account_label = str(payload_json.get("account_label") or "")
        invoked.append((tool_name, account_label))
        if tool_name == "browseract.onemin_billing_usage" and account_label == "ONEMIN_AI_API_KEY_FALLBACK_1":
            raise providers_route.ToolExecutionError(
                "ui_service_worker_failed:onemin_billing_usage:auth_request_failed"
            )
        if tool_name == "browseract.onemin_billing_usage":
            return {"refresh_backend": "browseract", "account_label": account_label, "remaining_credits": "12345"}
        return {"refresh_backend": "browseract", "account_label": account_label, "matched_owner_slots": 1}

    def fake_refresh(**kwargs):
        observed.update(kwargs)
        return (
            [{"account_label": "ONEMIN_AI_API_KEY_FALLBACK_1", "refresh_backend": "onemin_api", "remaining_credits": 12000}],
            [{"account_label": "ONEMIN_AI_API_KEY_FALLBACK_1", "refresh_backend": "onemin_api", "matched_owner_slots": 1}],
            [],
            1,
            0,
            False,
        )

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", fake_refresh)

    response = owner.post("/v1/providers/onemin/billing-refresh", json={"include_members": True})

    assert response.status_code == 200
    body = response.json()
    assert observed["all_accounts"] is False
    assert observed["account_labels"] == {"ONEMIN_AI_API_KEY_FALLBACK_1"}
    assert body["billing_refresh_count"] == 2
    assert body["member_reconciliation_count"] == 2
    assert body["errors"] == []
    assert body["provider_api_recovery_mode"] == "browseract_failure_recovery"
    assert body["provider_api_target_labels"] == ["ONEMIN_AI_API_KEY_FALLBACK_1"]
    assert body["browseract_failed_labels"] == ["ONEMIN_AI_API_KEY_FALLBACK_1"]
    assert body["browseract_recovered_labels"] == ["ONEMIN_AI_API_KEY_FALLBACK_1"]
    assert body["aggregate_snapshot"]["sum_free_credits"] == 24345.0
    assert body["actual_credits_snapshot"]["binding_account_count"] == 2
    assert "recovered through the direct 1min API" in body["note"]
    assert invoked == [
        ("browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY"),
        ("browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY_FALLBACK_1"),
        ("browseract.onemin_member_reconciliation", "ONEMIN_AI_API_KEY"),
    ]


def test_onemin_billing_refresh_prioritizes_missing_and_stale_actual_billing_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {
                "onemin_account_names": [
                    "ONEMIN_AI_API_KEY",
                    "ONEMIN_AI_API_KEY_FALLBACK_1",
                    "ONEMIN_AI_API_KEY_FALLBACK_2",
                    "ONEMIN_AI_API_KEY_FALLBACK_3",
                ]
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    from app.api.routes import providers as providers_route

    monkeypatch.setattr(owner.app.state.container.onemin_manager, "begin_billing_refresh", lambda: (True, 0.0, ""))
    monkeypatch.setattr(owner.app.state.container.onemin_manager, "finish_billing_refresh", lambda: None)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", lambda **_: ([], [], [], 0, 0, False))
    monkeypatch.setattr(providers_route, "_browseract_onemin_login_ready", lambda **_: True)
    monkeypatch.setattr(
        owner.app.state.container.onemin_manager,
        "accounts_snapshot",
        lambda **_: [
            {
                "account_label": "ONEMIN_AI_API_KEY",
                "has_actual_billing": True,
                "last_billing_snapshot_at": "2026-03-28T12:00:00+00:00",
            },
            {
                "account_label": "ONEMIN_AI_API_KEY_FALLBACK_1",
                "has_actual_billing": False,
                "last_billing_snapshot_at": None,
            },
            {
                "account_label": "ONEMIN_AI_API_KEY_FALLBACK_2",
                "has_actual_billing": True,
                "last_billing_snapshot_at": "2026-03-28T09:00:00+00:00",
            },
            {
                "account_label": "ONEMIN_AI_API_KEY_FALLBACK_3",
                "has_actual_billing": False,
                "last_billing_snapshot_at": "2026-03-27T09:00:00+00:00",
            },
        ],
    )

    selected_orders: list[list[str]] = []

    def fake_select(labels, *, limit: int):
        selected_orders.append(list(labels))
        return tuple(list(labels)[:limit])

    monkeypatch.setattr(owner.app.state.container.onemin_manager, "select_billing_refresh_account_labels", fake_select)
    monkeypatch.setattr(
        providers_route,
        "_invoke_browseract_tool",
        lambda **kwargs: {"refresh_backend": "browseract", "remaining_credits": "12345"}
        if str(kwargs.get("tool_name") or "") == "browseract.onemin_billing_usage"
        else {"refresh_backend": "browseract", "matched_owner_slots": 1},
    )

    response = owner.post("/v1/providers/onemin/billing-refresh", json={"include_members": False})

    assert response.status_code == 200
    assert selected_orders == [
        [
            "ONEMIN_AI_API_KEY_FALLBACK_1",
            "ONEMIN_AI_API_KEY_FALLBACK_3",
            "ONEMIN_AI_API_KEY_FALLBACK_2",
            "ONEMIN_AI_API_KEY",
        ],
    ]


def test_onemin_provider_api_full_refresh_continues_after_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import providers as providers_route
    monkeypatch.setattr(
        providers_route.upstream,
        "onemin_owner_rows",
        lambda: (
            {"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner-1@example.com"},
            {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "owner_email": "owner-2@example.com"},
            {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_2", "owner_email": "owner-3@example.com"},
        ),
    )

    calls: list[str] = []

    def fake_refresh_account(
        *,
        account_name: str,
        owner_email: str,
        include_members: bool,
        timeout_seconds: int,
        login_email: str = "",
        login_password: str = "",
    ):
        calls.append(account_name)
        if account_name == "ONEMIN_AI_API_KEY":
            raise RuntimeError("onemin_login_http_429")
        billing_result = {
            "refresh_backend": "onemin_api",
            "account_label": account_name,
            "owner_email": owner_email,
            "basis": "actual_provider_api",
        }
        member_result = {
            "refresh_backend": "onemin_api",
            "account_label": account_name,
            "owner_email": owner_email,
            "basis": "actual_provider_api",
        }
        return billing_result, member_result if include_members else None

    monkeypatch.setattr(providers_route, "_refresh_onemin_api_account", fake_refresh_account)
    monkeypatch.setattr(providers_route.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(providers_route, "_ONEMIN_DIRECT_API_QUARANTINED_UNTIL", 0.0, raising=False)
    monkeypatch.setattr(providers_route, "_ONEMIN_DIRECT_API_QUARANTINE_REASON", "", raising=False)

    billing_results, member_results, errors, attempted_count, skipped_count, rate_limited = providers_route._refresh_onemin_via_provider_api(
        include_members=True,
        timeout_seconds=180,
        all_accounts=True,
        continue_on_rate_limit=True,
    )

    assert calls == [
        "ONEMIN_AI_API_KEY",
        "ONEMIN_AI_API_KEY_FALLBACK_1",
        "ONEMIN_AI_API_KEY_FALLBACK_2",
    ]
    assert attempted_count == 3
    assert skipped_count == 0
    assert rate_limited is True
    assert len(errors) == 1
    assert errors[0]["tool_name"] == "onemin.api.billing_refresh"
    assert [row["account_label"] for row in billing_results] == [
        "ONEMIN_AI_API_KEY_FALLBACK_1",
        "ONEMIN_AI_API_KEY_FALLBACK_2",
    ]
    assert [row["account_label"] for row in member_results] == [
        "ONEMIN_AI_API_KEY_FALLBACK_1",
        "ONEMIN_AI_API_KEY_FALLBACK_2",
    ]


def test_onemin_provider_api_refresh_batches_after_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import providers as providers_route

    calls: list[str] = []
    sleep_calls: list[float] = []

    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner-1@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "owner_email": "owner-2@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_2", "owner_email": "owner-3@example.com"},
                    {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_3", "owner_email": "owner-4@example.com"},
                ]
            }
        ),
    )

    monkeypatch.setattr(
        providers_route,
        "_onemin_direct_api_quarantine_remaining",
        lambda: (0.0, ""),
    )
    monkeypatch.setattr(
        providers_route.upstream,
        "onemin_owner_rows",
        lambda: (
            {
                "account_name": "ONEMIN_AI_API_KEY",
                "owner_email": "owner-1@example.com",
            },
            {
                "account_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                "owner_email": "owner-2@example.com",
            },
            {
                "account_name": "ONEMIN_AI_API_KEY_FALLBACK_2",
                "owner_email": "owner-3@example.com",
            },
            {
                "account_name": "ONEMIN_AI_API_KEY_FALLBACK_3",
                "owner_email": "owner-4@example.com",
            },
        ),
    )

    def fake_refresh_account(
        *,
        account_name: str,
        owner_email: str,
        include_members: bool,
        timeout_seconds: int,
        login_email: str = "",
        login_password: str = "",
    ):
        calls.append(account_name)
        if account_name == "ONEMIN_AI_API_KEY":
            raise RuntimeError("onemin_login_http_429")
        billing_result = {
            "refresh_backend": "onemin_api",
            "account_label": account_name,
            "owner_email": owner_email,
            "basis": "actual_provider_api",
        }
        member_result = {
            "refresh_backend": "onemin_api",
            "account_label": account_name,
            "owner_email": owner_email,
            "basis": "actual_provider_api",
        }
        return billing_result, member_result if include_members else None

    monkeypatch.setattr(providers_route, "_refresh_onemin_api_account", fake_refresh_account)
    monkeypatch.setenv("ONEMIN_DIRECT_API_BATCH_SIZE", "2")
    monkeypatch.setenv("ONEMIN_DIRECT_API_BATCH_BACKOFF_SECONDS", "0.5")
    monkeypatch.setenv("ONEMIN_DIRECT_API_MIN_ACCOUNT_DELAY_SECONDS", "0")
    monkeypatch.setattr(providers_route.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    _, _, errors, attempted_count, skipped_count, rate_limited = providers_route._refresh_onemin_via_provider_api(
        include_members=True,
        timeout_seconds=180,
        all_accounts=True,
        continue_on_rate_limit=True,
    )

    assert calls == [
        "ONEMIN_AI_API_KEY",
        "ONEMIN_AI_API_KEY_FALLBACK_1",
        "ONEMIN_AI_API_KEY_FALLBACK_2",
        "ONEMIN_AI_API_KEY_FALLBACK_3",
    ]
    assert attempted_count == 4
    assert skipped_count == 0
    assert rate_limited is True
    assert errors[-1]["error"] == "onemin_login_http_429"
    assert sleep_calls == [0.5]


def test_onemin_manager_exposes_hourly_burn_rate_on_accounts_aggregate_and_actual_credits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)
    from app.api.routes import providers as providers_route

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "owner@example.com",
            "auth_metadata_json": {
                "onemin_account_name": "ONEMIN_AI_API_KEY",
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    monkeypatch.setattr(
        providers_route.upstream,
        "_provider_health_report",
        lambda: {
            "providers": {
                "onemin": {
                    "configured_slots": 3,
                    "estimated_burn_credits_per_hour": 2400.0,
                    "estimated_hours_remaining_at_current_pace": 50.0,
                    "estimated_days_remaining_at_7d_average": 4.5,
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot": "primary",
                            "slot_env_name": "ONEMIN_AI_API_KEY",
                            "state": "ready",
                            "owner_email": "owner@example.com",
                            "billing_remaining_credits": 1000.0,
                            "billing_max_credits": 2000.0,
                            "billing_basis": "actual_billing_usage_page",
                            "billing_observed_usage_burn_credits_per_hour": 1200.0,
                        },
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot": "fallback_1",
                            "slot_env_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                            "state": "ready",
                            "owner_email": "owner@example.com",
                            "estimated_remaining_credits": 0.0,
                            "billing_observed_usage_burn_credits_per_hour": 300.0,
                        },
                        {
                            "account_name": "ONEMIN_AI_API_KEY_FALLBACK_2",
                            "slot": "fallback_2",
                            "slot_env_name": "ONEMIN_AI_API_KEY_FALLBACK_2",
                            "state": "ready",
                            "owner_email": "other@example.com",
                            "estimated_remaining_credits": 500.0,
                        },
                    ],
                }
            }
        },
    )

    accounts = owner.get("/v1/providers/onemin/accounts")
    assert accounts.status_code == 200
    account_row = next(row for row in accounts.json()["accounts"] if row["account_id"] == "ONEMIN_AI_API_KEY")
    assert account_row["observed_usage_burn_credits_per_hour"] == 1500.0
    assert account_row["current_burn_credits_per_hour"] == 1500.0
    assert account_row["burn_basis"] == "observed_usage"
    assert account_row["slot_count_with_observed_usage_burn"] == 2

    aggregate = owner.get("/v1/providers/onemin/aggregate")
    assert aggregate.status_code == 200
    aggregate_body = aggregate.json()
    assert aggregate_body["observed_usage_burn_credits_per_hour"] == 1500.0
    assert aggregate_body["estimated_pool_burn_credits_per_hour"] == 2400.0
    assert aggregate_body["current_burn_credits_per_hour"] == 1500.0
    assert aggregate_body["burn_basis"] == "observed_usage"
    assert aggregate_body["bound_observed_usage_burn_credits_per_hour"] == 1500.0

    actual = owner.get("/v1/providers/onemin/actual-credits")
    assert actual.status_code == 200
    actual_body = actual.json()
    assert actual_body["actual_free_credits_total"] == 1000.0
    assert actual_body["observed_usage_burn_credits_per_hour"] == 1500.0
    assert actual_body["current_burn_credits_per_hour"] == 1500.0
    assert actual_body["burn_basis"] == "observed_usage"
    assert actual_body["global_estimated_pool_burn_credits_per_hour"] == 2400.0

def test_onemin_aggregate_and_runway_expose_scope_and_operator_global_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import providers as providers_route

    owner = _client(principal_id="exec-1", operator=True)

    created = owner.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "owner@example.com",
            "auth_metadata_json": {
                "onemin_account_name": "ONEMIN_AI_API_KEY",
            },
            "status": "enabled",
        },
    )
    assert created.status_code == 200

    monkeypatch.setattr(
        providers_route.upstream,
        "_provider_health_report",
        lambda: {
            "providers": {
                "onemin": {
                    "configured_slots": 2,
                    "estimated_remaining_credits_total": 1500.0,
                    "remaining_percent_of_max": 75.0,
                    "estimated_hours_remaining_at_current_pace": 12.0,
                    "estimated_days_remaining_at_7d_average": 1.5,
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot": "primary",
                            "slot_env_name": "ONEMIN_AI_API_KEY",
                            "state": "ready",
                            "estimated_remaining_credits": 1000.0,
                        },
                        {
                            "account_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                            "slot": "fallback_1",
                            "slot_env_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                            "state": "ready",
                            "estimated_remaining_credits": 500.0,
                        },
                    ],
                }
            }
        },
    )

    principal_aggregate = owner.get("/v1/providers/onemin/aggregate")
    assert principal_aggregate.status_code == 200
    principal_aggregate_body = principal_aggregate.json()
    assert principal_aggregate_body["scope"] == "principal_bindings"
    assert principal_aggregate_body["sum_free_credits"] == 1000.0
    assert principal_aggregate_body["live_remaining_credits_total"] == 1000.0
    assert principal_aggregate_body["live_positive_balance_account_count"] == 1
    assert principal_aggregate_body["global_estimated_free_credits_total"] == 1500.0
    assert principal_aggregate_body["global_live_remaining_credits_total"] == 1500.0
    assert principal_aggregate_body["global_estimated_hours_remaining_at_current_pace"] == 12.0
    assert principal_aggregate_body["scope_note"].startswith("principal view only includes 1min accounts bound")

    principal_runway = owner.get("/v1/providers/onemin/runway")
    assert principal_runway.status_code == 200
    principal_runway_body = principal_runway.json()
    assert principal_runway_body["forecast"]["scope"] == "principal_bindings"
    assert principal_runway_body["forecast"]["remaining_credits"] == 1000.0
    assert principal_runway_body["forecast"]["global_estimated_free_credits_total"] == 1500.0
    assert principal_runway_body["forecast"]["global_live_remaining_credits_total"] == 1500.0

    viewer = _client(principal_id="exec-viewer")
    denied_global = viewer.get("/v1/providers/onemin/aggregate?scope=global")
    assert denied_global.status_code == 403
    denied_body = denied_global.json()
    if "detail" in denied_body:
        assert denied_body["detail"] == "operator_scope_required"
    else:
        assert denied_body["error"]["code"] == "operator_scope_required"

    operator = _client(principal_id="exec-ops", operator=True)
    global_aggregate = operator.get("/v1/providers/onemin/aggregate?scope=global")
    assert global_aggregate.status_code == 200
    global_aggregate_body = global_aggregate.json()
    assert global_aggregate_body["scope"] == "global_pool"
    assert global_aggregate_body["scope_principal_id"] is None
    assert global_aggregate_body["sum_free_credits"] == 1500.0
    assert global_aggregate_body["live_remaining_credits_total"] == 1500.0
    assert global_aggregate_body["live_positive_balance_slot_count"] == 2
    assert global_aggregate_body["account_count"] == 2
    assert global_aggregate_body["scope_note"] == ""

    global_runway = operator.get("/v1/providers/onemin/runway?scope=global")
    assert global_runway.status_code == 200
    global_runway_body = global_runway.json()
    assert global_runway_body["principal_id"] == "exec-ops"
    assert global_runway_body["forecast"]["scope"] == "global_pool"
    assert global_runway_body["forecast"]["remaining_credits"] == 1500.0
    assert global_runway_body["forecast"]["global_live_remaining_credits_total"] == 1500.0


def test_onemin_manager_runway_falls_back_to_observed_burn_when_provider_pace_is_missing() -> None:
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    provider_health = {
        "providers": {
            "onemin": {
                "configured_slots": 3,
                "estimated_burn_credits_per_hour": 2400.0,
                "slots": [
                    {
                        "account_name": "ONEMIN_AI_API_KEY",
                        "slot": "primary",
                        "slot_env_name": "ONEMIN_AI_API_KEY",
                        "state": "ready",
                        "billing_remaining_credits": 1000.0,
                        "billing_max_credits": 2000.0,
                        "billing_basis": "actual_billing_usage_page",
                        "billing_observed_usage_burn_credits_per_hour": 1200.0,
                    },
                    {
                        "account_name": "ONEMIN_AI_API_KEY",
                        "slot": "fallback_1",
                        "slot_env_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                        "state": "ready",
                        "estimated_remaining_credits": 0.0,
                        "billing_observed_usage_burn_credits_per_hour": 300.0,
                    },
                    {
                        "account_name": "ONEMIN_AI_API_KEY_FALLBACK_2",
                        "slot": "fallback_2",
                        "slot_env_name": "ONEMIN_AI_API_KEY_FALLBACK_2",
                        "state": "ready",
                        "estimated_remaining_credits": 500.0,
                    },
                ],
            }
        }
    }

    forecast = manager.runway_snapshot(provider_health=provider_health, binding_rows=[], principal_id="")

    assert forecast["remaining_credits"] == 1500.0
    assert forecast["current_burn_per_hour"] == 1500.0
    assert forecast["hours_remaining_current_pace"] == 1.0
    assert forecast["days_remaining_7d_avg"] == 0.04
    assert forecast["burn_basis"] == "observed_usage"


def test_provider_registry_endpoint_exposes_lane_backend_and_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _client(principal_id="exec-1", operator=True)

    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "sh")
    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "vertex-fallback")
    monkeypatch.setenv("EA_GEMINI_VORTEX_SLOT_DEFAULT_OWNER", "fleet-primary")
    monkeypatch.setenv("EA_GEMINI_VORTEX_SLOT_FALLBACK_1_OWNER", "fleet-shadow")
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")

    response = owner.get("/v1/providers/registry")
    assert response.status_code == 200
    body = response.json()

    assert body["contract_name"] == "ea.provider_registry"
    assert body["principal_id"] == "exec-1"

    groundwork = next(item for item in body["lanes"] if item["profile"] == "groundwork")
    assert groundwork["backend"] == "gemini_vortex"
    assert groundwork["health_provider_key"] == "gemini_vortex"
    assert groundwork["capacity_summary"]["configured_slots"] == 2
    assert groundwork["capacity_summary"]["slot_owners"] == ["fleet-primary", "fleet-shadow"]

    review_light = next(item for item in body["lanes"] if item["profile"] == "review_light")
    assert review_light["backend"] == "chatplayground"
    assert review_light["health_provider_key"] == "chatplayground"
    assert review_light["providers"][0]["provider_key"] == "browseract"


def test_media_stewardship_endpoint_exposes_scheduler_and_challenger_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    owner = _client(principal_id="exec-1", operator=True)

    from app.api.routes import providers as providers_route

    scheduler_path = tmp_path / "provider-scheduler.json"
    challenger_path = tmp_path / "challenger-ledger.json"
    scheduler_path.write_text(
        json.dumps(
            {
                "providers": {
                    "media_factory": {
                        "active_until_epoch": 4102444800.0,
                        "active_target": "assets/hero/chummer6-hero.png",
                        "updated_at": 4102441200.0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    challenger_path.write_text(
        json.dumps(
            {
                "assets": {
                    "assets/hero/chummer6-hero.png": {
                        "provider": "media_factory",
                        "status": "media_factory:rendered",
                        "score": 312.0,
                        "updated_at": 4102441200.0,
                        "last_challenger": {
                            "provider": "gemini_vortex",
                            "status": "gemini_vortex:rendered",
                            "beat_champion": False,
                            "updated_at": 4102441300.0,
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(providers_route, "_MEDIA_PROVIDER_SCHEDULER_PATH", scheduler_path)
    monkeypatch.setattr(providers_route, "_MEDIA_CHALLENGER_LEDGER_PATH", challenger_path)

    response = owner.get("/v1/providers/media-stewardship")
    assert response.status_code == 200
    body = response.json()
    assert body["contract_name"] == "ea.media_stewardship"
    assert body["provider_scheduler"]["provider_count"] == 1
    assert body["provider_scheduler"]["active_provider_count"] == 1
    assert body["provider_scheduler"]["providers"][0]["provider_key"] == "media_factory"
    assert body["provider_scheduler"]["providers"][0]["active_target"] == "assets/hero/chummer6-hero.png"
    assert body["provider_scheduler"]["providers"][0]["wait_seconds_remaining"] > 0
    assert body["challenger_ledger"]["asset_count"] == 1
    assert body["challenger_ledger"]["challenger_count"] == 1
    assert body["challenger_ledger"]["assets"][0]["last_challenger_provider"] == "gemini_vortex"
    assert body["challenger_ledger"]["assets"][0]["last_challenger_beat_champion"] is False


def test_public_tour_routes_serve_bundle_html_json_and_assets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_TOURS", "1")
    slug = "kahlenberg-layout-first"
    bundle_dir = tmp_path / slug
    bundle_dir.mkdir(parents=True)
    asset_path = bundle_dir / "scene-01.jpg"
    asset_path.write_bytes(b"fake-jpeg-data")
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "title": "Kahlenberg Tour",
                "display_title": "Kahlenberg Tour",
                "variant_key": "layout_first",
                "variant_label": "layout first",
                "scene_count": 1,
                "listing_url": "https://example.test/listing",
                "hosted_url": f"https://ea.example/tours/{slug}",
                "facts": {
                    "rooms": 2,
                    "area_sqm": 58,
                    "total_rent_eur": 897,
                    "availability": "ab sofort",
                    "address_lines": ["1200 Wien"],
                    "teaser_attributes": ["Kahlenbergblick"],
                },
                "brief": {
                    "theme_name": "Calm daylight",
                    "tour_style": "layout first",
                    "audience": "flat hunters",
                    "creative_brief": "Lead with plan clarity.",
                    "call_to_action": "Book a viewing.",
                },
                "scenes": [
                    {
                        "name": "Living room",
                        "role": "photo",
                        "image_url": "https://example.test/original.jpg",
                        "source_url": "https://example.test/original.jpg",
                        "asset_relpath": "scene-01.jpg",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))

    client = _client(principal_id="exec-public-tour")

    page = client.get(f"/tours/{slug}")
    assert page.status_code == 200
    assert "Property Tour" in page.text
    assert f"/tours/files/{slug}/scene-01.jpg" in page.text

    payload = client.get(f"/tours/{slug}.json")
    assert payload.status_code == 200
    assert payload.json()["slug"] == slug

    asset = client.get(f"/tours/files/{slug}/scene-01.jpg")
    assert asset.status_code == 200
    assert asset.content == b"fake-jpeg-data"
    assert asset.headers["content-type"].startswith("image/jpeg")


def test_public_results_no_longer_shadow_tour_routes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_RESULTS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_TOURS", "1")
    result_dir = tmp_path / "results"
    result_bundle = result_dir / "movie-demo"
    result_bundle.mkdir(parents=True)
    (result_bundle / "asset.html").write_text("<html><body>movie</body></html>", encoding="utf-8")
    (result_bundle / "result.json").write_text(
        json.dumps(
            {
                "slug": "movie-demo",
                "title": "Movie Demo",
                "service_key": "mootion_movie",
                "summary": "Demo movie",
                "body_text": "Demo movie",
                "mime_type": "text/html",
                "viewer_kind": "html",
                "asset_relpath": "asset.html",
                "hosted_url": "https://ea.example/results/movie-demo",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_PUBLIC_RESULT_DIR", str(result_dir))
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path / "tours"))

    client = _client(principal_id="exec-public-result")

    result_page = client.get("/results/movie-demo")
    assert result_page.status_code == 200
    assert "Movie Demo" in result_page.text

    missing_tour = client.get("/tours/movie-demo")
    assert missing_tour.status_code == 404
    assert missing_tour.json()["error"]["code"] == "tour_not_found"


def test_public_side_surfaces_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_SIDE_SURFACES", "0")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_RESULTS", "0")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_TOURS", "0")
    client = _client(principal_id="exec-public-disabled")

    tour = client.get("/tours/example-tour")
    assert tour.status_code == 404
    assert tour.json() == {"detail": "Not Found"}

    result_page = client.get("/results/example-result")
    assert result_page.status_code == 404
    assert result_page.json() == {"detail": "Not Found"}


def test_public_results_and_tours_can_be_enabled_independently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result_dir = tmp_path / "results"
    result_bundle = result_dir / "movie-demo"
    result_bundle.mkdir(parents=True)
    (result_bundle / "asset.html").write_text("<html><body>movie</body></html>", encoding="utf-8")
    (result_bundle / "result.json").write_text(
        json.dumps(
            {
                "slug": "movie-demo",
                "title": "Movie Demo",
                "service_key": "mootion_movie",
                "summary": "Demo movie",
                "body_text": "Demo movie",
                "mime_type": "text/html",
                "viewer_kind": "html",
                "asset_relpath": "asset.html",
                "hosted_url": "https://ea.example/results/movie-demo",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_ENABLE_PUBLIC_RESULTS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_TOURS", "0")
    monkeypatch.setenv("EA_PUBLIC_RESULT_DIR", str(result_dir))

    client = _client(principal_id="exec-public-result-only")

    assert client.get("/results/movie-demo").status_code == 200
    assert client.get("/tours/movie-demo").status_code == 404


def test_onemin_manager_binding_overlay_and_occupancy_are_principal_scoped() -> None:
    from types import SimpleNamespace

    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    provider_health = {
        "providers": {
            "onemin": {
                "slots": [
                    {
                        "account_name": "ONEMIN_AI_API_KEY",
                        "slot_env_name": "ONEMIN_AI_API_KEY",
                        "slot": "primary",
                        "slot_name": "primary",
                        "credential_id": "primary",
                        "state": "ready",
                        "estimated_remaining_credits": 15000,
                    }
                ]
            }
        }
    }
    binding = SimpleNamespace(
        binding_id="binding-1",
        auth_metadata_json={"slot_env_name": "ONEMIN_AI_API_KEY"},
        external_account_ref="",
    )

    first_view = manager.accounts_snapshot(provider_health=provider_health, binding_rows=[binding])
    assert first_view[0]["browseract_binding_ids"] == ["binding-1"]

    second_view = manager.accounts_snapshot(provider_health=provider_health, binding_rows=[])
    assert second_view[0]["browseract_binding_ids"] == []

    aggregate = manager.aggregate_snapshot(provider_health=provider_health, binding_rows=[], principal_id="exec-2")
    assert aggregate["bound_account_count"] == 0
    assert aggregate["bound_actual_free_credits_total"] == 0

    lease = manager.reserve_for_candidates(
        candidates=[
            {
                "account_name": "ONEMIN_AI_API_KEY",
                "account_id": "ONEMIN_AI_API_KEY",
                "slot_name": "primary",
                "credential_id": "primary",
                "secret_env_name": "ONEMIN_AI_API_KEY",
                "state": "ready",
                "estimated_remaining_credits": 15000,
                "api_key": "test-key",
            }
        ],
        lane="core",
        capability="code_generate",
        principal_id="exec-1",
        request_id="req-1",
        estimated_credits=50,
        allow_reserve=False,
    )
    assert lease is not None
    assert manager.occupancy_snapshot(principal_id="exec-1")["active_lease_count"] == 1


def test_onemin_manager_does_not_count_unparsed_page_views_as_actual_billing() -> None:
    from types import SimpleNamespace

    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    provider_health = {
        "providers": {
            "onemin": {
                "slots": [
                    {
                        "account_name": "ONEMIN_AI_API_KEY",
                        "slot_env_name": "ONEMIN_AI_API_KEY",
                        "slot": "primary",
                        "slot_name": "primary",
                        "credential_id": "primary",
                        "state": "ready",
                        "estimated_remaining_credits": 15572,
                        "billing_basis": "page_seen_but_unparsed",
                        "last_billing_snapshot_at": "2026-03-27T21:24:46Z",
                    }
                ]
            }
        }
    }
    binding = SimpleNamespace(
        binding_id="binding-1",
        auth_metadata_json={"slot_env_name": "ONEMIN_AI_API_KEY"},
        external_account_ref="",
    )

    aggregate = manager.aggregate_snapshot(provider_health=provider_health, binding_rows=[], principal_id="")
    actual = manager.actual_credits_snapshot(provider_health=provider_health, binding_rows=[binding], principal_id="exec-1")

    assert aggregate["actual_billing_account_count"] == 0
    assert aggregate["actual_free_credits_total"] == 0
    assert aggregate["account_count"] == 1
    assert actual["actual_billing_account_count"] == 0
    assert actual["binding_account_count"] == 1
    assert actual["accounts_without_actual_billing_count"] == 1
    assert manager.occupancy_snapshot(principal_id="exec-2")["active_lease_count"] == 0


def test_onemin_manager_reserve_for_candidates_prefers_persisted_actual_credits() -> None:
    from app.domain.models import OneminAccount, OneminCredential
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    repo = InMemoryOneminManagerRepository()
    manager = OneminManagerService(repo=repo)
    repo.replace_state(
        accounts=[
            OneminAccount(
                account_id="ONEMIN_AI_API_KEY_FALLBACK_60",
                account_label="ONEMIN_AI_API_KEY_FALLBACK_60",
                status="ready",
                remaining_credits=1049,
                max_credits=15000,
                details_json={
                    "credit_basis": "actual_billing_usage_page",
                    "has_actual_billing": True,
                    "actual_remaining_credits": 1049.0,
                    "actual_max_credits": 15000.0,
                },
            ),
            OneminAccount(
                account_id="ONEMIN_AI_API_KEY_FALLBACK_61",
                account_label="ONEMIN_AI_API_KEY_FALLBACK_61",
                status="ready",
                remaining_credits=40000,
                max_credits=15000,
                details_json={
                    "credit_basis": "actual_billing_usage_page",
                    "has_actual_billing": True,
                    "actual_remaining_credits": 40000.0,
                    "actual_max_credits": 15000.0,
                },
            ),
        ],
        credentials=[
            OneminCredential(
                credential_id="fallback_60",
                account_id="ONEMIN_AI_API_KEY_FALLBACK_60",
                slot_name="fallback_60",
                secret_env_name="ONEMIN_AI_API_KEY_FALLBACK_60",
                state="ready",
                remaining_credits=1049,
            ),
            OneminCredential(
                credential_id="fallback_61",
                account_id="ONEMIN_AI_API_KEY_FALLBACK_61",
                slot_name="fallback_61",
                secret_env_name="ONEMIN_AI_API_KEY_FALLBACK_61",
                state="ready",
                remaining_credits=40000,
            ),
        ],
    )

    lease = manager.reserve_for_candidates(
        candidates=[
            {
                "account_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
                "account_id": "ONEMIN_AI_API_KEY_FALLBACK_60",
                "slot_name": "fallback_60",
                "credential_id": "fallback_60",
                "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
                "state": "ready",
                "estimated_remaining_credits": 5000000,
                "api_key": "low-key",
            },
            {
                "account_name": "ONEMIN_AI_API_KEY_FALLBACK_61",
                "account_id": "ONEMIN_AI_API_KEY_FALLBACK_61",
                "slot_name": "fallback_61",
                "credential_id": "fallback_61",
                "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_61",
                "state": "ready",
                "estimated_remaining_credits": None,
                "api_key": "high-key",
            },
        ],
        lane="core",
        capability="code_generate",
        principal_id="exec-1",
        request_id="req-actual-credits",
        estimated_credits=25662,
        allow_reserve=False,
    )

    assert lease is not None
    assert lease["account_name"] == "ONEMIN_AI_API_KEY_FALLBACK_61"
    assert lease["api_key"] == "high-key"


def test_onemin_manager_keeps_unknown_budget_candidates_eligible_when_known_budget_is_insufficient() -> None:
    from app.domain.models import OneminAccount, OneminCredential
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    repo = InMemoryOneminManagerRepository()
    manager = OneminManagerService(repo=repo)
    repo.replace_state(
        accounts=[
            OneminAccount(
                account_id="ONEMIN_AI_API_KEY_FALLBACK_60",
                account_label="ONEMIN_AI_API_KEY_FALLBACK_60",
                status="ready",
                remaining_credits=1049,
                max_credits=15000,
                details_json={
                    "credit_basis": "actual_billing_usage_page",
                    "has_actual_billing": True,
                    "actual_remaining_credits": 1049.0,
                    "actual_max_credits": 15000.0,
                },
            )
        ],
        credentials=[
            OneminCredential(
                credential_id="fallback_60",
                account_id="ONEMIN_AI_API_KEY_FALLBACK_60",
                slot_name="fallback_60",
                secret_env_name="ONEMIN_AI_API_KEY_FALLBACK_60",
                state="ready",
                remaining_credits=1049,
            )
        ],
    )

    lease = manager.reserve_for_candidates(
        candidates=[
            {
                "account_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
                "account_id": "ONEMIN_AI_API_KEY_FALLBACK_60",
                "slot_name": "fallback_60",
                "credential_id": "fallback_60",
                "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
                "state": "ready",
                "estimated_remaining_credits": 5000000,
                "api_key": "low-key",
            },
            {
                "account_name": "ONEMIN_AI_API_KEY_FALLBACK_62",
                "account_id": "ONEMIN_AI_API_KEY_FALLBACK_62",
                "slot_name": "fallback_62",
                "credential_id": "fallback_62",
                "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_62",
                "state": "ready",
                "estimated_remaining_credits": None,
                "api_key": "unknown-key",
            },
        ],
        lane="core",
        capability="code_generate",
        principal_id="exec-1",
        request_id="req-unknown-budget",
        estimated_credits=25662,
        allow_reserve=False,
    )

    assert lease is not None
    assert lease["account_name"] == "ONEMIN_AI_API_KEY_FALLBACK_62"
    assert lease["api_key"] == "unknown-key"


def test_onemin_manager_budget_limited_quarantine_only_blocks_requests_above_observed_remaining() -> None:
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    candidate = {
        "account_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
        "account_id": "ONEMIN_AI_API_KEY_FALLBACK_60",
        "slot_name": "fallback_60",
        "credential_id": "fallback_60",
        "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
        "state": "quarantine",
        "remaining_credits": 1650,
        "estimated_remaining_credits": 1650,
        "billing_remaining_credits": 4_200_000,
        "last_error": "INSUFFICIENT_CREDITS:The feature requires 57451 credits, but the Finland Office team only has 1650 credits",
        "api_key": "budget-key",
    }

    lease = manager.reserve_for_candidates(
        candidates=[candidate],
        lane="core",
        capability="code_generate",
        principal_id="exec-1",
        request_id="req-budget-recovery",
        estimated_credits=1200,
        allow_reserve=False,
    )

    assert lease is not None
    assert lease["api_key"] == "budget-key"
    manager.release_lease(lease_id=str(lease["lease_id"]))

    oversized = manager.reserve_for_candidates(
        candidates=[candidate],
        lane="core",
        capability="code_generate",
        principal_id="exec-1",
        request_id="req-budget-too-large",
        estimated_credits=50000,
        allow_reserve=False,
    )

    assert oversized is None


def test_onemin_manager_probe_ok_allows_billing_backed_budget_override() -> None:
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    candidate = {
        "account_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
        "account_id": "ONEMIN_AI_API_KEY_FALLBACK_60",
        "slot_name": "fallback_60",
        "credential_id": "fallback_60",
        "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
        "state": "quarantine",
        "remaining_credits": 1650,
        "estimated_remaining_credits": 1650,
        "billing_remaining_credits": 4_200_000,
        "billing_max_credits": 4_450_000,
        "billing_basis": "actual_provider_api",
        "last_probe_result": "ok",
        "last_error": "INSUFFICIENT_CREDITS:The feature requires 73111 credits, but the Finland Office team only has 1650 credits",
        "api_key": "probe-ok-key",
    }

    lease = manager.reserve_for_candidates(
        candidates=[candidate],
        lane="core",
        capability="code_generate",
        principal_id="exec-1",
        request_id="req-probe-ok-budget-override",
        estimated_credits=73111,
        allow_reserve=False,
    )

    assert lease is not None
    assert lease["api_key"] == "probe-ok-key"


def test_onemin_manager_probe_ok_does_not_trust_mismatched_billing_override() -> None:
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    candidate = {
        "account_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
        "account_id": "ONEMIN_AI_API_KEY_FALLBACK_60",
        "slot_name": "fallback_60",
        "credential_id": "fallback_60",
        "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
        "state": "quarantine",
        "remaining_credits": 1650,
        "estimated_remaining_credits": 1650,
        "billing_remaining_credits": 4_200_000,
        "billing_max_credits": 4_450_000,
        "billing_basis": "actual_provider_api",
        "billing_team_mismatch": True,
        "last_probe_result": "ok",
        "last_error": "INSUFFICIENT_CREDITS:The feature requires 73111 credits, but the Finland Office team only has 1650 credits",
        "api_key": "probe-ok-key",
    }

    lease = manager.reserve_for_candidates(
        candidates=[candidate],
        lane="core",
        capability="code_generate",
        principal_id="exec-1",
        request_id="req-probe-ok-mismatch",
        estimated_credits=73111,
        allow_reserve=False,
    )

    assert lease is None


def test_onemin_manager_probe_ok_billing_override_does_not_mask_zero_live_balance() -> None:
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    candidates = [
        {
            "account_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
            "account_id": "ONEMIN_AI_API_KEY_FALLBACK_60",
            "slot_name": "fallback_60",
            "credential_id": "fallback_60",
            "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
            "state": "degraded",
            "remaining_credits": 0,
            "estimated_remaining_credits": 0,
            "billing_remaining_credits": 4_200_000,
            "billing_max_credits": 4_450_000,
            "billing_basis": "actual_provider_api",
            "last_probe_result": "ok",
            "last_error": "INSUFFICIENT_CREDITS:The feature requires 1877 credits, but the team only has 0 credits",
            "api_key": "zero-live-key",
        },
        {
            "account_name": "ONEMIN_AI_API_KEY_FALLBACK_61",
            "account_id": "ONEMIN_AI_API_KEY_FALLBACK_61",
            "slot_name": "fallback_61",
            "credential_id": "fallback_61",
            "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_61",
            "state": "quarantine",
            "remaining_credits": 1650,
            "estimated_remaining_credits": 1650,
            "billing_remaining_credits": 4_200_000,
            "billing_max_credits": 4_450_000,
            "billing_basis": "actual_provider_api",
            "last_error": "INSUFFICIENT_CREDITS:The feature requires 1726 credits, but the team only has 1650 credits",
            "api_key": "positive-live-key",
        },
    ]

    lease = manager.reserve_for_candidates(
        candidates=candidates,
        lane="core",
        capability="code_generate",
        principal_id="exec-1",
        request_id="req-zero-live-mask",
        estimated_credits=699,
        allow_reserve=False,
    )

    assert lease is not None
    assert lease["api_key"] == "positive-live-key"


def test_onemin_manager_prefers_exact_live_budget_before_billing_backed_recovery() -> None:
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    candidates = [
        {
            "account_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
            "account_id": "ONEMIN_AI_API_KEY_FALLBACK_60",
            "slot_name": "fallback_60",
            "credential_id": "fallback_60",
            "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
            "state": "quarantine",
            "remaining_credits": 1650,
            "estimated_remaining_credits": 1650,
            "billing_remaining_credits": 4_200_000,
            "billing_max_credits": 4_450_000,
            "billing_basis": "actual_provider_api",
            "last_error": "INSUFFICIENT_CREDITS:The feature requires 57451 credits, but the team only has 1650 credits",
            "last_probe_result": "ok",
            "api_key": "billing-recovery-key",
        },
        {
            "account_name": "ONEMIN_AI_API_KEY_FALLBACK_61",
            "account_id": "ONEMIN_AI_API_KEY_FALLBACK_61",
            "slot_name": "fallback_61",
            "credential_id": "fallback_61",
            "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_61",
            "state": "ready",
            "remaining_credits": 2400,
            "estimated_remaining_credits": 2400,
            "api_key": "exact-live-key",
        },
    ]

    lease = manager.reserve_for_candidates(
        candidates=candidates,
        lane="core",
        capability="code_generate",
        principal_id="exec-1",
        request_id="req-exact-live-preferred",
        estimated_credits=699,
        allow_reserve=False,
    )

    assert lease is not None
    assert lease["api_key"] == "exact-live-key"


def test_onemin_manager_uses_billing_backed_recovery_after_new_success_or_billing_snapshot() -> None:
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    now = time.time()
    lease = manager.reserve_for_candidates(
        candidates=[
            {
                "account_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
                "account_id": "ONEMIN_AI_API_KEY_FALLBACK_60",
                "slot_name": "fallback_60",
                "credential_id": "fallback_60",
                "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
                "state": "quarantine",
                "remaining_credits": 1650,
                "estimated_remaining_credits": 1650,
                "billing_remaining_credits": 4_200_000,
                "billing_max_credits": 4_450_000,
                "billing_basis": "actual_provider_api",
                "last_error": "INSUFFICIENT_CREDITS:The feature requires 57451 credits, but the team only has 1650 credits",
                "last_failure_at": now - 600,
                "last_success_at": now - 60,
                "api_key": "recent-success-key",
            },
            {
                "account_name": "ONEMIN_AI_API_KEY_FALLBACK_61",
                "account_id": "ONEMIN_AI_API_KEY_FALLBACK_61",
                "slot_name": "fallback_61",
                "credential_id": "fallback_61",
                "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_61",
                "state": "quarantine",
                "remaining_credits": 1650,
                "estimated_remaining_credits": 1650,
                "billing_remaining_credits": 4_200_000,
                "billing_max_credits": 4_450_000,
                "billing_basis": "actual_provider_api",
                "last_error": "INSUFFICIENT_CREDITS:The feature requires 57451 credits, but the team only has 1650 credits",
                "last_failure_at": now - 600,
                "last_billing_snapshot_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 30)),
                "api_key": "fresh-billing-key",
            },
        ],
        lane="core",
        capability="code_generate",
        principal_id="exec-1",
        request_id="req-billing-recovery",
        estimated_credits=50000,
        allow_reserve=False,
    )

    assert lease is not None
    assert lease["api_key"] in {"recent-success-key", "fresh-billing-key"}


def test_onemin_manager_uses_fresh_billing_snapshot_to_override_older_depleted_probe() -> None:
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    lease = manager.reserve_for_candidates(
        candidates=[
            {
                "account_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
                "account_id": "ONEMIN_AI_API_KEY_FALLBACK_60",
                "slot_name": "fallback_60",
                "credential_id": "fallback_60",
                "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
                "state": "ready",
                "remaining_credits": 0,
                "estimated_remaining_credits": 0,
                "billing_remaining_credits": 4_255_550,
                "billing_max_credits": 4_450_000,
                "billing_basis": "actual_provider_api",
                "last_probe_result": "depleted",
                "last_error": "INSUFFICIENT_CREDITS:The feature requires 1726 credits, but the team only has 0 credits",
                "last_probe_at": 1000.0,
                "last_billing_snapshot_at": "2026-04-30T14:23:21Z",
                "api_key": "fresh-billing-key",
            },
            {
                "account_name": "ONEMIN_AI_API_KEY_FALLBACK_61",
                "account_id": "ONEMIN_AI_API_KEY_FALLBACK_61",
                "slot_name": "fallback_61",
                "credential_id": "fallback_61",
                "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_61",
                "state": "ready",
                "remaining_credits": 0,
                "estimated_remaining_credits": 0,
                "billing_remaining_credits": 4_255_550,
                "billing_max_credits": 4_450_000,
                "billing_basis": "actual_provider_api",
                "last_probe_result": "depleted",
                "last_error": "INSUFFICIENT_CREDITS:The feature requires 1726 credits, but the team only has 0 credits",
                "last_probe_at": 2000.0,
                "last_billing_snapshot_at": "1970-01-01T00:00:01Z",
                "api_key": "stale-billing-key",
            },
        ],
        lane="core",
        capability="code_generate",
        principal_id="exec-1",
        request_id="req-fresh-billing-overrides-stale-probe",
        estimated_credits=1726,
        allow_reserve=False,
    )

    assert lease is not None
    assert lease["api_key"] == "fresh-billing-key"


def test_onemin_manager_candidate_repo_state_preserves_zero_live_estimate_over_persisted_billing() -> None:
    from app.domain.models import OneminAccount, OneminCredential
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    repo = InMemoryOneminManagerRepository()
    manager = OneminManagerService(repo=repo)
    repo.replace_state(
        accounts=[
            OneminAccount(
                account_id="ONEMIN_AI_API_KEY_FALLBACK_48",
                account_label="ONEMIN_AI_API_KEY_FALLBACK_48",
                status="ready",
                remaining_credits=16169,
                max_credits=16169,
                details_json={
                    "credit_basis": "actual_provider_api",
                    "has_actual_billing": True,
                    "actual_remaining_credits": 16169.0,
                    "actual_max_credits": 16169.0,
                    "estimated_remaining_credits": 0.0,
                },
            )
        ],
        credentials=[
            OneminCredential(
                credential_id="fallback_48",
                account_id="ONEMIN_AI_API_KEY_FALLBACK_48",
                slot_name="fallback_48",
                secret_env_name="ONEMIN_AI_API_KEY_FALLBACK_48",
                state="ready",
                remaining_credits=16169,
            )
        ],
    )

    candidate = {
        "account_name": "ONEMIN_AI_API_KEY_FALLBACK_48",
        "account_id": "ONEMIN_AI_API_KEY_FALLBACK_48",
        "slot_name": "fallback_48",
        "credential_id": "fallback_48",
        "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_48",
        "state": "ready",
        "remaining_credits": None,
        "estimated_remaining_credits": 0,
        "billing_remaining_credits": 16169,
        "billing_max_credits": 16169,
        "billing_basis": "actual_provider_api",
        "last_probe_result": "depleted",
        "last_probe_detail": "INSUFFICIENT_CREDITS:The feature requires 1726 credits, but the team only has 1049 credits",
        "api_key": "zero-estimate-key",
    }

    lease = manager.reserve_for_candidates(
        candidates=[candidate],
        lane="core",
        capability="code_generate",
        principal_id="exec-1",
        request_id="req-preserve-zero-estimate",
        estimated_credits=699,
        allow_reserve=False,
    )

    assert lease is None


def test_onemin_manager_actual_snapshot_ignores_mismatched_actual_billing() -> None:
    from types import SimpleNamespace

    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    provider_health = {
        "providers": {
            "onemin": {
                "slots": [
                    {
                        "account_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
                        "slot_env_name": "ONEMIN_AI_API_KEY_FALLBACK_60",
                        "slot": "fallback_60",
                        "slot_name": "fallback_60",
                        "credential_id": "fallback_60",
                        "state": "degraded",
                        "remaining_credits": 1650,
                        "estimated_remaining_credits": 1650,
                        "estimated_credit_basis": "observed_error",
                        "billing_remaining_credits": 4_200_000,
                        "billing_max_credits": 4_450_000,
                        "billing_basis": "actual_provider_api",
                        "billing_team_name": "Aziliz Tanguy",
                        "billing_team_mismatch": True,
                        "billing_team_match_subject": "Finland Office team",
                    }
                ]
            }
        }
    }
    binding = SimpleNamespace(
        binding_id="binding-1",
        auth_metadata_json={"slot_env_name": "ONEMIN_AI_API_KEY_FALLBACK_60"},
        external_account_ref="",
    )

    actual = manager.actual_credits_snapshot(provider_health=provider_health, binding_rows=[binding], principal_id="exec-1")
    accounts = manager.accounts_snapshot(provider_health=provider_health, binding_rows=[binding], principal_id="exec-1")

    assert actual["actual_billing_account_count"] == 0
    assert actual["actual_free_credits_total"] == 0
    assert actual["accounts_without_actual_billing_count"] == 1
    assert accounts[0]["has_actual_billing"] is False
    assert accounts[0]["actual_remaining_credits"] is None
    assert accounts[0]["estimated_remaining_credits"] == 1650
    assert accounts[0]["credit_basis"] == "observed_error"


def test_onemin_manager_non_authoritative_provider_health_does_not_block_persisted_ready_account() -> None:
    from app.domain.models import OneminAccount, OneminCredential
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    manager._repo.replace_state(
        accounts=[
            OneminAccount(
                account_id="ONEMIN_AI_API_KEY_FALLBACK_1",
                account_label="ONEMIN_AI_API_KEY_FALLBACK_1",
                status="ready",
                remaining_credits=40000,
                max_credits=15000,
                last_billing_snapshot_at="2026-04-28T08:30:00Z",
                details_json={
                    "credit_basis": "actual_billing_usage_page",
                    "has_actual_billing": True,
                    "actual_remaining_credits": 40000.0,
                    "actual_max_credits": 15000.0,
                },
            )
        ],
        credentials=[
            OneminCredential(
                credential_id="fallback_1",
                account_id="ONEMIN_AI_API_KEY_FALLBACK_1",
                slot_name="fallback_1",
                secret_env_name="ONEMIN_AI_API_KEY_FALLBACK_1",
                state="ready",
                remaining_credits=40000,
            )
        ],
    )
    candidate = {
        "account_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
        "account_id": "ONEMIN_AI_API_KEY_FALLBACK_1",
        "slot_name": "fallback_1",
        "credential_id": "fallback_1",
        "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
        "state": "quarantine",
        "slot_role": "active",
        "remaining_credits": 0,
        "estimated_remaining_credits": 0,
        "billing_remaining_credits": 0,
        "last_probe_result": "depleted",
        "api_key": "high-key",
    }
    provider_health = {
        "providers": {
            "onemin": {
                "slots": [candidate],
            }
        }
    }

    lease = manager.reserve_for_candidates(
        candidates=[candidate],
        lane="core",
        capability="code_generate",
        principal_id="exec-1",
        request_id="req-non-authoritative-provider-health",
        estimated_credits=25662,
        allow_reserve=False,
        provider_health=provider_health,
    )

    assert lease is not None
    assert lease["api_key"] == "high-key"
    assert lease["account_name"] == "ONEMIN_AI_API_KEY_FALLBACK_1"


def test_refresh_onemin_api_account_uses_credit_subject_hint_to_select_matching_team(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import providers as providers_route

    requested_urls: list[str] = []

    monkeypatch.setattr(
        providers_route,
        "_onemin_api_login",
        lambda **_: {
            "token": "session-token",
            "teams": [
                {"teamId": "team-wrong", "team": {"uuid": "team-wrong", "name": "Aziliz Tanguy"}},
                {"teamId": "team-right", "team": {"uuid": "team-right", "name": "Finland Office"}},
            ],
        },
    )

    def fake_get_json(*, url: str, headers: dict[str, str], timeout_seconds: int) -> dict[str, object]:
        requested_urls.append(url)
        assert headers["X-Auth-Token"] == "Bearer session-token"
        if url.endswith("/topups"):
            return {"topupList": []}
        if url.endswith("/usages"):
            return {"usageList": []}
        if url.endswith("/invoices"):
            return {"invoiceList": []}
        raise AssertionError(url)

    monkeypatch.setattr(providers_route, "_onemin_api_get_json", fake_get_json)
    monkeypatch.setattr(
        providers_route.upstream,
        "onemin_credit_subject_hint_for_account",
        lambda *, account_name: {"credit_subject": "Finland Office team"} if account_name == "ONEMIN_AI_API_KEY_FALLBACK_60" else {},
    )
    monkeypatch.setattr(
        providers_route.upstream,
        "_latest_provider_billing_snapshot",
        lambda **_: None,
        raising=False,
    )
    monkeypatch.setattr(
        providers_route.upstream,
        "record_onemin_billing_snapshot",
        lambda **kwargs: dict(kwargs["snapshot_json"]),
    )

    billing_result, member_result = providers_route._refresh_onemin_api_account(
        account_name="ONEMIN_AI_API_KEY_FALLBACK_60",
        owner_email="owner@example.com",
        include_members=False,
        timeout_seconds=120,
    )

    assert member_result is None
    assert billing_result["team_id"] == "team-right"
    assert billing_result["structured_output_json"]["team_name"] == "Finland Office"
    assert billing_result["structured_output_json"]["team_selection"]["reason"] == "credit_subject_hint"
    assert all("/team-right/" in url for url in requested_urls)


def test_refresh_onemin_api_account_prefers_configured_team_id_over_credit_subject_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import providers as providers_route

    requested_urls: list[str] = []

    monkeypatch.setattr(
        providers_route,
        "_onemin_api_login",
        lambda **_: {
            "token": "session-token",
            "teams": [
                {"teamId": "team-wrong", "team": {"uuid": "team-wrong", "name": "Finland Office"}},
                {"teamId": "team-right", "team": {"uuid": "team-right", "name": "Saga Silfverberg"}},
            ],
        },
    )

    def fake_get_json(*, url: str, headers: dict[str, str], timeout_seconds: int) -> dict[str, object]:
        requested_urls.append(url)
        assert headers["X-Auth-Token"] == "Bearer session-token"
        if url.endswith("/topups"):
            return {"topupList": []}
        if url.endswith("/usages"):
            return {"usageList": []}
        if url.endswith("/invoices"):
            return {"invoiceList": []}
        raise AssertionError(url)

    monkeypatch.setattr(providers_route, "_onemin_api_get_json", fake_get_json)
    monkeypatch.setattr(
        providers_route.upstream,
        "onemin_credit_subject_hint_for_account",
        lambda *, account_name: {"credit_subject": "Finland Office team"} if account_name == "ONEMIN_AI_API_KEY_FALLBACK_60" else {},
    )
    monkeypatch.setattr(
        providers_route.upstream,
        "_latest_provider_billing_snapshot",
        lambda **_: None,
        raising=False,
    )
    monkeypatch.setattr(
        providers_route.upstream,
        "record_onemin_billing_snapshot",
        lambda **kwargs: dict(kwargs["snapshot_json"]),
    )

    billing_result, member_result = providers_route._refresh_onemin_api_account(
        account_name="ONEMIN_AI_API_KEY_FALLBACK_60",
        owner_email="owner@example.com",
        include_members=False,
        timeout_seconds=120,
        preferred_team_id="team-right",
    )

    assert member_result is None
    assert billing_result["team_id"] == "team-right"
    assert billing_result["structured_output_json"]["team_name"] == "Saga Silfverberg"
    assert billing_result["structured_output_json"]["team_selection"]["reason"] == "configured_team_id"
    assert all("/team-right/" in url for url in requested_urls)


def test_operator_can_record_onemin_billing_snapshot_into_live_manager_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(tmp_path))
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_54", "business-54")

    owner = _client(principal_id="codex-fleet", operator=True)

    recorded = owner.post(
        "/v1/providers/onemin/billing-snapshots",
        json={
            "account_label": "ONEMIN_AI_API_KEY_FALLBACK_54",
            "source": "browseract.onemin_billing_usage.fastestvpn_refresh",
            "snapshot_json": {
                "observed_at": "2026-04-04T08:24:48Z",
                "remaining_credits": 4280000,
                "max_credits": 4280000,
                "basis": "actual_billing_usage_page",
                "source_url": "https://app.1min.ai/billing-usage",
                "structured_output_json": {
                    "billing_overview_json": {
                        "plan_name": "BUSINESS",
                        "billing_cycle": "LIFETIME",
                        "subscription_status": "Active",
                    }
                },
            },
        },
    )

    assert recorded.status_code == 200
    body = recorded.json()
    assert body["snapshot"]["account_name"] == "ONEMIN_AI_API_KEY_FALLBACK_54"
    assert body["snapshot"]["remaining_credits"] == 4280000.0
    assert body["account_snapshot"]["account_id"] == "ONEMIN_AI_API_KEY_FALLBACK_54"
    assert body["account_snapshot"]["actual_remaining_credits"] == 4280000.0
    assert body["account_snapshot"]["credit_basis"] == "actual_billing_usage_page"
    assert body["account_snapshot"]["has_actual_billing"] is True
    assert body["aggregate_snapshot"]["sum_free_credits"] == 4280000.0
    assert body["aggregate_snapshot"]["actual_free_credits_total"] == 4280000.0
    assert body["aggregate_snapshot"]["actual_billing_account_count"] == 1

    aggregate = owner.get("/v1/providers/onemin/aggregate?scope=global")
    assert aggregate.status_code == 200
    aggregate_body = aggregate.json()
    assert aggregate_body["sum_free_credits"] == 4280000.0
    assert aggregate_body["actual_free_credits_total"] == 4280000.0
    assert aggregate_body["actual_billing_account_count"] == 1


def test_onemin_image_reservation_and_release_are_principal_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _client(principal_id="exec-image", operator=True)
    from app.api.routes import providers as providers_route

    monkeypatch.setattr(
        providers_route.upstream,
        "_provider_health_report",
        lambda: {
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY_FALLBACK_22",
                            "slot_env_name": "ONEMIN_AI_API_KEY_FALLBACK_22",
                            "slot": "fallback_22",
                            "slot_name": "fallback_22",
                            "credential_id": "fallback_22",
                            "state": "ready",
                            "estimated_remaining_credits": 24000,
                            "slot_role": "image",
                        }
                    ]
                }
            }
        },
    )

    reserved = owner.post("/v1/providers/onemin/reserve-image", json={"estimated_credits": 900})
    assert reserved.status_code == 200
    reserved_body = reserved.json()
    assert reserved_body["principal_id"] == "exec-image"
    assert reserved_body["secret_env_name"] == "ONEMIN_AI_API_KEY_FALLBACK_22"
    lease_id = reserved_body["lease_id"]

    occupancy = owner.get("/v1/providers/onemin/occupancy")
    assert occupancy.status_code == 200
    assert occupancy.json()["active_lease_count"] == 1

    foreign = owner.post(
        f"/v1/providers/onemin/leases/{lease_id}/release",
        json={"status": "released"},
        headers={"X-EA-Principal-ID": "exec-foreign"},
    )
    assert foreign.status_code == 404

    released = owner.post(
        f"/v1/providers/onemin/leases/{lease_id}/release",
        json={"status": "released", "actual_credits_delta": 900},
    )
    assert released.status_code == 200
    assert released.json()["actual_credits_delta"] == 900


def test_onemin_aggregate_exposes_media_and_core_lease_breakout() -> None:
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    provider_health = {
        "providers": {
            "onemin": {
                "slots": [
                    {
                        "account_name": "ONEMIN_AI_API_KEY",
                        "slot_env_name": "ONEMIN_AI_API_KEY",
                        "slot": "primary",
                        "slot_name": "primary",
                        "credential_id": "primary",
                        "state": "ready",
                        "estimated_remaining_credits": 15000,
                        "slot_role": "mixed",
                    }
                ]
            }
        }
    }

    image = manager.reserve_for_provider_health(
        provider_health=provider_health,
        lane="image",
        capability="image_generate",
        principal_id="exec-image",
        request_id="img-1",
        estimated_credits=800,
        allow_reserve=False,
    )
    assert image is not None
    manager.record_usage(lease_id=str(image["lease_id"]), actual_credits_delta=800, status="success")
    manager.release_lease(lease_id=str(image["lease_id"]), status="released")

    core = manager.reserve_for_provider_health(
        provider_health=provider_health,
        lane="core",
        capability="code_generate",
        principal_id="exec-core",
        request_id="core-1",
        estimated_credits=300,
        allow_reserve=False,
    )
    assert core is not None

    aggregate = manager.aggregate_snapshot(provider_health=provider_health, binding_rows=[], principal_id="exec-core")
    assert aggregate["active_image_generation_lease_count"] == 0
    assert aggregate["active_core_code_lease_count"] == 1
    assert aggregate["lease_actual_credits_by_task_class"]["image_generation"] == 800.0
