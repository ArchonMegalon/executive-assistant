from __future__ import annotations

import os
from types import SimpleNamespace

from app.api.routes.landing_shared_support import operator_bootstrap_defaults
from app.product.service import build_product_service
from tests.product_test_helpers import _build_client, build_product_client, start_workspace


def test_operator_bootstrap_defaults_align_access_email_principal_with_operator_id() -> None:
    defaults = operator_bootstrap_defaults(
        principal_id="cf-email:work.tibor.girschele@gmail.com",
        access_email="work.tibor.girschele@gmail.com",
    )

    assert defaults["email_hint"] == "work.tibor.girschele@gmail.com"
    assert defaults["operator_id"] == "cf-email:work.tibor.girschele@gmail.com"
    assert defaults["display_name"] == "Work Tibor Girschele"


def test_workspace_access_session_self_heals_into_operator_scope_without_bootstrap() -> None:
    principal_id = "exec-bootstrap-workspace-session"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal")

    product = build_product_service(client.app.state.container)
    principal_session = product.issue_workspace_access_session(
        principal_id=principal_id,
        email="work.tibor.girschele@gmail.com",
        role="principal",
        display_name="Work Tibor Girschele",
        default_target="/app/today",
    )
    opened = client.get(principal_session["access_url"], follow_redirects=False)
    assert opened.status_code == 303
    assert opened.headers["location"] == "/admin/office"
    assert "ea_workspace_session=" in str(opened.headers.get("set-cookie") or "")

    proactive = client.get(
        "/admin/proactive-ooda/approval",
        follow_redirects=False,
        headers={"accept": "text/html"},
    )
    assert proactive.status_code == 200
    assert "Proactive OODA Approval" in proactive.text


def test_explicit_principal_workspace_access_session_keeps_today_scope() -> None:
    principal_id = "exec-explicit-principal-workspace-session"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal")

    product = build_product_service(client.app.state.container)
    principal_session = product.issue_workspace_access_session(
        principal_id=principal_id,
        email="principal@example.com",
        role="principal",
        display_name="Principal Access",
        source_kind="settings_access",
        default_target="/app/today",
    )

    opened = client.get(principal_session["access_url"], follow_redirects=False)

    assert opened.status_code == 303
    assert opened.headers["location"] == "/app/today"
    assert "ea_workspace_session=" in str(opened.headers.get("set-cookie") or "")


def test_workspace_sign_in_candidates_prefer_active_operator_profile_for_matching_email() -> None:
    principal_id = "cf-email:work.tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal")

    container = client.app.state.container
    container.orchestrator.upsert_operator_profile(
        principal_id=principal_id,
        operator_id="operator-work-tibor-girschele",
        display_name="Work Tibor Girschele",
        roles=("operator", "reviewer"),
        trust_tier="standard",
        status="active",
        notes="Seeded by workspace sign-in candidate test.",
    )
    product = build_product_service(container)
    product.issue_workspace_access_session(
        principal_id=principal_id,
        email="work.tibor.girschele@gmail.com",
        role="principal",
        display_name="Work Tibor Girschele",
        source_kind="seed_principal_sign_in",
    )

    candidates = product._workspace_sign_in_candidates(email="work.tibor.girschele@gmail.com")

    assert candidates
    assert candidates[0]["principal_id"] == principal_id
    assert candidates[0]["role"] == "operator"
    assert candidates[0]["operator_id"] == "operator-work-tibor-girschele"
    assert candidates[0]["display_name"] == "Work Tibor Girschele"


