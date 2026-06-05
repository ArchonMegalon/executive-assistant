from __future__ import annotations

import json
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from tests.product_test_helpers import start_workspace


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.delenv("EA_LEDGER_BACKEND", raising=False)
    monkeypatch.setenv("EA_API_TOKEN", "")
    monkeypatch.setenv("EA_RUNTIME_MODE", "dev")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://propertyquarry.com")
    from app.api.app import create_app

    return TestClient(create_app())


def test_register_start_returns_magic_link_and_local_code_without_email_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EMAILIT_API_KEY", raising=False)
    client = _client(monkeypatch)

    response = client.post("/v1/register/start", json={"email": "Tibor.Girschele@Gmail.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "tibor.girschele@gmail.com"
    assert len(body["verification_code"]) == 6
    assert body["magic_link_url"].startswith("/register?token=")
    assert body["workspace_name"] == "Tibor Girschele"
    assert body["email_delivery_status"] == ""


def test_register_start_uses_absolute_magic_link_when_email_delivery_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    client = _client(monkeypatch)

    from app.api.routes import onboarding as onboarding_route
    from app.services.registration_email import RegistrationEmailReceipt

    observed: dict[str, object] = {}

    def _fake_send_registration_email(**kwargs) -> RegistrationEmailReceipt:
        observed.update(kwargs)
        return RegistrationEmailReceipt(
            provider="emailit",
            message_id="emailit-message-1",
            accepted_at="2026-03-26T00:00:00+00:00",
        )

    monkeypatch.setattr(onboarding_route, "send_registration_email", _fake_send_registration_email)

    response = client.post("/v1/register/start", json={"email": "exec@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["email_delivery_status"] == "sent"
    assert body["email_delivery_provider"] == "emailit"
    assert body["email_delivery_id"] == "emailit-message-1"
    assert observed["recipient_email"] == "exec@example.com"
    assert str(observed["magic_link_url"]).startswith("https://propertyquarry.com/register?token=")


def test_register_start_reports_email_delivery_failure_without_aborting_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    client = _client(monkeypatch)

    from app.api.routes import onboarding as onboarding_route

    monkeypatch.setattr(
        onboarding_route,
        "send_registration_email",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("registration_email_send_failed:422:Domain not verified")),
    )

    response = client.post("/v1/register/start", json={"email": "broken@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "broken@example.com"
    assert body["email_delivery_status"] == "failed"
    assert "Domain not verified" in body["email_delivery_error"]
    assert len(body["verification_code"]) == 6


def test_sign_in_email_link_reissues_workspace_access_for_existing_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    client = _client(monkeypatch)
    start_workspace(client, mode="personal", workspace_name="Founder Office")

    issued = client.post(
        "/app/api/access-sessions",
        json={"email": "founder@example.com", "role": "principal", "display_name": "Founder Office"},
    )
    assert issued.status_code == 200

    from app.product import service as product_service
    from app.services.registration_email import RegistrationEmailReceipt

    observed: dict[str, object] = {}

    def _fake_send_workspace_access_email(**kwargs) -> RegistrationEmailReceipt:
        observed.update(kwargs)
        return RegistrationEmailReceipt(
            provider="emailit",
            message_id="access-message-1",
            accepted_at="2026-03-26T00:00:00+00:00",
        )

    monkeypatch.setattr(product_service, "send_workspace_access_email", _fake_send_workspace_access_email)

    response = client.post(
        "/sign-in/email-link",
        data={"email": "Founder@Example.com"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "link_status=sent" in response.headers["location"]
    assert "link_count=1" in response.headers["location"]
    followup = client.get(response.headers["location"])
    assert followup.status_code == 200
    assert "Secure access links sent." in followup.text
    assert "founder@example.com" in followup.text
    assert observed["recipient_email"] == "founder@example.com"
    assert observed["workspace_name"] == "Founder Office"
    assert str(observed["access_url"]).startswith("https://propertyquarry.com/workspace-access/")


def test_sign_in_email_link_reports_missing_workspace_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    client = _client(monkeypatch)

    response = client.post(
        "/sign-in/email-link",
        data={"email": "unknown@example.com"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "link_status=not_found" in response.headers["location"]
    followup = client.get(response.headers["location"])
    assert followup.status_code == 200
    assert "No existing workspace matched that email." in followup.text


def test_sign_in_page_offers_google_return_path(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/sign-in")

    assert response.status_code == 200
    assert "Continue with Google" in response.text
    assert "Google can reopen an existing workspace with identity-only scope." in response.text


def test_sign_in_google_reopens_existing_workspace_after_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "test-google-client-id")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "test-google-client-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://propertyquarry.com/google/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "test-google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "test-provider-secret-key")
    client = _client(monkeypatch)

    existing_principal = "user-4a1702ea0e8d9ec5"
    client.headers.update({"X-EA-Principal-ID": existing_principal})
    start_workspace(client, mode="personal", workspace_name="Tibor Property Workspace")

    sign_in_start = client.post(
        "/sign-in/google",
        follow_redirects=False,
    )
    assert sign_in_start.status_code == 303
    auth_url = sign_in_start.headers["location"]
    assert auth_url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    parsed = urllib.parse.urlparse(auth_url)
    query = urllib.parse.parse_qs(parsed.query)
    assert query["redirect_uri"][0] == "https://propertyquarry.com/google/callback"

    from app.services import google_oauth as google_service

    monkeypatch.setattr(
        google_service,
        "_exchange_google_code_for_tokens",
        lambda **kwargs: {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "scope": "openid email profile",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        google_service,
        "_fetch_google_userinfo",
        lambda access_token: {
            "sub": "google-sub-signin",
            "email": "tibor.girschele@gmail.com",
        },
    )

    callback = client.get(
        "/google/callback",
        params={"code": "code-123", "state": query["state"][0]},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"].startswith("/workspace-access/")

    opened = client.get(callback.headers["location"], follow_redirects=False)
    assert opened.status_code == 303
    assert opened.headers["location"] == "/app/properties"
    assert "ea_workspace_session=" in str(opened.headers.get("set-cookie") or "")


def test_sign_in_page_does_not_require_email_field_for_google(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/sign-in")

    assert response.status_code == 200
    assert 'action="/sign-in/google"' in response.text
    assert "Continue with Google" in response.text
    assert 'id="google_sign_in_email"' not in response.text
    assert 'placeholder="you@company.com"' not in response.text


def test_register_verify_requires_matching_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMAILIT_API_KEY", raising=False)
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "test-google-client-id")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "test-google-client-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://propertyquarry.com/google/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "test-google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "test-provider-secret-key")
    client = _client(monkeypatch)

    started = client.post("/v1/register/start", json={"email": "verify@example.com"})
    assert started.status_code == 200
    body = started.json()

    missing_code = client.post(
        "/v1/register/verify",
        json={
            "verification_token": body["verification_token"],
            "verification_code": "",
            "workspace_name": "Verify Example",
            "timezone": "Europe/Vienna",
            "language": "en",
        },
    )
    assert missing_code.status_code == 400
    assert missing_code.json()["error"]["code"] == "registration_verification_code_invalid"

    verified = client.post(
        "/v1/register/verify",
        json={
            "verification_token": body["verification_token"],
            "verification_code": body["verification_code"],
            "workspace_name": "Verify Example",
            "timezone": "Europe/Vienna",
            "language": "en",
        },
    )
    assert verified.status_code == 200
    verified_body = verified.json()
    assert verified_body["access_url"].startswith("/workspace-access/")
    google_start = dict(verified_body["google_start"])
    assert google_start["ready"] is True
    assert google_start["auth_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert google_start["start_url"] == google_start["auth_url"]


def test_register_verify_uses_browser_google_callback_even_when_api_callback_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EMAILIT_API_KEY", raising=False)
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "test-google-client-id")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "test-google-client-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://propertyquarry.com/v1/providers/google/oauth/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "test-google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "test-provider-secret-key")
    client = _client(monkeypatch)

    started = client.post("/v1/register/start", json={"email": "browser-callback@example.com"})
    assert started.status_code == 200
    body = started.json()

    verified = client.post(
        "/v1/register/verify",
        json={
            "verification_token": body["verification_token"],
            "verification_code": body["verification_code"],
            "workspace_name": "Browser Callback",
            "timezone": "Europe/Vienna",
            "language": "en",
        },
    )
    assert verified.status_code == 200
    google_start = dict(verified.json()["google_start"])
    parsed = urllib.parse.urlparse(str(google_start["auth_url"]))
    query = urllib.parse.parse_qs(parsed.query)
    assert query["redirect_uri"][0] == "https://propertyquarry.com/google/callback"


def test_register_google_callback_page_signals_original_registration_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMAILIT_API_KEY", raising=False)
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "test-google-client-id")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "test-google-client-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://propertyquarry.com/v1/providers/google/oauth/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "test-google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "test-provider-secret-key")
    client = _client(monkeypatch)

    started = client.post("/v1/register/start", json={"email": "callback-signal@example.com"})
    assert started.status_code == 200
    body = started.json()

    verified = client.post(
        "/v1/register/verify",
        json={
            "verification_token": body["verification_token"],
            "verification_code": body["verification_code"],
            "workspace_name": "Callback Signal",
            "timezone": "Europe/Vienna",
            "language": "en",
        },
    )
    assert verified.status_code == 200
    google_start = dict(verified.json()["google_start"])
    parsed = urllib.parse.urlparse(str(google_start["auth_url"]))
    query = urllib.parse.parse_qs(parsed.query)

    from app.services import google_oauth as google_service

    monkeypatch.setattr(
        google_service,
        "_exchange_google_code_for_tokens",
        lambda **kwargs: {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "scope": (
                "openid email profile "
                "https://www.googleapis.com/auth/gmail.send "
                "https://www.googleapis.com/auth/gmail.metadata "
                "https://www.googleapis.com/auth/calendar.readonly"
            ),
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        google_service,
        "_fetch_google_userinfo",
        lambda access_token: {
            "sub": "google-sub-register",
            "email": "callback-signal@example.com",
            "hd": "example.com",
        },
    )
    monkeypatch.setattr(
        google_service,
        "_refresh_google_access_token",
        lambda **kwargs: {
            "access_token": "fresh-access-token",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(google_service, "_gmail_messages_payload", lambda **kwargs: {})
    monkeypatch.setattr(google_service, "_list_recent_calendar_signals", lambda **kwargs: [])

    callback = client.get("/google/callback", params={"code": "code-123", "state": query["state"][0]})

    assert callback.status_code == 200
    assert "Return to registration" in callback.text
    assert "ea-register-google-connected" in callback.text
    assert "window.location.replace" in callback.text
    assert "google_connected" in callback.text
    assert "Open Properties" in callback.text


def test_register_verify_reports_google_oauth_configuration_hint_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMAILIT_API_KEY", raising=False)
    monkeypatch.delenv("EA_GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("EA_GOOGLE_OAUTH_REDIRECT_URI", raising=False)
    monkeypatch.delenv("EA_GOOGLE_OAUTH_STATE_SECRET", raising=False)
    monkeypatch.delenv("EA_PROVIDER_SECRET_KEY", raising=False)
    client = _client(monkeypatch)

    started = client.post("/v1/register/start", json={"email": "nodev@example.com"})
    assert started.status_code == 200
    body = started.json()

    verified = client.post(
        "/v1/register/verify",
        json={
            "verification_token": body["verification_token"],
            "verification_code": body["verification_code"],
            "workspace_name": "No Dev",
            "timezone": "Europe/Vienna",
            "language": "en",
        },
    )
    assert verified.status_code == 200
    google_start = dict(verified.json()["google_start"])
    assert google_start["ready"] is False
    assert google_start["error"] == "google_oauth_client_id_missing"
    assert "Set EA_GOOGLE_OAUTH_CLIENT_ID and EA_GOOGLE_OAUTH_CLIENT_SECRET." in google_start["detail"]


def test_registration_email_payload_stays_english_and_uses_propertyquarry_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_FROM", "property@propertyquarry.com")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_NAME", "PropertyQuarry")

    from app.services import registration_email as service

    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"id": "emailit-live-1"}).encode("utf-8")

    def _fake_urlopen(request, timeout=0):
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr(service.urllib.request, "urlopen", _fake_urlopen)

    receipt = service.send_registration_email(
        recipient_email="tibor.girschele@gmail.com",
        verification_code="654321",
        magic_link_url="https://propertyquarry.com/register?token=test&code=654321",
        expires_at=2_000_000_000,
    )

    payload = dict(captured["payload"])
    assert payload["from"] == "PropertyQuarry <property@propertyquarry.com>"
    assert payload["subject"] == "Verify your email for PropertyQuarry"
    assert "Use this verification code to create your PropertyQuarry workspace" in payload["text"]
    assert "Google is connected after sign-up as an identity and optional workspace data source for PropertyQuarry." in payload["text"]
    assert "https://propertyquarry.com/register?token=test&code=654321" in payload["text"]
    assert receipt.message_id == "emailit-live-1"


def test_registration_email_falls_back_to_verified_sender_when_domain_is_not_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_FROM", "property@propertyquarry.com")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_NAME", "PropertyQuarry")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_FROM_FALLBACK", "concierge@chummer.run")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_NAME_FALLBACK", "PropertyQuarry")

    from app.services import registration_email as service

    observed_payloads: list[dict[str, object]] = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"id": "emailit-live-fallback-1"}).encode("utf-8")

    class _DomainNotVerified(service.urllib.error.HTTPError):
        def __init__(self):
            super().__init__(
                url=service.EMAILIT_API_BASE,
                code=422,
                msg="Unprocessable Entity",
                hdrs=None,
                fp=None,
            )

        def read(self) -> bytes:
            return b'{"error":"Domain not verified"}'

    call_count = {"value": 0}

    def _fake_urlopen(request, timeout=0):
        observed_payloads.append(json.loads(request.data.decode("utf-8")))
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise _DomainNotVerified()
        return _Response()

    monkeypatch.setattr(service.urllib.request, "urlopen", _fake_urlopen)

    receipt = service.send_registration_email(
        recipient_email="tibor.girschele@gmail.com",
        verification_code="654321",
        magic_link_url="https://propertyquarry.com/register?token=test&code=654321",
        expires_at=2_000_000_000,
    )

    assert call_count["value"] == 2
    assert observed_payloads[0]["from"] == "PropertyQuarry <property@propertyquarry.com>"
    assert observed_payloads[1]["from"] == "PropertyQuarry <concierge@chummer.run>"
    assert observed_payloads[1]["meta"]["sender_fallback_used"] == "true"
    assert observed_payloads[1]["meta"]["preferred_sender_email"] == "property@propertyquarry.com"
    assert observed_payloads[1]["meta"]["fallback_sender_email"] == "concierge@chummer.run"
    assert receipt.message_id == "emailit-live-fallback-1"


def test_registration_email_can_force_verified_sender_without_primary_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_FORCE_FALLBACK", "1")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_FROM", "property@propertyquarry.com")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_NAME", "PropertyQuarry")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_FROM_FALLBACK", "concierge@chummer.run")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_NAME_FALLBACK", "PropertyQuarry")

    from app.services import registration_email as service

    observed_payloads: list[dict[str, object]] = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"id": "emailit-live-forced-fallback-1"}).encode("utf-8")

    def _fake_urlopen(request, timeout=0):
        observed_payloads.append(json.loads(request.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr(service.urllib.request, "urlopen", _fake_urlopen)

    receipt = service.send_registration_email(
        recipient_email="tibor.girschele@gmail.com",
        verification_code="654321",
        magic_link_url="https://propertyquarry.com/register?token=test&code=654321",
        expires_at=2_000_000_000,
    )

    assert len(observed_payloads) == 1
    assert observed_payloads[0]["from"] == "PropertyQuarry <concierge@chummer.run>"
    assert receipt.message_id == "emailit-live-forced-fallback-1"


def test_property_search_results_email_serializes_emailit_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_FROM", "property@propertyquarry.com")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_NAME", "PropertyQuarry")

    from app.services import registration_email as service

    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"id": "emailit-property-results-1"}).encode("utf-8")

    def _fake_urlopen(request, timeout=0):
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr(service.urllib.request, "urlopen", _fake_urlopen)

    receipt = service.send_property_search_results_ready_email(
        recipient_email="tibor.girschele@gmail.com",
        results_url="https://propertyquarry.com/app/properties?run_id=run-1",
        result_total=2,
        hosted_tour_total=1,
        top_properties=[
            {
                "title": "BG Leopoldstadt, 082 25 E 89/25g",
                "source_label": "Justiz Edikte Auctions | Austria | Buy | 1020 Vienna",
                "fit_summary": "Sparse but relevant auction with floorplan and enough area.",
                "price_label": "EUR 310,000",
                "area_label": "82 m2",
                "rooms_label": "3 rooms",
                "location_label": "1020 Vienna",
                "review_url": "https://propertyquarry.com/app/research/run-1/prop-1",
                "tour_status": "queued",
            },
            {
                "title": "Genossenschaft 70 m2",
                "property_url": "https://propertyquarry.com/source/property-2",
            },
        ],
    )

    payload = dict(captured["payload"])
    assert payload["from"] == "PropertyQuarry <property@propertyquarry.com>"
    assert payload["subject"] == "PropertyQuarry results ready"
    assert "Best matches:" in payload["text"]
    assert "BG Leopoldstadt" in payload["text"]
    assert "https://propertyquarry.com/app/properties?run_id=run-1" in payload["text"]
    html = str(payload["html"])
    assert "<table" in html
    assert "Best matches" in html
    assert 'href="https://propertyquarry.com/app/research/run-1/prop-1"' in html
    assert ">BG Leopoldstadt, 082 25 E 89/25g</a>" in html
    assert "EUR 310,000" in html
    assert "82 m2" in html
    assert 'href="https://propertyquarry.com/app/properties?run_id=run-1"' in html
    assert ">Open full results</a>" in html
    assert ">https://propertyquarry.com/app/research/run-1/prop-1</a>" not in html
    assert ">https://propertyquarry.com/app/properties?run_id=run-1</a>" not in html
    assert isinstance(payload["meta"]["top_property_refs"], str)
    assert isinstance(json.loads(payload["meta"]["top_property_refs"]), list)
    assert payload["meta"]["results_ref"]
    assert receipt.message_id == "emailit-property-results-1"


