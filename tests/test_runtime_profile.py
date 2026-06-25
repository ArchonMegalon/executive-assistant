from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.dependencies import (
    RequestContext,
    get_request_context,
    resolve_principal_id,
)
from app.product.service import _sign_channel_payload
from app.domain.models import TaskContract, now_utc_iso
from app.repositories.task_contracts import InMemoryTaskContractRepository
from app.services.provider_registry import ProviderRegistryService
from app.services.skills import SkillCatalogService
from app.settings import (
    get_settings,
    resolve_signing_secret,
    resolve_runtime_profile,
    validate_startup_settings,
)
from app.services.task_contracts import TaskContractService


def _clear_env() -> None:
    for key in (
        "EA_RUNTIME_MODE",
        "EA_STORAGE_FALLBACK_ALLOWED",
        "EA_STORAGE_BACKEND",
        "EA_LEDGER_BACKEND",
        "DATABASE_URL",
        "EA_API_TOKEN",
        "EA_SIGNING_SECRET",
        "EA_DEFAULT_PRINCIPAL_ID",
        "EA_ALLOW_LOOPBACK_NO_AUTH",
        "EA_REGISTRATION_EMAIL_FROM",
        "EA_REGISTRATION_EMAIL_FROM_FALLBACK",
        "EA_EMAIL_DEFAULT_FROM",
        "EA_REGISTRATION_EMAIL_ALLOWED_DOMAINS",
        "EA_ALLOW_NON_PROPERTYQUARRY_EMAIL_SENDER",
        "EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER",
        "EA_CODEXEA_AUTHENTICATED_PRINCIPAL_ID",
        "EA_PUBLIC_APP_BASE_URL",
        "EA_GOOGLE_OAUTH_REDIRECT_URI",
        "EA_WORKSPACE_ACCESS_TOKEN_ISSUER",
        "EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE",
        "EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION",
        "EA_TRUST_BROWSER_PRINCIPAL_OVERRIDE",
        "EA_CF_ACCESS_TEAM_DOMAIN",
        "EA_CF_ACCESS_AUD",
        "EA_CF_ACCESS_CERTS_URL",
        "EA_ENABLE_LEGACY_RUNTIME_SURFACES",
    ):
        os.environ.pop(key, None)


@pytest.fixture(autouse=True)
def _isolated_env() -> None:
    tracked = {
        "EA_RUNTIME_MODE": os.environ.get("EA_RUNTIME_MODE"),
        "EA_STORAGE_FALLBACK_ALLOWED": os.environ.get("EA_STORAGE_FALLBACK_ALLOWED"),
        "EA_STORAGE_BACKEND": os.environ.get("EA_STORAGE_BACKEND"),
        "EA_LEDGER_BACKEND": os.environ.get("EA_LEDGER_BACKEND"),
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
        "EA_API_TOKEN": os.environ.get("EA_API_TOKEN"),
        "EA_SIGNING_SECRET": os.environ.get("EA_SIGNING_SECRET"),
        "EA_DEFAULT_PRINCIPAL_ID": os.environ.get("EA_DEFAULT_PRINCIPAL_ID"),
        "EA_ALLOW_LOOPBACK_NO_AUTH": os.environ.get("EA_ALLOW_LOOPBACK_NO_AUTH"),
        "EA_REGISTRATION_EMAIL_FROM": os.environ.get("EA_REGISTRATION_EMAIL_FROM"),
        "EA_REGISTRATION_EMAIL_FROM_FALLBACK": os.environ.get("EA_REGISTRATION_EMAIL_FROM_FALLBACK"),
        "EA_EMAIL_DEFAULT_FROM": os.environ.get("EA_EMAIL_DEFAULT_FROM"),
        "EA_REGISTRATION_EMAIL_ALLOWED_DOMAINS": os.environ.get("EA_REGISTRATION_EMAIL_ALLOWED_DOMAINS"),
        "EA_ALLOW_NON_PROPERTYQUARRY_EMAIL_SENDER": os.environ.get("EA_ALLOW_NON_PROPERTYQUARRY_EMAIL_SENDER"),
        "EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER": os.environ.get("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"),
        "EA_CODEXEA_AUTHENTICATED_PRINCIPAL_ID": os.environ.get("EA_CODEXEA_AUTHENTICATED_PRINCIPAL_ID"),
        "EA_PUBLIC_APP_BASE_URL": os.environ.get("EA_PUBLIC_APP_BASE_URL"),
        "EA_GOOGLE_OAUTH_REDIRECT_URI": os.environ.get("EA_GOOGLE_OAUTH_REDIRECT_URI"),
        "EA_WORKSPACE_ACCESS_TOKEN_ISSUER": os.environ.get("EA_WORKSPACE_ACCESS_TOKEN_ISSUER"),
        "EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE": os.environ.get("EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE"),
        "EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION": os.environ.get("EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION"),
        "EA_TRUST_BROWSER_PRINCIPAL_OVERRIDE": os.environ.get("EA_TRUST_BROWSER_PRINCIPAL_OVERRIDE"),
        "EA_CF_ACCESS_TEAM_DOMAIN": os.environ.get("EA_CF_ACCESS_TEAM_DOMAIN"),
        "EA_CF_ACCESS_AUD": os.environ.get("EA_CF_ACCESS_AUD"),
        "EA_CF_ACCESS_CERTS_URL": os.environ.get("EA_CF_ACCESS_CERTS_URL"),
        "EA_ENABLE_LEGACY_RUNTIME_SURFACES": os.environ.get("EA_ENABLE_LEGACY_RUNTIME_SURFACES"),
    }
    _clear_env()
    try:
        yield
    finally:
        for key, value in tracked.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _request(headers: dict[str, str] | None = None, *, client_host: str = "127.0.0.1", path: str = "/context") -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": raw_headers,
            "client": (client_host, 49152),
        }
    )


