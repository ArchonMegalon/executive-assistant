from __future__ import annotations

import pytest


def test_onemin_browseract_default_limits_are_host_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONEMIN_BROWSERACT_MAX_ACCOUNTS_PER_REFRESH", raising=False)
    monkeypatch.delenv("ONEMIN_BROWSERACT_PARALLELISM", raising=False)
    monkeypatch.delenv("EA_ONEMIN_BROWSERACT_HARD_MAX_ACCOUNTS_PER_REFRESH", raising=False)
    monkeypatch.delenv("EA_ONEMIN_BROWSERACT_HARD_MAX_PARALLELISM", raising=False)

    from app.api.routes import providers as providers_route

    assert providers_route._onemin_browseract_max_accounts_per_refresh() == 1
    assert providers_route._onemin_browseract_parallelism() == 1


def test_onemin_browseract_env_overrides_are_capped_by_host_safe_hard_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONEMIN_BROWSERACT_MAX_ACCOUNTS_PER_REFRESH", "59")
    monkeypatch.setenv("ONEMIN_BROWSERACT_PARALLELISM", "12")
    monkeypatch.delenv("EA_ONEMIN_BROWSERACT_HARD_MAX_ACCOUNTS_PER_REFRESH", raising=False)
    monkeypatch.delenv("EA_ONEMIN_BROWSERACT_HARD_MAX_PARALLELISM", raising=False)

    from app.api.routes import providers as providers_route

    assert providers_route._onemin_browseract_max_accounts_per_refresh() == 1
    assert providers_route._onemin_browseract_parallelism() == 1


def test_onemin_browseract_hard_limits_can_be_raised_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONEMIN_BROWSERACT_MAX_ACCOUNTS_PER_REFRESH", "59")
    monkeypatch.setenv("ONEMIN_BROWSERACT_PARALLELISM", "12")
    monkeypatch.setenv("EA_ONEMIN_BROWSERACT_HARD_MAX_ACCOUNTS_PER_REFRESH", "3")
    monkeypatch.setenv("EA_ONEMIN_BROWSERACT_HARD_MAX_PARALLELISM", "2")

    from app.api.routes import providers as providers_route

    assert providers_route._onemin_browseract_max_accounts_per_refresh() == 3
    assert providers_route._onemin_browseract_parallelism() == 2
