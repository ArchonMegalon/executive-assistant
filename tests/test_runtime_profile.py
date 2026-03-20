from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.dependencies import RequestContext, get_request_context, resolve_principal_id
from app.domain.models import TaskContract, now_utc_iso
from app.repositories.task_contracts import InMemoryTaskContractRepository
from app.services.provider_registry import ProviderRegistryService
from app.services.skills import SkillCatalogService
from app.settings import (
    get_settings,
    resolve_runtime_profile,
    validate_startup_settings,
)
from app.services.task_contracts import TaskContractService


def _clear_env() -> None:
    for key in (
        "EA_RUNTIME_MODE",
        "EA_STORAGE_BACKEND",
        "EA_LEDGER_BACKEND",
        "DATABASE_URL",
        "EA_API_TOKEN",
        "EA_DEFAULT_PRINCIPAL_ID",
        "EA_CF_ACCESS_TEAM_DOMAIN",
        "EA_CF_ACCESS_AUD",
        "EA_CF_ACCESS_CERTS_URL",
    ):
        os.environ.pop(key, None)


@pytest.fixture(autouse=True)
def _isolated_env() -> None:
    tracked = {
        "EA_RUNTIME_MODE": os.environ.get("EA_RUNTIME_MODE"),
        "EA_STORAGE_BACKEND": os.environ.get("EA_STORAGE_BACKEND"),
        "EA_LEDGER_BACKEND": os.environ.get("EA_LEDGER_BACKEND"),
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
        "EA_API_TOKEN": os.environ.get("EA_API_TOKEN"),
        "EA_DEFAULT_PRINCIPAL_ID": os.environ.get("EA_DEFAULT_PRINCIPAL_ID"),
        "EA_CF_ACCESS_TEAM_DOMAIN": os.environ.get("EA_CF_ACCESS_TEAM_DOMAIN"),
        "EA_CF_ACCESS_AUD": os.environ.get("EA_CF_ACCESS_AUD"),
        "EA_CF_ACCESS_CERTS_URL": os.environ.get("EA_CF_ACCESS_CERTS_URL"),
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


def _request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/context",
            "headers": raw_headers,
        }
    )


def _container_for_current_settings():
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    return SimpleNamespace(settings=settings, runtime_profile=profile), profile


def test_runtime_profile_auto_without_database_prefers_memory() -> None:
    _clear_env()
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    assert profile.storage_backend == "memory"
    assert profile.durability == "ephemeral"
    assert profile.auth_mode == "anonymous_dev"
    assert profile.principal_source == "caller_header_or_default"
    assert profile.caller_principal_header_allowed is True


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


def test_prod_requires_database_url() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "secret-token"
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        validate_startup_settings(get_settings())


def test_prod_runtime_profile_requires_authenticated_header_principal() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "secret-token"
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
    assert header_context.principal_id == "caller-1"


def test_runtime_profile_prod_authenticated_header_matches_request_context_contract() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "secret-token"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    container, profile = _container_for_current_settings()

    with pytest.raises(HTTPException, match="principal_required"):
        get_request_context(
            _request(headers={"Authorization": "Bearer secret-token"}),
            container=container,
        )

    header_context = get_request_context(
        _request(headers={"Authorization": "Bearer secret-token", "X-EA-Principal-ID": "ops-1"}),
        container=container,
    )
    assert profile.principal_source == "authenticated_header"
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