def _observation(**kwargs):
    return SimpleNamespace(
        event_type=kwargs.get("event_type", ""),
        payload=kwargs.get("payload", {}),
        source_id=kwargs.get("source_id", ""),
        created_at=kwargs.get("created_at", "2026-06-22T00:00:00+00:00"),
        observation_id=kwargs.get("observation_id", "obs-1"),
        principal_id=kwargs.get("principal_id", ""),
    )


def _container_for_current_settings():
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    return SimpleNamespace(
        settings=settings,
        runtime_profile=profile,
        orchestrator=SimpleNamespace(fetch_operator_profile=lambda operator_id, principal_id: None),
    ), profile


def test_runtime_profile_auto_without_database_prefers_memory() -> None:
    _clear_env()
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    assert profile.storage_backend == "memory"
    assert profile.durability == "ephemeral"
    assert profile.auth_mode == "anonymous_dev"
    assert profile.principal_source == "caller_header_or_default"
    assert profile.caller_principal_header_allowed is True


def test_runtime_profile_non_prod_can_disable_storage_fallback() -> None:
    _clear_env()
    os.environ["EA_STORAGE_FALLBACK_ALLOWED"] = "false"
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    assert profile.storage_backend == "memory"
    assert settings.storage_fallback_allowed is False


def test_runtime_profile_auto_with_database_prefers_postgres() -> None:
    _clear_env()
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    assert profile.storage_backend == "postgres"
    assert profile.durability == "durable"
    assert profile.principal_source == "caller_header_or_default"
    assert profile.caller_principal_header_allowed is True


def test_runtime_profile_non_prod_token_auth_still_allows_caller_header_or_default_principal() -> None:
    _clear_env()
    os.environ["EA_API_TOKEN"] = "secret-token"
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    assert profile.auth_mode == "token"
    assert profile.principal_source == "authenticated_header_or_default"
    assert profile.caller_principal_header_allowed is True


def test_non_prod_defaults_legacy_runtime_surfaces_enabled() -> None:
    _clear_env()

    settings = get_settings()

    assert settings.legacy_runtime_surfaces_enabled is True


def test_prod_defaults_legacy_runtime_surfaces_disabled() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://assistant.example.test"

    settings = get_settings()

    assert settings.legacy_runtime_surfaces_enabled is False


def test_prod_requires_database_url() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://assistant.example.test"
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        validate_startup_settings(get_settings())


def test_prod_requires_explicit_signing_secret() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "secret-token"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    with pytest.raises(RuntimeError, match="EA_SIGNING_SECRET"):
        validate_startup_settings(get_settings())


def test_prod_requires_workspace_access_token_issuer_binding() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    with pytest.raises(RuntimeError, match="workspace access token binding"):
        validate_startup_settings(get_settings())


