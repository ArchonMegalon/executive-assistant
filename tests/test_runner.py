from __future__ import annotations

from contextlib import contextmanager
import importlib
import logging
import sys
from types import SimpleNamespace

import pytest

from app.domain.models import ConnectorBinding


def _load_runner_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=lambda *args, **kwargs: None))
    return importlib.import_module("app.runner")


def test_run_api_uses_main_asgi_target(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner_module(monkeypatch)
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    monkeypatch.setattr(
        runner.uvicorn,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    runner._run_api()

    assert calls
    assert calls[0][0] == ("app.main:app",)


def test_runner_no_longer_exposes_openvoice_tts_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner_module(monkeypatch)

    assert not hasattr(runner, "_run_openvoice")


def test_scheduler_pushbullet_relay_enabled_prefers_explicit_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner_module(monkeypatch)

    monkeypatch.delenv("EA_SCHEDULER_PUSHBULLET_RELAY_ENABLED", raising=False)
    monkeypatch.setenv("EA_PUSHBULLET_RELAY_ENABLED", "1")
    assert runner._scheduler_pushbullet_relay_enabled() is True

    monkeypatch.setenv("EA_SCHEDULER_PUSHBULLET_RELAY_ENABLED", "0")
    assert runner._scheduler_pushbullet_relay_enabled() is False


def test_run_scheduler_pushbullet_relay_returns_service_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner_module(monkeypatch)
    observed: dict[str, object] = {}

    def _fake_run_pushbullet_relay_once(*, timeout: float = 20.0):
        observed["timeout"] = timeout
        return {
            "ran": True,
            "forwarded_total": 1,
            "inspected_total": 2,
            "matched_total": 1,
            "skipped_total": 1,
            "blocked_rule_count": 0,
            "primed_rule_count": 0,
            "errors": 0,
            "rules": [],
        }

    import sys

    sys.modules["app.services.pushbullet_relay"] = SimpleNamespace(run_pushbullet_relay_once=_fake_run_pushbullet_relay_once)
    try:
        summary = runner._run_scheduler_pushbullet_relay(SimpleNamespace(), logging.getLogger("test.runner"))
    finally:
        sys.modules.pop("app.services.pushbullet_relay", None)

    assert observed["timeout"] == 20.0
    assert summary["forwarded_total"] == 1
    assert summary["errors"] == 0


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
    assert summary["api_attempted"] == 0
    assert summary["api_rate_limited"] is False
    assert summary["errors"] == 0
    assert calls == [
        ("principal-1", "browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY"),
        ("principal-1", "browseract.onemin_member_reconciliation", "ONEMIN_AI_API_KEY"),
    ]
    assert finished == [True]


def test_scheduler_onemin_billing_refresh_provisions_fastestvpn_for_browseract_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import providers as providers_route
    runner = _load_runner_module(monkeypatch)

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
            finish_billing_refresh=lambda: None,
        ),
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: [binding]
        ),
    )

    monkeypatch.setenv("EA_UI_BROWSER_PROXY_SERVER", "http://ea-fastestvpn-proxy:3128")
    monkeypatch.setattr(providers_route, "_onemin_browseract_max_accounts_per_refresh", lambda: 1)
    monkeypatch.setattr(providers_route, "_onemin_direct_api_batch_backoff_seconds", lambda: 0.0)
    monkeypatch.setattr(providers_route, "_binding_run_url", lambda *args, **kwargs: "")
    monkeypatch.setattr(providers_route, "_binding_workflow_id", lambda *args, **kwargs: "")
    monkeypatch.setattr(providers_route, "_resolve_onemin_account_labels", lambda _binding: {"ONEMIN_AI_API_KEY"})
    monkeypatch.setattr(providers_route, "_browseract_onemin_login_ready", lambda **_kwargs: True)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", lambda **_kwargs: ([], [], [], 0, 0, False))
    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", lambda **_kwargs: {"account_label": "ONEMIN_AI_API_KEY", "refresh_backend": "browseract"})

    observed: list[tuple[tuple[str, ...], str]] = []

    @contextmanager
    def fake_managed_fastestvpn_services(*, service_names, reason):
        observed.append((tuple(service_names), reason))
        yield {}

    monkeypatch.setattr(providers_route, "_managed_fastestvpn_services", fake_managed_fastestvpn_services)

    summary = runner._run_scheduler_onemin_billing_refresh(container, logging.getLogger("test.runner"))

    assert summary["ran"] is True
    assert observed == [(("ea-fastestvpn-proxy",), "scheduler.onemin.browseract.refresh")]


def test_scheduler_onemin_billing_refresh_recovers_browseract_failures_via_provider_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import providers as providers_route
    runner = _load_runner_module(monkeypatch)

    calls: list[tuple[str, str, str]] = []
    refresh_calls: list[dict[str, object]] = []
    finished: list[bool] = []

    binding = ConnectorBinding(
        binding_id="binding-1",
        principal_id="principal-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={},
        auth_metadata_json={
            "onemin_account_names": [
                "ONEMIN_AI_API_KEY",
                "ONEMIN_AI_API_KEY_FALLBACK_1",
            ]
        },
        status="enabled",
        created_at="2026-03-26T00:00:00Z",
        updated_at="2026-03-26T00:00:00Z",
    )

    container = SimpleNamespace(
        onemin_manager=SimpleNamespace(
            begin_billing_refresh=lambda: (True, 0.0, ""),
            finish_billing_refresh=lambda: finished.append(True),
            select_billing_refresh_account_labels=lambda labels, limit: tuple(list(labels)[:limit]),
        ),
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: [binding]
        ),
    )

    monkeypatch.setattr(providers_route, "_onemin_browseract_max_accounts_per_refresh", lambda: 4)
    monkeypatch.setattr(providers_route, "_onemin_direct_api_batch_backoff_seconds", lambda: 0.0)
    monkeypatch.setattr(providers_route, "_binding_run_url", lambda *args, **kwargs: "")
    monkeypatch.setattr(providers_route, "_binding_workflow_id", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        providers_route,
        "_resolve_onemin_account_labels",
        lambda _binding: {"ONEMIN_AI_API_KEY", "ONEMIN_AI_API_KEY_FALLBACK_1"},
    )
    monkeypatch.setattr(providers_route, "_browseract_onemin_login_ready", lambda **_kwargs: True)
    monkeypatch.setattr(
        providers_route,
        "_partition_onemin_browseract_account_labels",
        lambda **_kwargs: (
            ["ONEMIN_AI_API_KEY", "ONEMIN_AI_API_KEY_FALLBACK_1"],
            [],
        ),
    )
    monkeypatch.setattr(
        providers_route.upstream,
        "onemin_account_login_credentials",
        lambda **_kwargs: {"login_email": "owner@example.com", "login_password": "slotpass"},
    )

    def fake_invoke_browseract_tool(*, container, principal_id: str, tool_name: str, action_kind: str, payload_json: dict[str, object]):
        account_label = str(payload_json.get("account_label") or "")
        calls.append((principal_id, tool_name, account_label))
        if tool_name == "browseract.onemin_billing_usage" and account_label == "ONEMIN_AI_API_KEY_FALLBACK_1":
            raise providers_route.ToolExecutionError(
                "ui_service_worker_failed:onemin_billing_usage:auth_request_failed"
            )
        return {"account_label": account_label, "refresh_backend": tool_name}

    def fake_refresh(**kwargs):
        refresh_calls.append(dict(kwargs))
        return (
            [{"account_label": "ONEMIN_AI_API_KEY_FALLBACK_1"}],
            [{"account_label": "ONEMIN_AI_API_KEY_FALLBACK_1"}],
            [],
            1,
            0,
            False,
        )

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", fake_refresh)
    monkeypatch.setenv("EA_SCHEDULER_ONEMIN_GLOBAL_PROVIDER_API_SWEEP", "0")

    summary = runner._run_scheduler_onemin_billing_refresh(container, logging.getLogger("test.runner"))

    assert summary["ran"] is True
    assert summary["browseract_attempted"] == 2
    assert summary["browseract_refreshed"] == 1
    assert summary["browseract_failed"] == 1
    assert summary["member_reconciled"] == 2
    assert summary["api_attempted"] == 1
    assert summary["api_recovered"] == 1
    assert summary["errors"] == 0
    assert refresh_calls == [
        {
            "include_members": True,
            "timeout_seconds": 180,
            "all_accounts": False,
            "continue_on_rate_limit": False,
            "account_labels": {"ONEMIN_AI_API_KEY_FALLBACK_1"},
            "account_login_credentials": {
                "ONEMIN_AI_API_KEY_FALLBACK_1": {
                    "login_email": "owner@example.com",
                    "login_password": "slotpass",
                }
            },
        }
    ]
    assert sorted(calls) == sorted(
        [
            ("principal-1", "browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY"),
            ("principal-1", "browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY_FALLBACK_1"),
            ("principal-1", "browseract.onemin_member_reconciliation", "ONEMIN_AI_API_KEY"),
        ]
    )
    assert finished == [True]


