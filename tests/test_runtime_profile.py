from __future__ import annotations

import os

import pytest

from app.api.dependencies import RequestContext, resolve_principal_id
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
    ):
        os.environ.pop(key, None)


def test_runtime_profile_auto_without_database_prefers_memory() -> None:
    _clear_env()
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    assert profile.storage_backend == "memory"
    assert profile.durability == "ephemeral"


def test_runtime_profile_auto_with_database_prefers_postgres() -> None:
    _clear_env()
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    settings = get_settings()
    profile = resolve_runtime_profile(settings)
    assert profile.storage_backend == "postgres"
    assert profile.durability == "durable"


def test_prod_requires_database_url() -> None:
    _clear_env()
    os.environ["EA_RUNTIME_MODE"] = "prod"
    os.environ["EA_API_TOKEN"] = "secret-token"
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        validate_startup_settings(get_settings())


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
