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

    assert summary == {"ran": True, "attempted": 1, "synced": 1, "errors": 0}
    assert calls == ["principal-google-1|scheduler|5|5"]


def test_scheduler_morning_memo_delivery_sends_once_when_due(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner_module(monkeypatch)

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
        "errors": 0,
    }
    assert service_calls == []