def test_scheduler_onemin_billing_refresh_uses_owner_ledger_accounts_without_trusted_binding_mapping(
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
        auth_metadata_json={},
        status="enabled",
        created_at="2026-03-26T00:00:00Z",
        updated_at="2026-03-26T00:00:00Z",
    )

    container = SimpleNamespace(
        onemin_manager=SimpleNamespace(
            begin_billing_refresh=lambda: (True, 0.0, ""),
            finish_billing_refresh=lambda: finished.append(True),
            select_billing_refresh_account_labels=lambda labels, limit: tuple(list(labels)[:limit]),
        ),
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: [binding]
        ),
    )

    monkeypatch.setattr(providers_route, "_onemin_browseract_max_accounts_per_refresh", lambda: 4)
    monkeypatch.setattr(providers_route, "_binding_run_url", lambda *args, **kwargs: "")
    monkeypatch.setattr(providers_route, "_binding_workflow_id", lambda *args, **kwargs: "")
    monkeypatch.setattr(providers_route, "_resolve_onemin_account_labels", lambda _binding: ())
    monkeypatch.setattr(
        providers_route,
        "_normalized_onemin_owner_rows",
        lambda **_kwargs: [
            {"account_name": "ONEMIN_AI_API_KEY", "owner_email": "owner-1@example.com"},
            {"account_name": "ONEMIN_AI_API_KEY_FALLBACK_1", "owner_email": "owner-2@example.com"},
        ],
    )
    monkeypatch.setattr(
        providers_route,
        "_partition_onemin_browseract_account_labels",
        lambda **_kwargs: (
            ["ONEMIN_AI_API_KEY", "ONEMIN_AI_API_KEY_FALLBACK_1"],
            [],
        ),
    )
    monkeypatch.setattr(providers_route, "_browseract_onemin_login_ready", lambda **_kwargs: True)
    monkeypatch.setattr(providers_route.upstream, "onemin_account_login_credentials", lambda **_kwargs: {})
    monkeypatch.setenv("EA_SCHEDULER_ONEMIN_GLOBAL_PROVIDER_API_SWEEP", "0")

    def fake_invoke_browseract_tool(*, container, principal_id: str, tool_name: str, action_kind: str, payload_json: dict[str, object]):
        account_label = str(payload_json.get("account_label") or "")
        calls.append((principal_id, tool_name, account_label))
        return {"account_label": account_label, "refresh_backend": tool_name}

    monkeypatch.setattr(providers_route, "_invoke_browseract_tool", fake_invoke_browseract_tool)
    monkeypatch.setattr(providers_route, "_refresh_onemin_via_provider_api", lambda **_kwargs: ([], [], [], 0, 0, False))

    summary = runner._run_scheduler_onemin_billing_refresh(container, logging.getLogger("test.runner"))

    assert summary["ran"] is True
    assert summary["browseract_attempted"] == 2
    assert summary["browseract_refreshed"] == 2
    assert summary["member_reconciled"] == 2
    assert summary["api_attempted"] == 0
    assert sorted(calls) == sorted(
        [
            ("principal-1", "browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY"),
            ("principal-1", "browseract.onemin_billing_usage", "ONEMIN_AI_API_KEY_FALLBACK_1"),
            ("principal-1", "browseract.onemin_member_reconciliation", "ONEMIN_AI_API_KEY"),
            ("principal-1", "browseract.onemin_member_reconciliation", "ONEMIN_AI_API_KEY_FALLBACK_1"),
        ]
    )
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


def test_scheduler_google_signal_sync_runs_for_enabled_google_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)

    calls: list[str] = []

    google_binding = ConnectorBinding(
        binding_id="binding-google-1",
        principal_id="principal-google-1",
        connector_name="google_workspace",
        external_account_ref="exec@example.com",
        scope_json={},
        auth_metadata_json={"google_email": "exec@example.com"},
        status="enabled",
        created_at="2026-03-26T00:00:00Z",
        updated_at="2026-03-26T00:00:00Z",
    )
    disabled_binding = ConnectorBinding(
        binding_id="binding-google-2",
        principal_id="principal-google-2",
        connector_name="google_workspace",
        external_account_ref="skip@example.com",
        scope_json={},
        auth_metadata_json={"google_email": "skip@example.com"},
        status="disabled",
        created_at="2026-03-26T00:00:00Z",
        updated_at="2026-03-26T00:00:00Z",
    )

    class _FakeService:
        def sync_google_workspace_signals(self, *, principal_id: str, actor: str, email_limit: int, calendar_limit: int):
            calls.append(f"{principal_id}|{actor}|{email_limit}|{calendar_limit}")
            return {"total": 2}

    container = SimpleNamespace(
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: [google_binding, disabled_binding]
        ),
    )

    monkeypatch.setitem(
        sys.modules,
        "app.product.service",
        SimpleNamespace(build_product_service=lambda _container: _FakeService()),
    )

    summary = runner._run_scheduler_google_signal_sync(container, logging.getLogger("test.runner"))

    assert summary == {"ran": True, "attempted": 1, "synced": 1, "errors": 0, "skipped": 0}
    assert calls == ["principal-google-1|scheduler|5|5"]


def test_scheduler_google_signal_sync_runs_configured_property_mailboxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)
    monkeypatch.setattr(runner, "assistant_property_lane_enabled", lambda: True)
    monkeypatch.setenv("EA_PROPERTY_ALERT_ACCOUNT_EMAILS", "property.alerts@example.test")

    calls: list[str] = []
    property_calls: list[str] = []
    google_binding = ConnectorBinding(
        binding_id="binding-google-1",
        principal_id="principal-google-1",
        connector_name="google_workspace",
        external_account_ref="principal.test",
        scope_json={},
        auth_metadata_json={"google_email": "principal.test"},
        status="enabled",
        created_at="2026-03-26T00:00:00Z",
        updated_at="2026-03-26T00:00:00Z",
    )

    class _FakeService:
        def sync_google_workspace_signals(self, *, principal_id: str, actor: str, email_limit: int, calendar_limit: int):
            calls.append(f"{principal_id}|{actor}|{email_limit}|{calendar_limit}")
            return {"total": 0}

        def sync_google_willhaben_signals(self, *, principal_id: str, actor: str, account_email: str, email_limit: int):
            property_calls.append(f"{principal_id}|{actor}|{account_email}|{email_limit}")
            return {"synced_total": 2}

    container = SimpleNamespace(
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: [google_binding]
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.product.service",
        SimpleNamespace(build_product_service=lambda _container: _FakeService()),
    )

    summary = runner._run_scheduler_google_signal_sync(container, logging.getLogger("test.runner"))

    assert summary == {
        "ran": True,
        "attempted": 1,
        "synced": 1,
        "errors": 0,
        "skipped": 0,
        "property_accounts": ["property.alerts@example.test"],
        "property_attempted": 1,
        "property_synced": 2,
    }
    assert calls == ["principal-google-1|scheduler|5|5"]
    assert property_calls == ["principal-google-1|scheduler|property.alerts@example.test|10"]


