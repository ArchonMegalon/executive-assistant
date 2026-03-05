from __future__ import annotations

import os

from app.settings import get_settings


def _clear_env() -> None:
    for key in (
        "EA_APP_NAME",
        "EA_APP_VERSION",
        "EA_ROLE",
        "EA_HOST",
        "EA_PORT",
        "EA_LOG_LEVEL",
        "EA_TENANT_ID",
        "EA_STORAGE_BACKEND",
        "EA_LEDGER_BACKEND",
        "DATABASE_URL",
        "EA_ARTIFACTS_DIR",
        "EA_API_TOKEN",
        "EA_MAX_REWRITE_CHARS",
        "EA_APPROVAL_THRESHOLD_CHARS",
        "EA_APPROVAL_TTL_MINUTES",
        "EA_CHANNEL_DEFAULT_LIMIT",
    ):
        os.environ.pop(key, None)


def test_settings_defaults() -> None:
    _clear_env()
    s = get_settings()
    assert s.core.app_name == "ea-rewrite"
    assert s.core.role == "api"
    assert s.storage.backend == "auto"
    assert s.storage.database_url == ""
    assert s.auth.enabled is False
    assert s.policy.max_rewrite_chars == 20000
    assert s.policy.approval_required_chars == 5000
    assert s.policy.approval_ttl_minutes == 120
    assert s.channels.default_list_limit == 50


def test_settings_legacy_backend_fallback() -> None:
    _clear_env()
    os.environ["EA_LEDGER_BACKEND"] = "postgres"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
    s = get_settings()
    assert s.storage.backend == "postgres"
    assert s.ledger_backend == "postgres"
    assert s.database_url == "postgresql://example.invalid/ea"


def test_settings_explicit_storage_backend_wins() -> None:
    _clear_env()
    os.environ["EA_LEDGER_BACKEND"] = "memory"
    os.environ["EA_STORAGE_BACKEND"] = "postgres"
    s = get_settings()
    assert s.storage.backend == "postgres"


def test_policy_threshold_overrides() -> None:
    _clear_env()
    os.environ["EA_APPROVAL_THRESHOLD_CHARS"] = "42"
    os.environ["EA_APPROVAL_TTL_MINUTES"] = "15"
    s = get_settings()
    assert s.policy.approval_required_chars == 42
    assert s.policy.approval_ttl_minutes == 15