def test_google_sign_in_callback_issues_operator_session_when_operator_profile_exists(monkeypatch) -> None:
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://assistant.example.test/google/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "test-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "test-provider-secret")

    principal_id = "cf-email:work.tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal")

    container = client.app.state.container
    container.orchestrator.upsert_operator_profile(
        principal_id=principal_id,
        operator_id="operator-work-tibor-girschele",
        display_name="Work Tibor Girschele",
        roles=("operator", "reviewer"),
        trust_tier="standard",
        status="active",
        notes="Seeded by Google sign-in operator test.",
    )

    from app.api.routes import landing_setup as landing_setup_routes
    from app.services import google_oauth as google_service

    packet = google_service.build_google_oauth_start(
        principal_id="",
        scope_bundle="identity",
        redirect_uri_override="https://assistant.example.test/google/callback",
        return_to="/sign-in?google_connected=1",
        browser_source="sign_in",
    )
    account = SimpleNamespace(
        binding=SimpleNamespace(
            principal_id=principal_id,
            binding_id=f"{principal_id}:{google_service.GOOGLE_PROVIDER_KEY}",
        ),
        google_email="work.tibor.girschele@gmail.com",
        google_subject="google-sub-work-tibor",
        granted_scopes=("openid", "email", "profile"),
        consent_stage="identity",
    )
    monkeypatch.setattr(landing_setup_routes, "complete_google_oauth_callback", lambda **_kwargs: account)
    monkeypatch.setattr(landing_setup_routes, "_google_post_connect_sync", lambda **_kwargs: {"status": "identity_only"})

    callback = client.get(
        "/google/callback",
        params={"code": "code-123", "state": packet.state},
        follow_redirects=False,
    )

    assert callback.status_code == 303
    access_url = str(callback.headers.get("location") or "")
    assert access_url.startswith("/workspace-access/")

    opened = client.get(access_url, follow_redirects=False)
    assert opened.status_code == 303

    proactive = client.get(
        "/admin/proactive-ooda/approval",
        follow_redirects=False,
        headers={"accept": "text/html"},
    )
    assert proactive.status_code == 200
    assert "Proactive OODA Approval" in proactive.text


def test_existing_principal_workspace_session_resolves_operator_scope_for_operator_only_api() -> None:
    principal_id = "cf-email:work.tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal")

    container = client.app.state.container
    container.orchestrator.upsert_operator_profile(
        principal_id=principal_id,
        operator_id="operator-work-tibor-girschele",
        display_name="Work Tibor Girschele",
        roles=("operator", "reviewer"),
        trust_tier="standard",
        status="active",
        notes="Seeded by workspace-session operator-scope compatibility test.",
    )
    product = build_product_service(container)
    principal_session = product.issue_workspace_access_session(
        principal_id=principal_id,
        email="work.tibor.girschele@gmail.com",
        role="principal",
        display_name="Work Tibor Girschele",
        source_kind="seed_principal_workspace_session",
    )

    opened = client.get(principal_session["access_url"], follow_redirects=False)
    assert opened.status_code == 303
    assert "ea_workspace_session=" in str(opened.headers.get("set-cookie") or "")

    operator_only = client.get("/v1/skills")

    assert operator_only.status_code == 200
    assert operator_only.json() == []


def test_api_token_request_resolves_operator_scope_for_operator_only_api_without_operator_header() -> None:
    principal_id = "cf-email:work.tibor.girschele@gmail.com"
    previous_token = os.environ.get("EA_API_TOKEN")
    previous_default_principal = os.environ.get("EA_DEFAULT_PRINCIPAL_ID")
    os.environ["EA_API_TOKEN"] = "test-token"
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = principal_id
    try:
        client = _build_client(principal_id=principal_id, api_token="test-token")
        start_workspace(client, mode="personal")

        container = client.app.state.container
        container.orchestrator.upsert_operator_profile(
            principal_id=principal_id,
            operator_id="operator-work-tibor-girschele",
            display_name="Work Tibor Girschele",
            roles=("operator", "reviewer"),
            trust_tier="standard",
            status="active",
            notes="Seeded by api-token operator-scope compatibility test.",
        )

        operator_only = client.get("/v1/skills")
    finally:
        if previous_token is None:
            os.environ.pop("EA_API_TOKEN", None)
        else:
            os.environ["EA_API_TOKEN"] = previous_token
        if previous_default_principal is None:
            os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
        else:
            os.environ["EA_DEFAULT_PRINCIPAL_ID"] = previous_default_principal

    assert operator_only.status_code == 200
    assert operator_only.json() == []