def test_scheduler_google_signal_sync_runtime_invalid_grant_enters_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)
    monkeypatch.setenv("EA_SCHEDULER_GOOGLE_SIGNAL_SYNC_RUNTIME_COOLDOWN_SECONDS", "600")
    runner._SCHEDULER_GOOGLE_SIGNAL_SYNC_RUNTIME_COOLDOWNS.clear()

    google_binding = ConnectorBinding(
        binding_id="binding-google-runtime-1",
        principal_id="principal-google-runtime-1",
        connector_name="google_workspace",
        external_account_ref="exec@example.com",
        scope_json={},
        auth_metadata_json={"google_email": "exec@example.com"},
        status="enabled",
        created_at="2026-03-26T00:00:00Z",
        updated_at="2026-03-26T00:00:00Z",
    )
    calls: list[str] = []
    observations: list[dict[str, object]] = []

    class _FakeService:
        def sync_google_workspace_signals(self, *, principal_id: str, actor: str, email_limit: int, calendar_limit: int):
            calls.append(f"{principal_id}|{actor}|{email_limit}|{calendar_limit}")
            raise RuntimeError("google_oauth_invalid_grant")

    container = SimpleNamespace(
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: [google_binding]
        ),
        channel_runtime=SimpleNamespace(ingest_observation=lambda **kwargs: observations.append(dict(kwargs))),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.product.service",
        SimpleNamespace(build_product_service=lambda _container: _FakeService()),
    )
    monkeypatch.setattr(runner.time, "time", lambda: 1000.0)

    summary = runner._run_scheduler_google_signal_sync(container, logging.getLogger("test.runner"))

    assert summary == {"ran": True, "attempted": 1, "synced": 0, "errors": 1, "skipped": 0}
    assert calls == ["principal-google-runtime-1|scheduler|5|5"]
    state = runner._SCHEDULER_GOOGLE_SIGNAL_SYNC_RUNTIME_COOLDOWNS["principal-google-runtime-1"]
    assert state["reason"] == "google_oauth_invalid_grant"
    assert state["blocked_until"] == 1600.0
    assert observations == [
        {
            "principal_id": "principal-google-runtime-1",
            "channel": "product",
            "event_type": "google_workspace_signal_sync_recovery_blocked",
            "payload": {
                "reason": "google_oauth_invalid_grant",
                "blocked_at": "1970-01-01T00:16:40Z",
                "blocked_until": "1970-01-01T00:26:40Z",
                "cooldown_seconds": 600,
                "cooldown_active": True,
                "recovery_mode": "scheduler_cooldown",
                "raw_credential_exposed": False,
                "raw_payload_exposed": False,
            },
            "source_id": "google-workspace-signal-sync-recovery-blocked:principal-google-runtime-1:1600",
            "dedupe_key": "google-workspace-signal-sync-recovery-blocked:principal-google-runtime-1:1600",
        }
    ]


def test_scheduler_google_signal_sync_runtime_cooldown_skips_repeated_reauth_attempts(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = _load_runner_module(monkeypatch)
    runner._SCHEDULER_GOOGLE_SIGNAL_SYNC_RUNTIME_COOLDOWNS.clear()
    runner._SCHEDULER_GOOGLE_SIGNAL_SYNC_RUNTIME_COOLDOWNS["principal-google-runtime-2"] = {
        "reason": "google_oauth_invalid_grant",
        "blocked_until": 1600.0,
        "last_logged_at": 0.0,
    }

    google_binding = ConnectorBinding(
        binding_id="binding-google-runtime-2",
        principal_id="principal-google-runtime-2",
        connector_name="google_workspace",
        external_account_ref="exec@example.com",
        scope_json={},
        auth_metadata_json={"google_email": "exec@example.com"},
        status="enabled",
        created_at="2026-03-26T00:00:00Z",
        updated_at="2026-03-26T00:00:00Z",
    )
    calls: list[str] = []

    class _FakeService:
        def sync_google_workspace_signals(self, *, principal_id: str, actor: str, email_limit: int, calendar_limit: int):
            calls.append(f"{principal_id}|{actor}|{email_limit}|{calendar_limit}")
            return {"total": 1}

    container = SimpleNamespace(
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: [google_binding]
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.product.service",
        SimpleNamespace(build_product_service=lambda _container: _FakeService()),
    )
    monkeypatch.setattr(runner.time, "time", lambda: 1000.0)
    caplog.set_level(logging.DEBUG, logger="test.runner")

    summary = runner._run_scheduler_google_signal_sync(container, logging.getLogger("test.runner"))

    assert summary == {"ran": True, "attempted": 0, "synced": 0, "errors": 0, "skipped": 1}
    assert calls == []
    assert any("scheduler google signal sync cooldown" in record.getMessage() for record in caplog.records)

def test_scheduler_pocket_signal_sync_runs_for_default_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)
    monkeypatch.setenv("POCKET_API_KEY", "pk_test")
    monkeypatch.setenv("EA_SCHEDULER_POCKET_SIGNAL_SYNC_LIMIT", "7")

    calls: list[str] = []

    class _FakeService:
        def sync_pocket_recordings(self, *, principal_id: str, actor: str, limit: int):
            calls.append(f"{principal_id}|{actor}|{limit}")
            return {"total": 3}

    container = SimpleNamespace(
        settings=SimpleNamespace(
            auth=SimpleNamespace(default_principal_id="principal-default"),
        ),
    )

    monkeypatch.setitem(
        sys.modules,
        "app.product.service",
        SimpleNamespace(build_product_service=lambda _container: _FakeService()),
    )

    summary = runner._run_scheduler_pocket_signal_sync(container, logging.getLogger("test.runner"))

    assert summary == {"ran": True, "attempted": 1, "synced": 3, "errors": 0, "principal_id": "principal-default"}
    assert calls == ["principal-default|scheduler|7"]


def test_scheduler_alexa_history_sync_runs_for_default_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)
    monkeypatch.setenv("EA_ALEXA_HISTORY_IMPORT_ROOT", "/tmp/alexa-history")
    monkeypatch.setenv("EA_SCHEDULER_ALEXA_HISTORY_SYNC_LIMIT", "9")

    calls: list[str] = []

    class _FakeService:
        def sync_alexa_history_from_import_root(self, *, principal_id: str, actor: str, limit: int, force: bool):
            calls.append(f"{principal_id}|{actor}|{limit}|{force}")
            return {
                "synced_total": 4,
                "processed_source_total": 2,
                "skipped_source_total": 3,
                "teable_index_status": "synced",
                "teable_index_blocked_reason": "",
            }

    container = SimpleNamespace(
        settings=SimpleNamespace(
            auth=SimpleNamespace(default_principal_id="principal-default"),
        ),
    )

    monkeypatch.setitem(
        sys.modules,
        "app.product.service",
        SimpleNamespace(build_product_service=lambda _container: _FakeService()),
    )

    summary = runner._run_scheduler_alexa_history_sync(container, logging.getLogger("test.runner"))

    assert summary == {
        "ran": True,
        "attempted": 5,
        "synced": 4,
        "errors": 0,
        "principal_id": "principal-default",
        "processed_source_total": 2,
        "skipped_source_total": 3,
        "teable_index_status": "synced",
        "teable_index_blocked_reason": "",
    }
    assert calls == ["principal-default|scheduler|9|False"]


def test_scheduler_property_scout_runs_for_configured_principals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)
    monkeypatch.setenv("EA_PROPERTY_SCOUT_PRINCIPAL_IDS", "principal-b, principal-a, principal-a")

    calls: list[str] = []

    class _FakeService:
        def sync_direct_property_scout(self, *, principal_id: str, actor: str):
            calls.append(f"{principal_id}|{actor}")
            return {"status": "processed", "review_created_total": 2}

    container = SimpleNamespace(settings=SimpleNamespace(auth=SimpleNamespace(default_principal_id="fallback")))
    monkeypatch.setitem(
        sys.modules,
        "app.product.service",
        SimpleNamespace(build_product_service=lambda _container: _FakeService()),
    )

    summary = runner._run_scheduler_property_scout(container, logging.getLogger("test.runner"))

    assert summary == {
        "ran": True,
        "attempted": 2,
        "synced": 4,
        "errors": 0,
        "principals": ["principal-a", "principal-b"],
    }
    assert calls == ["principal-a|scheduler", "principal-b|scheduler"]