def test_prod_allows_workspace_access_token_binding_from_public_origin() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://assistant.example.test"

    profile = validate_startup_settings(get_settings())

    assert profile.mode == "prod"


def test_prod_rejects_placeholder_workspace_access_token_binding_from_public_origin() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://example.test"
    with pytest.raises(RuntimeError, match="placeholder workspace access token binding origin/issuer"):
        validate_startup_settings(get_settings())


def test_prod_rejects_placeholder_workspace_access_token_issuer() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_WORKSPACE_ACCESS_TOKEN_ISSUER"] = "https://example.test"
    with pytest.raises(RuntimeError, match="placeholder workspace access token binding origin/issuer"):
        validate_startup_settings(get_settings())


def test_prod_rejects_placeholder_workspace_access_token_audience() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://assistant.example.test"
    os.environ["EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE"] = "example-secret"
    with pytest.raises(RuntimeError, match="placeholder EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE"):
        validate_startup_settings(get_settings())


def test_prod_rejects_placeholder_workspace_access_token_key_version() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://assistant.example.test"
    os.environ["EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION"] = "replace-me"
    with pytest.raises(RuntimeError, match="placeholder EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION"):
        validate_startup_settings(get_settings())


def test_prod_rejects_placeholder_api_token() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "secret-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    with pytest.raises(RuntimeError, match="placeholder EA_API_TOKEN"):
        validate_startup_settings(get_settings())


def test_prod_rejects_placeholder_signing_secret() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    with pytest.raises(RuntimeError, match="placeholder EA_SIGNING_SECRET"):
        validate_startup_settings(get_settings())


def test_prod_allows_cloudflare_access_auth_without_api_token() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://assistant.example.test"
    os.environ["EA_CF_ACCESS_TEAM_DOMAIN"] = "girschele.cloudflareaccess.com"
    os.environ["EA_CF_ACCESS_AUD"] = "aud-123"

    profile = validate_startup_settings(get_settings())

    assert profile.mode == "prod"
    assert profile.auth_mode == "access"


def test_prod_rejects_placeholder_cloudflare_access_team_domain() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://assistant.example.test"
    os.environ["EA_CF_ACCESS_TEAM_DOMAIN"] = "example.test"
    os.environ["EA_CF_ACCESS_AUD"] = "aud-123"
    with pytest.raises(RuntimeError, match="placeholder EA_CF_ACCESS_TEAM_DOMAIN"):
        validate_startup_settings(get_settings())


def test_prod_rejects_placeholder_cloudflare_access_audience() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://assistant.example.test"
    os.environ["EA_CF_ACCESS_TEAM_DOMAIN"] = "girschele.cloudflareaccess.com"
    os.environ["EA_CF_ACCESS_AUD"] = "replace-me"
    with pytest.raises(RuntimeError, match="placeholder EA_CF_ACCESS_AUD"):
        validate_startup_settings(get_settings())


def test_prod_rejects_placeholder_cloudflare_access_certs_url() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://assistant.example.test"
    os.environ["EA_CF_ACCESS_TEAM_DOMAIN"] = "girschele.cloudflareaccess.com"
    os.environ["EA_CF_ACCESS_AUD"] = "aud-123"
    os.environ["EA_CF_ACCESS_CERTS_URL"] = "https://example.test/cdn-cgi/access/certs"
    with pytest.raises(RuntimeError, match="placeholder EA_CF_ACCESS_CERTS_URL"):
        validate_startup_settings(get_settings())


def test_prod_forbids_loopback_no_auth() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://assistant.example.test"
    os.environ["EA_ALLOW_LOOPBACK_NO_AUTH"] = "1"
    with pytest.raises(RuntimeError, match="EA_ALLOW_LOOPBACK_NO_AUTH"):
        validate_startup_settings(get_settings())


def test_prod_rejects_registration_sender_domains_outside_configured_allowlist() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://assistant.example.test"
    os.environ["EA_REGISTRATION_EMAIL_FROM"] = "concierge@chummer.run"
    os.environ["EA_REGISTRATION_EMAIL_ALLOWED_DOMAINS"] = "example.test"
    with pytest.raises(RuntimeError, match="registration email sender domains"):
        validate_startup_settings(get_settings())


def test_prod_allows_registration_sender_domain_from_configured_allowlist() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://assistant.example.test"
    os.environ["EA_REGISTRATION_EMAIL_FROM"] = "concierge@chummer.run"
    os.environ["EA_REGISTRATION_EMAIL_ALLOWED_DOMAINS"] = "chummer.run"
    profile = validate_startup_settings(get_settings())
    assert profile.storage_backend == "postgres"