def test_channel_digest_email_payload_uses_compact_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_FROM", "kleinhirn@girschele.com")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_NAME", "Kleinhirn")

    from app.services import registration_email as service

    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"id": "emailit-digest-1"}).encode("utf-8")

    def _fake_urlopen(request, timeout=0):
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr(service.urllib.request, "urlopen", _fake_urlopen)

    receipt = service.send_channel_digest_email(
        recipient_email="tibor@myexternalbrain.com",
        digest_key="memo",
        headline="Morning memo digest",
        preview_text="0 memo items, 0 commitments at risk, 0 open decisions.",
        delivery_url="https://myexternalbrain.com/channel-loop/deliveries/token-123",
        plain_text=(
            "Open digest: https://myexternalbrain.com/channel-loop/deliveries/token-very-long\n"
            "Morning memo digest\n"
            "0 memo items, 0 commitments at risk, 0 open decisions.\n"
            "\n"
            "1. [Memo] Fix memo delivery blocker\n"
            "   Domain not verified. Verify the sending domain in the email provider before the next memo cycle.\n"
            "   Open support: https://myexternalbrain.com/app/settings/support\n"
        ),
        expires_at="2026-04-01T17:27:54+00:00",
    )

    payload = dict(captured["payload"])
    assert payload["from"] == "Kleinhirn <kleinhirn@girschele.com>"
    assert payload["subject"] == "Morning memo digest"
    assert "Open this secure workspace view:" in payload["text"]
    assert "https://myexternalbrain.com/channel-loop/deliveries/token-123" in payload["text"]
    assert "Digest preview" in payload["text"]
    assert "Open digest:" not in payload["text"]
    assert "Fix memo delivery blocker" in payload["text"]
    assert payload["meta"]["digest_key"] == "memo"
    assert payload["meta"]["delivery_ref"]
    assert "delivery_url" not in payload["meta"]
    assert receipt.message_id == "emailit-digest-1"