def test_scheduler_property_only_profile_helper_accepts_property_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)

    monkeypatch.delenv("PROPERTYQUARRY_SCHEDULER_PROFILE", raising=False)
    assert runner._scheduler_property_only_profile_enabled() is False

    for value in ("property_only", "property-only", "property"):
        monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", value)
        assert runner._scheduler_property_only_profile_enabled() is True

    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "full")
    assert runner._scheduler_property_only_profile_enabled() is False


def test_worker_property_only_profile_helper_accepts_property_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)

    monkeypatch.delenv("PROPERTYQUARRY_WORKER_PROFILE", raising=False)
    assert runner._worker_property_only_profile_enabled() is False

    for value in ("property_only", "property-only", "property"):
        monkeypatch.setenv("PROPERTYQUARRY_WORKER_PROFILE", value)
        assert runner._worker_property_only_profile_enabled() is True

    monkeypatch.setenv("PROPERTYQUARRY_WORKER_PROFILE", "full")
    assert runner._worker_property_only_profile_enabled() is False


def test_scheduler_morning_memo_delivery_sends_once_when_due(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner_module(monkeypatch)
    monkeypatch.setenv("EA_SCHEDULER_DIGEST_EMAIL_ENABLED", "1")

    google_binding = ConnectorBinding(
        binding_id="binding-google-1",
        principal_id="principal-memo-1",
        connector_name="google_workspace",
        external_account_ref="exec@example.com",
        scope_json={},
        auth_metadata_json={"google_email": "exec@example.com"},
        status="enabled",
        created_at="2026-03-30T00:00:00Z",
        updated_at="2026-03-30T00:00:00Z",
    )
    preference = SimpleNamespace(
        preference_id="pref-memo-1",
        principal_id="principal-memo-1",
        channel="email",
        recipient_ref="morning_memo_primary",
        cadence="weekdays_morning",
        quiet_hours_json={
            "timezone": "UTC",
            "delivery_time_local": "08:00",
            "quiet_hours_start": "20:00",
            "quiet_hours_end": "07:00",
            "delivery_window_minutes": 120,
        },
        format_json={
            "schedule_kind": "morning_memo",
            "digest_key": "memo",
            "role": "principal",
            "display_name": "Exec One",
            "delivery_channel": "email",
            "allow_scheduler_email": True,
            "retry_after_minutes": 60,
        },
        status="active",
    )

    service_calls: list[tuple[str, str, str]] = []
    ingested_events: list[tuple[str, str]] = []
    dedupe_index: dict[str, SimpleNamespace] = {}

    class _FakeChannelRuntime:
        def find_observation_by_dedupe(self, dedupe_key: str, *, principal_id: str | None = None):
            return dedupe_index.get(dedupe_key)

        def list_recent_observations(self, limit: int = 50, principal_id: str | None = None):
            return []

        def ingest_observation(
            self,
            principal_id: str,
            channel: str,
            event_type: str,
            payload: dict[str, object] | None = None,
            *,
            source_id: str = "",
            external_id: str = "",
            dedupe_key: str = "",
            auth_context_json: dict[str, object] | None = None,
            raw_payload_uri: str = "",
        ):
            ingested_events.append((event_type, dedupe_key))
            row = SimpleNamespace(
                event_type=event_type,
                payload=dict(payload or {}),
                created_at="2026-03-30T08:05:00+00:00",
            )
            if dedupe_key:
                dedupe_index[dedupe_key] = row
            return row

    class _FakeService:
        def channel_digest_pack(self, *, principal_id: str, digest_key: str, operator_id: str = ""):
            return {"key": digest_key, "items": [{"title": "Memo", "tag": "Memo"}]}

        def issue_channel_digest_delivery(
            self,
            *,
            principal_id: str,
            digest_key: str,
            recipient_email: str,
            role: str,
            display_name: str = "",
            operator_id: str = "",
            delivery_channel: str = "email",
            expires_in_hours: int = 72,
            base_url: str = "",
        ):
            service_calls.append((principal_id, digest_key, recipient_email))
            return {
                "delivery_id": "digest-1",
                "digest_key": digest_key,
                "email_delivery_status": "sent",
            }

    container = SimpleNamespace(
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: [google_binding]
        ),
        memory_runtime=SimpleNamespace(
            list_delivery_preferences=lambda principal_id, limit=50, status=None: [preference]
        ),
        channel_runtime=_FakeChannelRuntime(),
    )

    monkeypatch.setitem(
        sys.modules,
        "app.product.service",
        SimpleNamespace(build_product_service=lambda _container: _FakeService()),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.registration_email",
        SimpleNamespace(email_delivery_enabled=lambda: True),
    )

    now_utc = runner.datetime(2026, 3, 30, 8, 5, tzinfo=runner.timezone.utc)
    summary = runner._run_scheduler_morning_memo_delivery(
        container,
        logging.getLogger("test.runner"),
        now_utc=now_utc,
    )

    assert summary == {
        "ran": True,
        "configured": 1,
        "due": 1,
        "sent": 1,
        "blocked": 0,
        "failed": 0,
        "skipped": 0,
        "budget_deferred": 0,
        "errors": 0,
    }
    assert service_calls == [("principal-memo-1", "memo", "exec@example.com")]
    assert ingested_events == [
        ("scheduled_morning_memo_delivery_sent", "principal-memo-1|scheduled-morning-memo|pref-memo-1|2026-03-30|sent")
    ]

    second_summary = runner._run_scheduler_morning_memo_delivery(
        container,
        logging.getLogger("test.runner"),
        now_utc=now_utc,
    )
    assert second_summary["sent"] == 0
    assert second_summary["skipped"] == 1


def test_scheduler_morning_memo_delivery_respects_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner_module(monkeypatch)
    monkeypatch.setenv("EA_SCHEDULER_DIGEST_EMAIL_ENABLED", "1")

    google_binding = ConnectorBinding(
        binding_id="binding-google-1",
        principal_id="principal-memo-2",
        connector_name="google_workspace",
        external_account_ref="exec@example.com",
        scope_json={},
        auth_metadata_json={"google_email": "exec@example.com"},
        status="enabled",
        created_at="2026-03-30T00:00:00Z",
        updated_at="2026-03-30T00:00:00Z",
    )
    preference = SimpleNamespace(
        preference_id="pref-memo-2",
        principal_id="principal-memo-2",
        channel="email",
        recipient_ref="morning_memo_primary",
        cadence="daily_morning",
        quiet_hours_json={
            "timezone": "UTC",
            "delivery_time_local": "08:00",
            "quiet_hours_start": "20:00",
            "quiet_hours_end": "07:00",
            "delivery_window_minutes": 120,
        },
        format_json={
            "schedule_kind": "morning_memo",
            "digest_key": "memo",
            "role": "principal",
            "display_name": "Exec Two",
            "delivery_channel": "email",
            "retry_after_minutes": 60,
        },
        status="active",
    )
    recent_failure = SimpleNamespace(
        event_type="scheduled_morning_memo_delivery_failed",
        payload={"schedule_key": "pref-memo-2", "local_day": "2026-03-30"},
        created_at="2026-03-30T07:40:00+00:00",
    )
    service_calls: list[str] = []

    class _FakeService:
        def channel_digest_pack(self, *, principal_id: str, digest_key: str, operator_id: str = ""):
            return {"key": digest_key, "items": [{"title": "Memo", "tag": "Memo"}]}

        def issue_channel_digest_delivery(self, **kwargs):
            service_calls.append("called")
            return {"delivery_id": "digest-2", "digest_key": "memo", "email_delivery_status": "sent"}

    container = SimpleNamespace(
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: [google_binding]
        ),
        memory_runtime=SimpleNamespace(
            list_delivery_preferences=lambda principal_id, limit=50, status=None: [preference]
        ),
        channel_runtime=SimpleNamespace(
            find_observation_by_dedupe=lambda dedupe_key, principal_id=None: None,
            list_recent_observations=lambda limit=50, principal_id=None: [recent_failure],
            ingest_observation=lambda *args, **kwargs: None,
        ),
    )

    monkeypatch.setitem(
        sys.modules,
        "app.product.service",
        SimpleNamespace(build_product_service=lambda _container: _FakeService()),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.registration_email",
        SimpleNamespace(email_delivery_enabled=lambda: True),
    )

    now_utc = runner.datetime(2026, 3, 30, 8, 5, tzinfo=runner.timezone.utc)
    summary = runner._run_scheduler_morning_memo_delivery(
        container,
        logging.getLogger("test.runner"),
        now_utc=now_utc,
    )

    assert summary == {
        "ran": True,
        "configured": 1,
        "due": 1,
        "sent": 0,
        "blocked": 1,
        "failed": 0,
        "skipped": 0,
        "budget_deferred": 0,
        "errors": 0,
    }
    assert service_calls == []