def test_prod_allows_registration_sender_domain_override() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://assistant.example.test"
    os.environ["EA_REGISTRATION_EMAIL_FROM"] = "concierge@chummer.run"
    os.environ["EA_REGISTRATION_EMAIL_ALLOWED_DOMAINS"] = "example.test"
    os.environ["EA_ALLOW_NON_PROPERTYQUARRY_EMAIL_SENDER"] = "1"
    profile = validate_startup_settings(get_settings())
    assert profile.storage_backend == "postgres"


def test_prod_runtime_profile_requires_authenticated_header_principal() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "secret-token"
    os.environ["EA_SIGNING_SECRET"] = "signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    assert profile.auth_mode == "token"
    assert profile.principal_source == "authenticated_header"
    assert profile.caller_principal_header_allowed is True


def test_runtime_profile_non_prod_token_auth_matches_request_context_contract() -> None:
    _clear_env()
    os.environ["EA_API_TOKEN"] = "secret-token"
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = "ops-fallback"
    container, profile = _container_for_current_settings()

    fallback_context = get_request_context(
        _request(headers={"Authorization": "Bearer secret-token"}),
        container=container,
    )
    assert profile.principal_source == "authenticated_header_or_default"
    assert fallback_context.principal_id == "ops-fallback"
    assert fallback_context.authenticated is True

    header_context = get_request_context(
        _request(headers={"Authorization": "Bearer secret-token", "X-EA-Principal-ID": "caller-1"}),
        container=container,
    )
    assert header_context.principal_id == "ops-fallback"

    os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
    container, _ = _container_for_current_settings()
    header_context = get_request_context(
        _request(headers={"Authorization": "Bearer secret-token", "X-EA-Principal-ID": "caller-1"}),
        container=container,
    )
    assert header_context.principal_id == "caller-1"


def test_authenticated_principal_override_rejected_for_non_loopback_request() -> None:
    _clear_env()
    os.environ["EA_API_TOKEN"] = "secret-token"
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = "ops-fallback"
    os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
    container, _ = _container_for_current_settings()

    header_context = get_request_context(
        _request(
            headers={"Authorization": "Bearer secret-token", "X-EA-Principal-ID": "caller-1"},
            client_host="198.51.100.42",
        ),
        container=container,
    )
    assert header_context.principal_id == "ops-fallback"


def test_loopback_no_auth_preserves_token_auth_principal_contract() -> None:
    _clear_env()
    os.environ["EA_API_TOKEN"] = "secret-token"
    os.environ["EA_ALLOW_LOOPBACK_NO_AUTH"] = "1"
    os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
    container, _ = _container_for_current_settings()

    token_context = get_request_context(
        _request(headers={"Authorization": "Bearer secret-token", "X-EA-Principal-ID": "caller-1"}),
        container=container,
    )
    assert token_context.principal_id == "caller-1"
    assert token_context.auth_source == "api_token"
    assert token_context.authenticated is True

    loopback_context = get_request_context(
        _request(headers={"X-EA-Principal-ID": "caller-2"}),
        container=container,
    )
    assert loopback_context.principal_id == "caller-2"
    assert loopback_context.auth_source == "loopback_no_auth"
    assert loopback_context.authenticated is True
    assert loopback_context.operator_id == ""
    assert loopback_context.operator_authorized is False


def test_loopback_no_auth_uses_active_operator_profile_for_operator_context() -> None:
    _clear_env()
    os.environ["EA_ALLOW_LOOPBACK_NO_AUTH"] = "1"
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = "ops-fallback"
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    operator_profile = SimpleNamespace(
        operator_id="operator-1",
        principal_id="ops-fallback",
        roles=("operator", "reviewer"),
        status="active",
    )
    container = SimpleNamespace(
        settings=settings,
        runtime_profile=profile,
        channel_runtime=SimpleNamespace(list_recent_observations=lambda **kwargs: []),
        orchestrator=SimpleNamespace(
            fetch_operator_profile=lambda operator_id, principal_id: operator_profile
            if operator_id == "operator-1" and principal_id == "ops-fallback"
            else None,
            list_operator_profiles=lambda principal_id, status="active", limit=25: [operator_profile],
        ),
    )

    context = get_request_context(
        _request(headers={"X-EA-Principal-ID": "ops-fallback"}),
        container=container,
    )
    assert context.auth_source == "loopback_no_auth"
    assert context.operator_id == "operator-1"
    assert context.operator_authorized is True


