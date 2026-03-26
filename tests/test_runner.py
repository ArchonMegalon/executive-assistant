from __future__ import annotations

import importlib
import logging
import sys
from types import SimpleNamespace

import pytest

from app.domain.models import ConnectorBinding


def _load_runner_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=lambda *args, **kwargs: None))
    return importlib.import_module("app.runner")


def test_scheduler_onemin_billing_refresh_runs_browseract_and_provider_api_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import providers as providers_route
    runner = _load_runner_module(monkeypatch)

    calls: list[tuple[str, str, str]] = []
    finished: list[bool] = []

    binding = ConnectorBinding(
        binding_id="binding-1",
        principal_id="principal-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={},
        auth_metadata_json={"onemin_account_name": "ONEMIN_AI_API_KEY"},
        status="enabled",
        created_at="2026-03-26T00:00:00Z",
        updated_at="2026-03-26T00:00:00Z",
    )

    container = SimpleNamespace(
        onemin_manager=SimpleNamespace(
            begin_billing_refresh=lambda: (True, 0.0, ""),
            finish_billing_refresh=lambda: finished.append(True),
        ),
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: [binding]
        ),
    )

    monkeypatch.setattr(providers_route, "_onemin_browseract_max_accounts_per_refresh", lambda: 2)
    monkeypatch.setattr(providers_route, "_onemin_direct_api_batch_backoff_seconds", lambda: 0.0)
    monkeypatch.setattr(providers_route, "_binding_run_url", lambda *args, **kwargs: "")
    monkeypatch.setattr(providers_route, "_binding_workflow_id", lambda *args, **kwargs: "")
    monkeypatch.setattr(providers_route, "_resolve_onemin_account_labels", lambda _binding: {"ONEMIN_AI_API_KEY"})
    monkeypatch.setattr(providers_route, "_browseract_onemin_login_ready", lambda **_kwargs: True)

    def fake_invoke_browseract_tool(*, container, principal_id: str, tool_name: str, action_kind: str, payload_json: dict[str, object]):
        calls.append((principal_id, tool_name, str(payload_json.get("account_label") or "")))
        return {"account_label": payload_json.get("account_label"), "refresh_backend": tool_name}

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)
    monkeypatch.setattr(
        providers_route,
        "_refresh_onemin_via_provider_api",
        lambda **_kwargs: ([{"account_label": "ONEMIN_AI_API_KEY"}], [{"account_label": "ONEMIN_AI_API_KEY"}], [], 4, 0, False),
    )

    summary = runner._run_scheduler_onemin_billing_refresh(container, logging.getLogger("test.runner"))

    assert summary["ran"] is True
    assert summary["throttled"] is False
    assert summary["browseract_attempted"] == 1
    assert summary["browseract_refreshed"] == 1
    assert summary["member_reconciled"] == 1
    assert summary["api_attempted"] == 4
    assert summary["api_rate_limited"] is False
    assert summary["errors"] == 0
    assert calls == [
        ("principal-1", "browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY"),
        ("principal-1", "browseract.onemin_member_reconciliation", "ONEMIN_AI_API_KEY"),
    ]
    assert finished == [True]


def test_scheduler_onemin_billing_refresh_respects_manager_throttle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)
    finished: list[bool] = []
    container = SimpleNamespace(
        onemin_manager=SimpleNamespace(
            begin_billing_refresh=lambda: (False, 42.0, "cadence"),
            finish_billing_refresh=lambda: finished.append(True),
        ),
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: []
        ),
    )

    summary = runner._run_scheduler_onemin_billing_refresh(container, logging.getLogger("test.runner"))

    assert summary["ran"] is False
    assert summary["throttled"] is True
    assert summary["throttle_seconds_remaining"] == 42.0
    assert summary["throttle_reason"] == "cadence"
    assert summary["browseract_attempted"] == 0
    assert summary["api_attempted"] == 0
    assert finished == []