def test_scheduler_morning_memo_delivery_blocks_email_when_digest_email_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)
    monkeypatch.setenv("EA_SCHEDULER_DIGEST_EMAIL_ENABLED", "0")

    google_binding = ConnectorBinding(
        binding_id="binding-google-guard-1",
        principal_id="principal-memo-guard-1",
        connector_name="google_workspace",
        external_account_ref="exec@example.com",
        scope_json={},
        auth_metadata_json={"google_email": "exec@example.com"},
        status="enabled",
        created_at="2026-03-30T00:00:00Z",
        updated_at="2026-03-30T00:00:00Z",
    )
    preference = SimpleNamespace(
        preference_id="pref-memo-guard-1",
        principal_id="principal-memo-guard-1",
        channel="email",
        recipient_ref="morning_memo_primary",
        cadence="daily_morning",
        quiet_hours_json={
            "timezone": "UTC",
            "delivery_time_local": "08:00",
            "quiet_hours_start": "20:00",
            "quiet_hours_end": "07:00",
            "delivery_window_minutes": 120,
        },
        format_json={
            "schedule_kind": "morning_memo",
            "digest_key": "memo",
            "role": "principal",
            "display_name": "Exec Guard",
            "delivery_channel": "email",
            "retry_after_minutes": 60,
        },
        status="active",
    )

    service_calls: list[str] = []
    ingested_events: list[tuple[str, str, dict[str, object]]] = []

    class _FakeChannelRuntime:
        def find_observation_by_dedupe(self, dedupe_key: str, *, principal_id: str | None = None):
            return None

        def list_recent_observations(self, limit: int = 50, principal_id: str | None = None):
            return []

        def ingest_observation(
            self,
            principal_id: str,
            channel: str,
            event_type: str,
            payload: dict[str, object] | None = None,
            *,
            source_id: str = "",
            external_id: str = "",
            dedupe_key: str = "",
            auth_context_json: dict[str, object] | None = None,
            raw_payload_uri: str = "",
        ):
            ingested_events.append((event_type, dedupe_key, dict(payload or {})))
            return SimpleNamespace(
                event_type=event_type,
                payload=dict(payload or {}),
                created_at="2026-03-30T08:05:00+00:00",
            )

    class _FakeService:
        def channel_digest_pack(self, *, principal_id: str, digest_key: str, operator_id: str = ""):
            return {"key": digest_key, "items": [{"title": "Memo", "tag": "Memo"}]}

        def issue_channel_digest_delivery(self, **kwargs):
            service_calls.append("called")
            return {"delivery_id": "digest-guard-1", "digest_key": "memo", "email_delivery_status": "sent"}

    container = SimpleNamespace(
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: [google_binding]
        ),
        memory_runtime=SimpleNamespace(
            list_delivery_preferences=lambda principal_id, limit=50, status=None: [preference]
        ),
        channel_runtime=_FakeChannelRuntime(),
    )

    monkeypatch.setitem(
        sys.modules,
        "app.product.service",
        SimpleNamespace(build_product_service=lambda _container: _FakeService()),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.registration_email",
        SimpleNamespace(email_delivery_enabled=lambda: True),
    )

    now_utc = runner.datetime(2026, 3, 30, 8, 5, tzinfo=runner.timezone.utc)
    summary = runner._run_scheduler_morning_memo_delivery(
        container,
        logging.getLogger("test.runner"),
        now_utc=now_utc,
    )

    assert summary == {
        "ran": True,
        "configured": 1,
        "due": 1,
        "sent": 0,
        "blocked": 1,
        "failed": 0,
        "skipped": 0,
        "budget_deferred": 0,
        "errors": 0,
    }
    assert service_calls == []
    assert ingested_events == [
        (
            "scheduled_morning_memo_delivery_blocked",
            "principal-memo-guard-1|scheduled-morning-memo|pref-memo-guard-1|2026-03-30|email-disabled",
            {
                "schedule_key": "pref-memo-guard-1",
                "local_day": "2026-03-30",
                "reason": "scheduler_digest_email_disabled",
                "recipient_email": "exec@example.com",
            },
        )
    ]


def test_scheduler_morning_memo_delivery_blocks_email_when_not_explicitly_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)
    monkeypatch.setenv("EA_SCHEDULER_DIGEST_EMAIL_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_DIGEST_EMAIL_REQUIRE_EXPLICIT_ALLOWLIST", "1")

    google_binding = ConnectorBinding(
        binding_id="binding-google-guard-2",
        principal_id="principal-memo-guard-2",
        connector_name="google_workspace",
        external_account_ref="exec@example.com",
        scope_json={},
        auth_metadata_json={"google_email": "exec@example.com"},
        status="enabled",
        created_at="2026-03-30T00:00:00Z",
        updated_at="2026-03-30T00:00:00Z",
    )
    preference = SimpleNamespace(
        preference_id="pref-memo-guard-2",
        principal_id="principal-memo-guard-2",
        channel="email",
        recipient_ref="morning_memo_primary",
        cadence="daily_morning",
        quiet_hours_json={
            "timezone": "UTC",
            "delivery_time_local": "08:00",
            "quiet_hours_start": "20:00",
            "quiet_hours_end": "07:00",
            "delivery_window_minutes": 120,
        },
        format_json={
            "schedule_kind": "morning_memo",
            "digest_key": "memo",
            "role": "principal",
            "display_name": "Exec Guard Two",
            "delivery_channel": "email",
            "retry_after_minutes": 60,
        },
        status="active",
    )

    service_calls: list[str] = []
    ingested_events: list[tuple[str, str, dict[str, object]]] = []
    dedupe_index: dict[str, SimpleNamespace] = {}

    class _FakeChannelRuntime:
        def find_observation_by_dedupe(self, dedupe_key: str, *, principal_id: str | None = None):
            return dedupe_index.get(dedupe_key)

        def list_recent_observations(self, limit: int = 50, principal_id: str | None = None):
            return []

        def ingest_observation(
            self,
            principal_id: str,
            channel: str,
            event_type: str,
            payload: dict[str, object] | None = None,
            *,
            source_id: str = "",
            external_id: str = "",
            dedupe_key: str = "",
            auth_context_json: dict[str, object] | None = None,
            raw_payload_uri: str = "",
        ):
            ingested_events.append((event_type, dedupe_key, dict(payload or {})))
            row = SimpleNamespace(
                event_type=event_type,
                payload=dict(payload or {}),
                created_at="2026-03-30T08:05:00+00:00",
            )
            if dedupe_key:
                dedupe_index[dedupe_key] = row
            return row

    class _FakeService:
        def channel_digest_pack(self, *, principal_id: str, digest_key: str, operator_id: str = ""):
            return {"key": digest_key, "items": [{"title": "Memo", "tag": "Memo"}]}

        def issue_channel_digest_delivery(self, **kwargs):
            service_calls.append("called")
            return {"delivery_id": "digest-guard-2", "digest_key": "memo", "email_delivery_status": "sent"}

    container = SimpleNamespace(
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: [google_binding]
        ),
        memory_runtime=SimpleNamespace(
            list_delivery_preferences=lambda principal_id, limit=50, status=None: [preference]
        ),
        channel_runtime=_FakeChannelRuntime(),
    )

    monkeypatch.setitem(
        sys.modules,
        "app.product.service",
        SimpleNamespace(build_product_service=lambda _container: _FakeService()),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.registration_email",
        SimpleNamespace(email_delivery_enabled=lambda: True),
    )

    now_utc = runner.datetime(2026, 3, 30, 8, 5, tzinfo=runner.timezone.utc)
    summary = runner._run_scheduler_morning_memo_delivery(
        container,
        logging.getLogger("test.runner"),
        now_utc=now_utc,
    )
    second_summary = runner._run_scheduler_morning_memo_delivery(
        container,
        logging.getLogger("test.runner"),
        now_utc=now_utc,
    )

    assert summary == {
        "ran": True,
        "configured": 1,
        "due": 1,
        "sent": 0,
        "blocked": 1,
        "failed": 0,
        "skipped": 0,
        "budget_deferred": 0,
        "errors": 0,
    }
    assert second_summary == {
        "ran": True,
        "configured": 1,
        "due": 1,
        "sent": 0,
        "blocked": 1,
        "failed": 0,
        "skipped": 0,
        "budget_deferred": 0,
        "errors": 0,
    }
    assert service_calls == []
    assert ingested_events == [
        (
            "scheduled_morning_memo_delivery_blocked",
            "principal-memo-guard-2|scheduled-morning-memo|pref-memo-guard-2|2026-03-30|email-out-of-bounds",
            {
                "schedule_key": "pref-memo-guard-2",
                "local_day": "2026-03-30",
                "reason": "scheduler_digest_email_not_allowlisted",
                "recipient_email": "exec@example.com",
                "delivery_channel": "email",
            },
        )
    ]