def test_authenticated_request_requires_active_operator_profile_for_operator_context() -> None:
    _clear_env()
    os.environ["EA_API_TOKEN"] = "secret-token"
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = "ops-fallback"
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    operator_profile = SimpleNamespace(
        operator_id="operator-1",
        principal_id="ops-fallback",
        roles=("operator", "reviewer"),
        status="active",
    )
    container = SimpleNamespace(
        settings=settings,
        runtime_profile=profile,
        channel_runtime=SimpleNamespace(list_recent_observations=lambda **kwargs: []),
        orchestrator=SimpleNamespace(
            fetch_operator_profile=lambda operator_id, principal_id: operator_profile
            if operator_id == "operator-1" and principal_id == "ops-fallback"
            else None
        ),
    )

    context = get_request_context(
        _request(headers={"Authorization": "Bearer secret-token", "X-EA-Operator-ID": "operator-1"}),
        container=container,
    )
    assert context.operator_id == "operator-1"
    assert context.operator_authorized is True


def test_authenticated_request_does_not_gain_operator_context_without_active_operator_profile() -> None:
    _clear_env()
    os.environ["EA_API_TOKEN"] = "secret-token"
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = "ops-fallback"
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    container = SimpleNamespace(
        settings=settings,
        runtime_profile=profile,
        channel_runtime=SimpleNamespace(list_recent_observations=lambda **kwargs: []),
        orchestrator=SimpleNamespace(fetch_operator_profile=lambda operator_id, principal_id: None),
    )

    context = get_request_context(
        _request(headers={"Authorization": "Bearer secret-token", "X-EA-Operator-ID": "operator-1"}),
        container=container,
    )
    assert context.operator_id == ""
    assert context.operator_authorized is False


def test_runtime_profile_prod_authenticated_header_matches_request_context_contract() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "secret-token"
    os.environ["EA_SIGNING_SECRET"] = "signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    container, profile = _container_for_current_settings()

    with pytest.raises(HTTPException, match="principal_required"):
        get_request_context(
            _request(headers={"Authorization": "Bearer secret-token"}),
            container=container,
        )

    assert profile.principal_source == "authenticated_header"
    with pytest.raises(HTTPException, match="principal_required"):
        get_request_context(
            _request(headers={"Authorization": "Bearer secret-token", "X-EA-Principal-ID": "ops-1"}),
            container=container,
        )


def test_prod_ignores_authenticated_principal_override_even_when_flagged() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
    container, _ = _container_for_current_settings()

    with pytest.raises(HTTPException, match="principal_required"):
        get_request_context(
            _request(headers={"Authorization": "Bearer real-api-token", "X-EA-Principal-ID": "ops-1"}),
            container=container,
        )


def test_prod_codexea_routes_use_fixed_authenticated_principal_without_trusting_header() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_CODEXEA_AUTHENTICATED_PRINCIPAL_ID"] = "codexea-runtime"
    container, _ = _container_for_current_settings()

    context = get_request_context(
        _request(
            headers={
                "Authorization": "Bearer real-api-token",
                "X-EA-Principal-ID": "caller-controlled",
            },
            path="/v1/models",
        ),
        container=container,
    )

    assert context.principal_id == "codexea-runtime"
    assert context.authenticated is True
    assert context.auth_source == "api_token"


def test_prod_fixed_codexea_principal_does_not_apply_to_general_routes() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_CODEXEA_AUTHENTICATED_PRINCIPAL_ID"] = "codexea-runtime"
    container, _ = _container_for_current_settings()

    with pytest.raises(HTTPException, match="principal_required"):
        get_request_context(
            _request(headers={"Authorization": "Bearer real-api-token"}, path="/v1/onboarding/start"),
            container=container,
        )