def test_google_connect_email_uses_workspace_delivery_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_FROM", "kleinhirn@girschele.com")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_NAME", "Kleinhirn")
    monkeypatch.setenv("EA_EMAIL_DEFAULT_FROM", "sprachenzentrum@girschele.com")
    monkeypatch.setenv("EA_EMAIL_DEFAULT_NAME", "Sprachenzentrum")

    from app.services import registration_email as service

    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"id": "emailit-google-connect-1"}).encode("utf-8")

    def _fake_urlopen(request, timeout=0):
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr(service.urllib.request, "urlopen", _fake_urlopen)

    receipt = service.send_google_connect_email(
        recipient_email="tibor.girschele@gmail.com",
        workspace_name="PropertyQuarry Workspace",
        connect_url="https://propertyquarry.com/workspace-access/token?return_to=%2Fapp%2Factions%2Fgoogle%2Fconnect",
        scope_label="Google Full Workspace",
        scope_summary="Broader assistant context: inbox actions plus richer calendar and Drive index context.",
        primary_google_email="",
        connected_account_total=0,
        expires_at="2026-05-05T16:57:54+00:00",
    )

    payload = dict(captured["payload"])
    assert payload["from"] == "Sprachenzentrum <sprachenzentrum@girschele.com>"
    assert payload["subject"] == "Connect Google to PropertyQuarry Workspace"
    assert "No Google inbox is connected in this workspace yet" in payload["text"]
    assert "https://propertyquarry.com/workspace-access/token?return_to=%2Fapp%2Factions%2Fgoogle%2Fconnect" in payload["text"]
    assert receipt.message_id == "emailit-google-connect-1"