def test_scheduler_actionable_nudge_delivery_sends_telegram_when_due(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner_module(monkeypatch)

    telegram_binding = ConnectorBinding(
        binding_id="binding-telegram-1",
        principal_id="principal-nudge-1",
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        scope_json={},
        auth_metadata_json={"default_chat_ref": "1354554303"},
        status="enabled",
        created_at="2026-03-30T00:00:00Z",
        updated_at="2026-03-30T00:00:00Z",
    )
    preference = SimpleNamespace(
        preference_id="pref-nudge-1",
        principal_id="principal-nudge-1",
        channel="telegram",
        recipient_ref="assistant_nudge_primary",
        cadence="daily_morning",
        quiet_hours_json={
            "timezone": "UTC",
            "delivery_time_local": "08:00",
            "quiet_hours_start": "20:00",
            "quiet_hours_end": "07:00",
            "delivery_window_minutes": 120,
        },
        format_json={
            "schedule_kind": "assistant_nudge",
            "digest_key": "assistant_nudge",
            "role": "principal",
            "display_name": "Exec Nudge",
            "delivery_channel": "telegram",
            "retry_after_minutes": 60,
        },
        status="active",
    )

    service_calls: list[tuple[str, str, str, str]] = []
    ingested_events: list[tuple[str, str]] = []
    dedupe_index: dict[str, SimpleNamespace] = {}

    class _FakeChannelRuntime:
        def find_observation_by_dedupe(self, dedupe_key: str, *, principal_id: str | None = None):
            return dedupe_index.get(dedupe_key)

        def list_recent_observations(self, limit: int = 50, principal_id: str | None = None):
            return []

        def ingest_observation(
            self,
            principal_id: str,
            channel: str,
            event_type: str,
            payload: dict[str, object] | None = None,
            *,
            source_id: str = "",
            external_id: str = "",
            dedupe_key: str = "",
            auth_context_json: dict[str, object] | None = None,
            raw_payload_uri: str = "",
        ):
            ingested_events.append((event_type, dedupe_key))
            row = SimpleNamespace(
                event_type=event_type,
                payload=dict(payload or {}),
                created_at="2026-03-30T08:05:00+00:00",
            )
            if dedupe_key:
                dedupe_index[dedupe_key] = row
            return row

    class _FakeService:
        def channel_digest_pack(self, *, principal_id: str, digest_key: str, operator_id: str = ""):
            assert principal_id == "principal-nudge-1"
            assert digest_key == "assistant_nudge"
            return {"key": "assistant_nudge", "items": [{"title": "Reply to landlord", "tag": "Approval"}]}

        def issue_channel_digest_delivery(
            self,
            *,
            principal_id: str,
            digest_key: str,
            recipient_email: str,
            role: str,
            display_name: str = "",
            operator_id: str = "",
            delivery_channel: str = "email",
            expires_in_hours: int = 72,
            base_url: str = "",
        ):
            service_calls.append((principal_id, digest_key, recipient_email, delivery_channel))
            return {
                "delivery_id": "digest-nudge-1",
                "digest_key": digest_key,
                "telegram_delivery_status": "sent",
            }

    container = SimpleNamespace(
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: [telegram_binding]
            if connector_name == "telegram_identity"
            else []
        ),
        memory_runtime=SimpleNamespace(
            list_delivery_preferences=lambda principal_id, limit=50, status=None: [preference]
        ),
        channel_runtime=_FakeChannelRuntime(),
    )

    monkeypatch.setitem(
        sys.modules,
        "app.product.service",
        SimpleNamespace(build_product_service=lambda _container: _FakeService()),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.registration_email",
        SimpleNamespace(email_delivery_enabled=lambda: True),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.telegram_onboarding_service",
        SimpleNamespace(TELEGRAM_IDENTITY_CONNECTOR="telegram_identity"),
    )

    now_utc = runner.datetime(2026, 3, 30, 8, 5, tzinfo=runner.timezone.utc)
    summary = runner._run_scheduler_morning_memo_delivery(
        container,
        logging.getLogger("test.runner"),
        now_utc=now_utc,
    )

    assert summary == {
        "ran": True,
        "configured": 1,
        "due": 1,
        "sent": 1,
        "blocked": 0,
        "failed": 0,
        "skipped": 0,
        "budget_deferred": 0,
        "errors": 0,
    }
    assert service_calls == [("principal-nudge-1", "assistant_nudge", "principal-nudge-1", "telegram")]
    assert ingested_events == [
        ("scheduled_morning_memo_delivery_sent", "principal-nudge-1|scheduled-morning-memo|pref-nudge-1|2026-03-30|sent")
    ]