def test_workspace_session_rejects_forged_jti_even_with_valid_signature() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "real-api-token"
    os.environ["EA_SIGNING_SECRET"] = "real-signing-secret"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_WORKSPACE_ACCESS_TOKEN_ISSUER"] = "ea://workspace-access"
    os.environ["EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE"] = "workspace-access"
    os.environ["EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION"] = "v1"
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    principal_id = "principal-1"
    session_id = "access_123"
    issued_payload = {
        "session_id": session_id,
        "principal_id": principal_id,
        "jti": "wsa_real_token",
        "issuer": "ea://workspace-access",
        "audience": "workspace-access",
        "key_version": "v1",
        "session_version": 1,
    }
    forged_payload = {
        "token_kind": "workspace_access_session",
        "session_id": session_id,
        "principal_id": principal_id,
        "email": "principal@example.com",
        "role": "principal",
        "display_name": "Principal",
        "source_kind": "workspace_access",
        "expires_at": "2026-06-23T00:00:00+00:00",
        "iss": "ea://workspace-access",
        "aud": "workspace-access",
        "kid": "v1",
        "jti": "wsa_forged_token",
        "session_version": 1,
    }
    token = _sign_channel_payload(
        secret=resolve_signing_secret(settings, purpose="workspace-access"),
        payload=forged_payload,
    )
    container = SimpleNamespace(
        settings=settings,
        runtime_profile=profile,
        channel_runtime=SimpleNamespace(
            list_recent_observations=lambda limit=1000, principal_id=None: [
                _observation(
                    event_type="workspace_access_session_issued",
                    payload=issued_payload,
                    source_id=session_id,
                    principal_id=principal_id or "",
                )
            ]
        ),
    )

    with pytest.raises(HTTPException, match="auth_required"):
        get_request_context(
            _request(headers={"cookie": f"ea_workspace_session={token}"}),
            container=container,
        )


def test_signing_secret_does_not_fallback_to_api_token() -> None:
    _clear_env()
    os.environ["EA_API_TOKEN"] = "secret-token"
    settings = get_settings()
    resolved = resolve_signing_secret(settings, purpose="workspace-access")
    assert resolved != "secret-token:workspace-access"
    assert "secret-token" not in resolved

    os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
    container, _ = _container_for_current_settings()
    header_context = get_request_context(
        _request(headers={"Authorization": "Bearer secret-token", "X-EA-Principal-ID": "ops-1"}),
        container=container,
    )
    assert header_context.principal_id == "ops-1"
    assert header_context.authenticated is True


def test_prod_runtime_profile_allows_cloudflare_access_without_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    os.environ["EA_CF_ACCESS_TEAM_DOMAIN"] = "girschele.cloudflareaccess.com"
    os.environ["EA_CF_ACCESS_AUD"] = "aud-123"
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    assert profile.auth_mode == "access"

    from app.api import dependencies as deps
    from app.services.cloudflare_access import CloudflareAccessIdentity

    monkeypatch.setattr(
        deps,
        "resolve_access_identity",
        lambda **kwargs: CloudflareAccessIdentity(
            principal_id="cf-email:user@gmail.com",
            email="user@gmail.com",
            subject="subject-123",
            display_name="User Gmail",
            issuer="https://girschele.cloudflareaccess.com",
            idp_name="google",
            audiences=("aud-123",),
            claims={"email": "user@gmail.com", "sub": "subject-123"},
        ),
    )
    container, _ = _container_for_current_settings()
    container.orchestrator = SimpleNamespace(
        fetch_operator_profile=lambda operator_id, principal_id: None,
        upsert_operator_profile=lambda **kwargs: kwargs,
    )

    context = get_request_context(_request(headers={}), container=container)
    assert context.principal_id == "cf-email:user@gmail.com"
    assert context.authenticated is True
    assert context.auth_source == "cloudflare_access"
    assert context.access_email == "user@gmail.com"


def test_resolve_principal_id_rejects_foreign_requested_principal() -> None:
    context = RequestContext(principal_id="exec-1", authenticated=False)
    with pytest.raises(Exception):
        resolve_principal_id("exec-2", context)


def test_provider_registry_exposes_executable_browseract_binding() -> None:
    registry = ProviderRegistryService()
    contract = TaskContract(
        task_key="inventory",
        deliverable_type="inventory",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("browseract.extract_account_inventory",),
        evidence_requirements=(),
        memory_write_policy="none",
        budget_policy_json={"class": "low"},
        updated_at=now_utc_iso(),
    )
    bindings = registry.bindings_for_skill(
        SkillCatalogService(TaskContractService(InMemoryTaskContractRepository())).contract_to_skill(contract)
    )
    assert any(binding.provider_key == "browseract" and binding.executable for binding in bindings)