def test_plaintext_digest_email_payload_uses_full_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_FROM", "kleinhirn@girschele.com")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_NAME", "Kleinhirn")

    from app.services import registration_email as service

    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"id": "emailit-plaintext-1"}).encode("utf-8")

    def _fake_urlopen(request, timeout=0):
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr(service.urllib.request, "urlopen", _fake_urlopen)

    receipt = service.send_plaintext_digest_email(
        recipient_email="tibor.girschele@gmail.com",
        digest_key="codexea-ia-2026-05-01",
        headline="CodexEA internal affairs summary",
        preview_text="4 cycles, 2 fixes, 0 unresolved blockers.",
        plain_text="Important things fixed today.\n- lane selection no longer loops the same failure.\n",
    )

    payload = dict(captured["payload"])
    assert payload["from"] == "Kleinhirn <kleinhirn@girschele.com>"
    assert payload["subject"] == "CodexEA internal affairs summary"
    assert "4 cycles, 2 fixes, 0 unresolved blockers." in payload["text"]
    assert "Important things fixed today." in payload["text"]
    assert payload["meta"]["digest_key"] == "codexea-ia-2026-05-01"
    assert receipt.message_id == "emailit-plaintext-1"


def test_plaintext_digest_email_supports_custom_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_FROM", "kleinhirn@girschele.com")
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_NAME", "Kleinhirn")

    from app.services import registration_email as service

    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"id": "emailit-plaintext-custom-1"}).encode("utf-8")

    def _fake_urlopen(request, timeout=0):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr(service.urllib.request, "urlopen", _fake_urlopen)

    receipt = service.send_plaintext_digest_email(
        recipient_email="tibor.girschele@gmail.com",
        digest_key="codexea-ia-custom-sender",
        headline="Internal affairs summary",
        preview_text="Sender override smoke test.",
        plain_text="Plain body",
        sender_email="ia@chummer.run",
        sender_name="Internal Affairs",
    )

    payload = dict(captured["payload"])
    assert payload["from"] == "Internal Affairs <ia@chummer.run>"
    assert payload["reply_to"] == "ia@chummer.run"
    assert receipt.message_id == "emailit-plaintext-custom-1"