def test_scheduler_morning_memo_delivery_defers_when_pass_budget_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)
    monkeypatch.setenv("EA_SCHEDULER_DIGEST_EMAIL_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_MORNING_MEMO_MAX_DELIVERIES_PER_PASS", "1")

    google_bindings = [
        ConnectorBinding(
            binding_id="binding-google-a",
            principal_id="principal-memo-a",
            connector_name="google_workspace",
            external_account_ref="exec-a@example.com",
            scope_json={},
            auth_metadata_json={"google_email": "exec-a@example.com"},
            status="enabled",
            created_at="2026-03-30T00:00:00Z",
            updated_at="2026-03-30T00:00:00Z",
        ),
        ConnectorBinding(
            binding_id="binding-google-b",
            principal_id="principal-memo-b",
            connector_name="google_workspace",
            external_account_ref="exec-b@example.com",
            scope_json={},
            auth_metadata_json={"google_email": "exec-b@example.com"},
            status="enabled",
            created_at="2026-03-30T00:00:00Z",
            updated_at="2026-03-30T00:00:00Z",
        ),
    ]
    preferences = {
        "principal-memo-a": [
            SimpleNamespace(
                preference_id="pref-memo-a",
                principal_id="principal-memo-a",
                channel="email",
                recipient_ref="morning_memo_primary",
                cadence="daily_morning",
                quiet_hours_json={
                    "timezone": "UTC",
                    "delivery_time_local": "08:00",
                    "quiet_hours_start": "20:00",
                    "quiet_hours_end": "07:00",
                    "delivery_window_minutes": 120,
                },
                format_json={
                    "schedule_kind": "morning_memo",
                    "digest_key": "memo",
                    "role": "principal",
                    "display_name": "Exec A",
                    "delivery_channel": "email",
                    "allow_scheduler_email": True,
                    "retry_after_minutes": 60,
                },
                status="active",
            )
        ],
        "principal-memo-b": [
            SimpleNamespace(
                preference_id="pref-memo-b",
                principal_id="principal-memo-b",
                channel="email",
                recipient_ref="morning_memo_primary",
                cadence="daily_morning",
                quiet_hours_json={
                    "timezone": "UTC",
                    "delivery_time_local": "08:00",
                    "quiet_hours_start": "20:00",
                    "quiet_hours_end": "07:00",
                    "delivery_window_minutes": 120,
                },
                format_json={
                    "schedule_kind": "morning_memo",
                    "digest_key": "memo",
                    "role": "principal",
                    "display_name": "Exec B",
                    "delivery_channel": "email",
                    "allow_scheduler_email": True,
                    "retry_after_minutes": 60,
                },
                status="active",
            )
        ],
    }

    service_calls: list[str] = []
    ingested_events: list[str] = []

    class _FakeChannelRuntime:
        def find_observation_by_dedupe(self, dedupe_key: str, *, principal_id: str | None = None):
            return None

        def list_recent_observations(self, limit: int = 50, principal_id: str | None = None):
            return []

        def ingest_observation(
            self,
            principal_id: str,
            channel: str,
            event_type: str,
            payload: dict[str, object] | None = None,
            *,
            source_id: str = "",
            external_id: str = "",
            dedupe_key: str = "",
            auth_context_json: dict[str, object] | None = None,
            raw_payload_uri: str = "",
        ):
            ingested_events.append(event_type)
            return SimpleNamespace(
                event_type=event_type,
                payload=dict(payload or {}),
                created_at="2026-03-30T08:05:00+00:00",
            )

    class _FakeService:
        def channel_digest_pack(self, *, principal_id: str, digest_key: str, operator_id: str = ""):
            return {"key": digest_key, "items": [{"title": principal_id, "tag": "Memo"}]}

        def issue_channel_digest_delivery(self, **kwargs):
            service_calls.append(str(kwargs["principal_id"]))
            return {
                "delivery_id": f"digest-{kwargs['principal_id']}",
                "digest_key": str(kwargs["digest_key"]),
                "email_delivery_status": "sent",
            }

    container = SimpleNamespace(
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: list(google_bindings)
        ),
        memory_runtime=SimpleNamespace(
            list_delivery_preferences=lambda principal_id, limit=50, status=None: list(preferences.get(principal_id, []))
        ),
        channel_runtime=_FakeChannelRuntime(),
    )

    monkeypatch.setitem(
        sys.modules,
        "app.product.service",
        SimpleNamespace(build_product_service=lambda _container: _FakeService()),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.registration_email",
        SimpleNamespace(email_delivery_enabled=lambda: True),
    )

    now_utc = runner.datetime(2026, 3, 30, 8, 5, tzinfo=runner.timezone.utc)
    summary = runner._run_scheduler_morning_memo_delivery(
        container,
        logging.getLogger("test.runner"),
        now_utc=now_utc,
    )

    assert summary == {
        "ran": True,
        "configured": 2,
        "due": 2,
        "sent": 1,
        "blocked": 0,
        "failed": 0,
        "skipped": 0,
        "budget_deferred": 1,
        "errors": 0,
    }
    assert service_calls == ["principal-memo-a"]
    assert ingested_events.count("scheduled_morning_memo_delivery_sent") == 1
    assert ingested_events.count("scheduled_morning_memo_delivery_deferred") == 1


def test_scheduler_whatsapp_async_recovery_sends_queued_message(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner_module(monkeypatch)
    captured: list[dict[str, object]] = []
    marked_sent: list[tuple[str, str]] = []

    class _FakeChannelRuntime:
        def __init__(self) -> None:
            self.rows = [
                SimpleNamespace(
                    channel="whatsapp",
                    principal_id="principal-whatsapp-1",
                    recipient="+15550101223",
                    content="Ich denke an dich.",
                    metadata={"delivery_mode": "queued", "binding_id": "binding-1"},
                    created_at="2026-01-01T00:00:00Z",
                    delivery_id="delivery-whatsapp-1",
                    attempt_count=0,
                )
            ]

        def list_pending_delivery(self, limit: int = 50, *, principal_id: str | None = None) -> list[SimpleNamespace]:
            return list(self.rows)

        def mark_delivery_sent(self, delivery_id: str, *, principal_id: str, receipt_json: dict[str, object] | None = None):
            marked_sent.append((delivery_id, principal_id))
            return SimpleNamespace(
                status="sent",
                delivery_id=delivery_id,
                principal_id=principal_id,
                receipt_json=dict(receipt_json or {}),
            )

        def mark_delivery_failed(
            self,
            delivery_id: str,
            *,
            principal_id: str,
            error: str,
            next_attempt_at: str | None = None,
            dead_letter: bool = False,
        ):
            raise AssertionError("mark_delivery_failed should not run in happy path")

    class _FakeToolRuntime:
        def get_connector_binding(self, binding_id: str):
            raise AssertionError("get_connector_binding should not be called when send helper is mocked")

    row_count = [0]

    def _fake_send(**kwargs) -> object:
        row_count[0] += 1
        captured.append(dict(kwargs))
        from app.services.whatsapp_delivery import WhatsAppDeliveryReceipt

        return WhatsAppDeliveryReceipt(
            principal_id=kwargs["principal_id"],
            binding_id="binding-1",
            connector_name="whatsapp_export",
            recipient=kwargs["recipient"],
            message_ids=("wamid.123",),
            request_url="https://graph.facebook.com/v20.0/phone/messages",
            binding_status="enabled",
            external_account_ref="acc-ref",
        )

    monkeypatch.setattr(runner, "_whatsapp_queue_retry_backoff_seconds", lambda: 0.0)
    monkeypatch.setattr(runner, "send_whatsapp_text", _fake_send)

    tool_runtime = _FakeToolRuntime()
    container = SimpleNamespace(
        channel_runtime=_FakeChannelRuntime(),
        tool_runtime=tool_runtime,
    )

    summary = runner._run_scheduler_whatsapp_async_recovery(
        container,
        logging.getLogger("test.runner"),
    )

    assert summary["ran"] is True
    assert summary["drained"] == 1
    assert summary["pending"] == 0
    assert summary["skipped"] == 0
    assert summary["errors"] == 0
    assert summary["dead_lettered"] == 0
    assert summary["budget_deferred"] == 0
    assert row_count[0] == 1
    assert marked_sent == [("delivery-whatsapp-1", "principal-whatsapp-1")]
    assert captured[0]["tool_runtime"] is tool_runtime
    assert captured[0]["principal_id"] == "principal-whatsapp-1"
    assert captured[0]["recipient"] == "15550101223"
    assert captured[0]["text"] == "Ich denke an dich."
    assert captured[0]["binding_id"] == "binding-1"
    assert captured[0]["binding"] is None


def test_scheduler_whatsapp_async_recovery_dead_letters_after_retry_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner_module(monkeypatch)
    failures: list[dict[str, object]] = []
    marked_failed: list[tuple[str, bool, str | None]] = []

    class _FakeChannelRuntime:
        def __init__(self) -> None:
            self.rows = [
                SimpleNamespace(
                    channel="whatsapp",
                    principal_id="principal-whatsapp-2",
                    recipient="+15550100000",
                    content="Das ist wichtig.",
                    metadata={"delivery_mode": "queued", "binding_id": "binding-2"},
                    created_at="2026-01-01T00:00:00Z",
                    delivery_id="delivery-whatsapp-2",
                    attempt_count=0,
                )
            ]

        def list_pending_delivery(self, limit: int = 50, *, principal_id: str | None = None) -> list[SimpleNamespace]:
            return list(self.rows)

        def mark_delivery_sent(self, delivery_id: str, *, principal_id: str, receipt_json: dict[str, object] | None = None):
            raise AssertionError("mark_delivery_sent should not run when send fails")

        def mark_delivery_failed(
            self,
            delivery_id: str,
            *,
            principal_id: str,
            error: str,
            next_attempt_at: str | None = None,
            dead_letter: bool = False,
        ):
            marked_failed.append((delivery_id, dead_letter, next_attempt_at))
            return SimpleNamespace(
                status="dead_lettered",
                delivery_id=delivery_id,
                principal_id=principal_id,
                error=error,
            )

    class _FakeToolRuntime:
        def get_connector_binding(self, binding_id: str):
            raise AssertionError("get_connector_binding should not be called when send helper is mocked")

    def _fake_send(**_kwargs):
        failures.append(dict(_kwargs))
        raise RuntimeError("provider_unavailable")

    monkeypatch.setattr(runner, "_whatsapp_queue_max_attempts", lambda: 1)
    monkeypatch.setattr(runner, "_whatsapp_queue_retry_backoff_seconds", lambda: 0.0)
    monkeypatch.setattr(runner, "send_whatsapp_text", _fake_send)

    tool_runtime = _FakeToolRuntime()
    container = SimpleNamespace(
        channel_runtime=_FakeChannelRuntime(),
        tool_runtime=tool_runtime,
    )

    summary = runner._run_scheduler_whatsapp_async_recovery(
        container,
        logging.getLogger("test.runner"),
    )

    assert summary["ran"] is True
    assert summary["drained"] == 0
    assert summary["pending"] == 0
    assert summary["skipped"] == 0
    assert summary["errors"] == 1
    assert summary["dead_lettered"] == 1
    assert summary["budget_deferred"] == 0
    assert failures[0]["tool_runtime"] is tool_runtime
    assert failures[0]["principal_id"] == "principal-whatsapp-2"
    assert failures[0]["recipient"] == "15550100000"
    assert failures[0]["text"] == "Das ist wichtig."
    assert failures[0]["binding_id"] == "binding-2"
    assert failures[0]["binding"] is None
    assert marked_failed == [("delivery-whatsapp-2", True, None)]


def test_scheduler_whatsapp_async_recovery_defers_after_pass_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)
    monkeypatch.setenv("EA_SCHEDULER_WHATSAPP_ASYNC_RECOVERY_MAX_SENDS_PER_PASS", "1")
    captured: list[str] = []
    marked_sent: list[str] = []

    class _FakeChannelRuntime:
        def __init__(self) -> None:
            self.rows = [
                SimpleNamespace(
                    channel="whatsapp",
                    principal_id="principal-whatsapp-a",
                    recipient="+15550100001",
                    content="Message A",
                    metadata={"delivery_mode": "queued", "binding_id": "binding-a"},
                    created_at="2026-01-01T00:00:00Z",
                    delivery_id="delivery-whatsapp-a",
                    attempt_count=0,
                ),
                SimpleNamespace(
                    channel="whatsapp",
                    principal_id="principal-whatsapp-b",
                    recipient="+15550100002",
                    content="Message B",
                    metadata={"delivery_mode": "queued", "binding_id": "binding-b"},
                    created_at="2026-01-01T00:00:00Z",
                    delivery_id="delivery-whatsapp-b",
                    attempt_count=0,
                ),
            ]

        def list_pending_delivery(self, limit: int = 50, *, principal_id: str | None = None) -> list[SimpleNamespace]:
            return list(self.rows)

        def mark_delivery_sent(self, delivery_id: str, *, principal_id: str, receipt_json: dict[str, object] | None = None):
            marked_sent.append(str(delivery_id))
            return SimpleNamespace(status="sent", delivery_id=delivery_id, principal_id=principal_id)

        def mark_delivery_failed(
            self,
            delivery_id: str,
            *,
            principal_id: str,
            error: str,
            next_attempt_at: str | None = None,
            dead_letter: bool = False,
        ):
            raise AssertionError("mark_delivery_failed should not run in budget deferral test")

    class _FakeToolRuntime:
        def get_connector_binding(self, binding_id: str):
            raise AssertionError("get_connector_binding should not be called when send helper is mocked")

    def _fake_send(**kwargs):
        captured.append(str(kwargs["principal_id"]))
        from app.services.whatsapp_delivery import WhatsAppDeliveryReceipt

        return WhatsAppDeliveryReceipt(
            principal_id=kwargs["principal_id"],
            binding_id=str(kwargs["binding_id"]),
            connector_name="whatsapp_export",
            recipient=kwargs["recipient"],
            message_ids=("wamid.1",),
            request_url="https://graph.facebook.com/v20.0/phone/messages",
            binding_status="enabled",
            external_account_ref="acc-ref",
        )

    monkeypatch.setattr(runner, "send_whatsapp_text", _fake_send)

    container = SimpleNamespace(
        channel_runtime=_FakeChannelRuntime(),
        tool_runtime=_FakeToolRuntime(),
    )

    summary = runner._run_scheduler_whatsapp_async_recovery(
        container,
        logging.getLogger("test.runner"),
    )

    assert summary == {
        "ran": True,
        "drained": 1,
        "pending": 0,
        "skipped": 0,
        "errors": 0,
        "dead_lettered": 0,
        "budget_deferred": 1,
    }
    assert captured == ["principal-whatsapp-a"]
    assert marked_sent == ["delivery-whatsapp-a"]


