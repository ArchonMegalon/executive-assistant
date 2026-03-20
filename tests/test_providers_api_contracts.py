from __future__ import annotations

import hashlib
import json
import os
import urllib.parse

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client(*, principal_id: str) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    os.environ["EA_API_TOKEN"] = ""
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


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


def test_browser_landing_exposes_google_onboarding_and_html_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://ea.example/v1/providers/google/oauth/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "provider-secret-key")

    owner = _client(principal_id="exec-browser")

    landing = owner.get("/")
    assert landing.status_code == 200
    assert "Executive Assistant" in landing.text
    assert "Connect Google" in landing.text

    started = owner.post(
        "/google/connect",
        data={"principal_id": "exec-browser", "scope_bundle": "send", "api_token": ""},
        follow_redirects=False,
    )
    assert started.status_code == 303
    location = started.headers["location"]
    assert "https://accounts.google.com/o/oauth2/v2/auth" in location
    parsed = urllib.parse.urlparse(location)
    query = urllib.parse.parse_qs(parsed.query)
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
            "email": "browser@gmail.example",
            "hd": "gmail.example",
        },
    )

    callback = owner.get("/google/callback", params={"code": "code-123", "state": state})
    assert callback.status_code == 200
    assert "Google Connected" in callback.text
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
    assert "Signed in via Cloudflare Access" in landing.text
    assert "browser@gmail.com" in landing.text
    assert "own assistant" in landing.text

    started = owner.post(
        "/google/connect",
        data={"scope_bundle": "send"},
        follow_redirects=False,
    )
    assert started.status_code == 303
    parsed = urllib.parse.urlparse(started.headers["location"])
    query = urllib.parse.parse_qs(parsed.query)
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
    assert "Google Connected" in callback.text
    assert "cf-email:browser@gmail.com" in callback.text


def test_provider_bindings_reject_cross_principal_query_scope() -> None:
    owner = _client(principal_id="exec-1")
    response = owner.get("/v1/providers/bindings?principal_id=exec-2")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "principal_scope_mismatch"


def test_onemin_probe_all_endpoint_returns_slot_results(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _client(principal_id="exec-1")
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
    owner = _client(principal_id="exec-1")
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


def test_onemin_billing_refresh_uses_direct_api_when_no_browseract_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _client(principal_id="exec-1")
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

    response = owner.post("/v1/providers/onemin/billing-refresh", json={"include_members": True})
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


def test_provider_registry_endpoint_exposes_lane_backend_and_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _client(principal_id="exec-1")

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