def test_workspace_sign_in_auto_provisions_operator_when_only_specialized_profiles_exist() -> None:
    principal_id = "exec-1-auto-operator"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal")

    container = client.app.state.container
    container.orchestrator.upsert_operator_profile(
        principal_id=principal_id,
        operator_id="briefing-reviewer",
        display_name="Briefing Reviewer",
        roles=("briefing_reviewer",),
        trust_tier="standard",
        status="active",
        notes="Specialized reviewer profile should not block real operator bootstrap.",
    )
    product = build_product_service(container)

    access_grant = product.resolve_workspace_access_grant(
        principal_id=principal_id,
        email="tibor.girschele@gmail.com",
        default_role="principal",
        display_name="Tibor Workspace",
    )

    assert access_grant["role"] == "operator"
    assert access_grant["operator_id"] == "operator-tibor-girschele"

    principal_session = product.issue_workspace_access_session(
        principal_id=principal_id,
        email="tibor.girschele@gmail.com",
        role=access_grant["role"],
        display_name=access_grant["display_name"],
        operator_id=access_grant["operator_id"],
        source_kind="seed_principal_workspace_session",
    )

    opened = client.get(principal_session["access_url"], follow_redirects=False)
    assert opened.status_code == 303
    assert "ea_workspace_session=" in str(opened.headers.get("set-cookie") or "")

    operator_only = client.get("/v1/skills")

    assert operator_only.status_code == 200
    assert container.orchestrator.fetch_operator_profile(
        "operator-tibor-girschele",
        principal_id=principal_id,
    ) is not None


def test_legacy_principal_workspace_access_link_self_heals_into_operator_scope() -> None:
    principal_id = "exec-legacy-principal-link"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal")

    container = client.app.state.container
    container.orchestrator.upsert_operator_profile(
        principal_id=principal_id,
        operator_id="briefing-reviewer",
        display_name="Briefing Reviewer",
        roles=("briefing_reviewer",),
        trust_tier="standard",
        status="active",
        notes="Specialized reviewer profile should not block legacy session repair.",
    )
    product = build_product_service(container)

    principal_session = product.issue_workspace_access_session(
        principal_id=principal_id,
        email="tibor.girschele@gmail.com",
        role="principal",
        display_name="Tibor Girschele",
        source_kind="legacy_principal_session",
    )

    opened = client.get(principal_session["access_url"], follow_redirects=False)

    assert opened.status_code == 303
    assert opened.headers["location"] == "/admin/office"
    assert "ea_workspace_session=" in str(opened.headers.get("set-cookie") or "")

    operator_only = client.get("/v1/skills")

    assert operator_only.status_code == 200
    assert container.orchestrator.fetch_operator_profile(
        "operator-tibor-girschele",
        principal_id=principal_id,
    ) is not None


def test_legacy_principal_workspace_cookie_self_heals_into_operator_scope() -> None:
    principal_id = "exec-legacy-principal-cookie"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal")

    container = client.app.state.container
    container.orchestrator.upsert_operator_profile(
        principal_id=principal_id,
        operator_id="briefing-reviewer",
        display_name="Briefing Reviewer",
        roles=("briefing_reviewer",),
        trust_tier="standard",
        status="active",
        notes="Specialized reviewer profile should not block legacy cookie repair.",
    )
    product = build_product_service(container)

    principal_session = product.issue_workspace_access_session(
        principal_id=principal_id,
        email="tibor.girschele@gmail.com",
        role="principal",
        display_name="Tibor Girschele",
        source_kind="legacy_principal_session",
    )

    client.headers.pop("X-EA-Principal-ID", None)
    client.cookies.set("ea_workspace_session", str(principal_session["access_token"] or "").strip())

    operator_only = client.get("/v1/skills")

    assert operator_only.status_code == 200
    assert container.orchestrator.fetch_operator_profile(
        "operator-tibor-girschele",
        principal_id=principal_id,
    ) is not None