def test_scheduler_async_recovery_idle_helper_treats_skipped_only_pass_as_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)

    assert (
        runner._scheduler_async_recovery_is_idle(
            {
                "drained": 0,
                "pending": 0,
                "skipped": 2,
                "budget_deferred": 0,
                "errors": 0,
                "dead_lettered": 0,
            }
        )
        is True
    )


def test_scheduler_async_recovery_idle_helper_treats_error_or_pending_work_as_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)

    assert runner._scheduler_async_recovery_is_idle({"pending": 1}) is False
    assert runner._scheduler_async_recovery_is_idle({"errors": 1}) is False
    assert runner._scheduler_async_recovery_is_idle({"dead_lettered": 1}) is False


def test_scheduler_property_results_finalize_reconciles_ready_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner_module(monkeypatch)
    observed: list[int] = []

    class _FakeService:
        def reconcile_property_search_results_delivery(self, *, principal_id: str = "", limit: int = 20):
            observed.append(limit)
            return {"attempted": 2, "finalized": 1, "emailed": 1, "pending": 1}

    container = SimpleNamespace()
    monkeypatch.setitem(
        sys.modules,
        "app.product.service",
        SimpleNamespace(build_product_service=lambda _container: _FakeService()),
    )

    summary = runner._run_scheduler_property_results_finalize(container, logging.getLogger("test.runner"))

    assert summary == {
        "ran": True,
        "attempted": 2,
        "finalized": 1,
        "emailed": 1,
        "pending": 1,
        "errors": 0,
    }
    assert observed == [40]


def test_scheduler_host_pressure_snapshot_blocks_when_load_and_memory_cross_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)
    monkeypatch.setattr(runner.os, "getloadavg", lambda: (8.0, 7.0, 6.0))
    monkeypatch.setattr(runner.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(runner, "_scheduler_available_memory_gib", lambda: 1.0)
    monkeypatch.setenv("EA_SCHEDULER_HOST_PRESSURE_GUARD_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_HOST_MAX_LOAD_PER_CORE", "1.25")
    monkeypatch.setenv("EA_SCHEDULER_HOST_MIN_AVAILABLE_MEMORY_GIB", "2.0")

    snapshot = runner._scheduler_host_pressure_snapshot()

    assert snapshot["blocked"] is True
    assert snapshot["reasons"] == ["load", "memory"]
    assert snapshot["load_per_core"] == 2.0
    assert snapshot["available_memory_gib"] == 1.0


def test_execution_worker_pauses_before_queue_work_when_runtime_guard_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner_module(monkeypatch)
    queue_calls: list[str] = []

    container = SimpleNamespace(
        orchestrator=SimpleNamespace(run_next_queue_item=lambda lease_owner: queue_calls.append(lease_owner) or None)
    )
    monkeypatch.setattr(runner, "build_container", lambda: container)
    monkeypatch.setattr(runner.signal, "signal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        runner,
        "_scheduler_runtime_guard_state",
        lambda: {
            "blocked": True,
            "reasons": ["load"],
            "host_pressure": {"load_per_core": 2.0, "available_memory_gib": 1.0},
            "side_effects_enabled": True,
        },
    )

    def _stop_sleep(_seconds: float) -> None:
        raise StopIteration

    monkeypatch.setattr(runner.time, "sleep", _stop_sleep)

    with pytest.raises(StopIteration):
        runner._run_execution_worker("worker")

    assert queue_calls == []
