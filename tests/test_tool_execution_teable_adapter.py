from __future__ import annotations

import pytest

from app.domain.models import ToolDefinition, ToolInvocationRequest
from app.services.tool_execution_common import ToolExecutionError
import app.services.tool_execution_teable_adapter as teable_adapter
from app.services.tool_execution_teable_adapter import (
    TeableToolAdapter,
    _parse_teable_http_error_missing_fields,
)


def _table_sync_request_payload() -> dict[str, object]:
    return {
        "projection_scope": "proactive_ooda",
        "person_id": "person-hash",
        "tables_json": {"proactive_ooda_runs": [{"projection_id": "abc", "legacy_field": "legacy", "present_field": "ok"}]},
        "table_config_json": {
            "proactive_ooda_runs": {
                "table_id": "tbl_proactive_ooda_runs",
                "key_field": "projection_id",
                "field_key_type": "name",
            },
        },
    }


def _table_sync_request(payload: dict[str, object] | None = None) -> ToolInvocationRequest:
    request_payload = dict(payload or _table_sync_request_payload())
    return ToolInvocationRequest(
        session_id="proactive-ooda-table-sync",
        step_id="proactive-ooda-table-sync-step",
        tool_name="provider.teable.table_sync",
        action_kind="table.sync",
        payload_json=request_payload,
        context_json={},
    )


def test_parse_teable_http_error_missing_fields_from_payload() -> None:
    message = 'teable_http_error:404:{"code":"bad_request","missedFields":["delivery_next_action","delivery_next_action_href"]}'

    missing_fields = _parse_teable_http_error_missing_fields(message)

    assert missing_fields == ["delivery_next_action", "delivery_next_action_href"]


def test_parse_teable_http_error_missing_fields_from_truncated_message_text() -> None:
    message = (
        'teable_http_error:404:{"message":"Fields \\"delivery_next_action_href\\", '
        '\\"delivery_next_action_label\\", \\"delivery_next_action_method\\" do not exist in this table",'
        '"status":404,"code":"not_found","data":{"fieldKeyType":"name","missedFields"'
    )

    missing_fields = _parse_teable_http_error_missing_fields(message)

    assert missing_fields == [
        "delivery_next_action_href",
        "delivery_next_action_label",
        "delivery_next_action_method",
    ]


def test_teable_request_json_retries_transient_timeout_with_configured_timeout(monkeypatch) -> None:
    monkeypatch.setenv("TEABLE_REQUEST_TIMEOUT_SECONDS", "123")
    monkeypatch.setenv("TEABLE_REQUEST_RETRY_COUNT", "1")
    monkeypatch.setenv("TEABLE_REQUEST_RETRY_BACKOFF_SECONDS", "0")
    timeouts: list[float] = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"ok":true}'

    def _urlopen(request, timeout=0):
        timeouts.append(timeout)
        if len(timeouts) == 1:
            raise TimeoutError("The read operation timed out")
        return _Response()

    monkeypatch.setattr(teable_adapter.urllib.request, "urlopen", _urlopen)

    payload = TeableToolAdapter()._request_json(
        method="GET",
        url="https://teable.test/api/table/tbl/record",
        api_key="test-key",
    )

    assert payload == {"ok": True}
    assert timeouts == [123.0, 123.0]


def test_teable_request_json_does_not_retry_non_transient_failure(monkeypatch) -> None:
    monkeypatch.setenv("TEABLE_REQUEST_RETRY_COUNT", "3")
    monkeypatch.setenv("TEABLE_REQUEST_RETRY_BACKOFF_SECONDS", "0")
    calls: list[str] = []

    def _urlopen(request, timeout=0):
        calls.append("call")
        raise RuntimeError("bad payload")

    monkeypatch.setattr(teable_adapter.urllib.request, "urlopen", _urlopen)

    with pytest.raises(ToolExecutionError, match="teable_request_failed:bad payload"):
        TeableToolAdapter()._request_json(
            method="GET",
            url="https://teable.test/api/table/tbl/record",
            api_key="test-key",
        )

    assert calls == ["call"]


def test_teable_table_sync_retries_create_with_missing_fields_filtered(monkeypatch) -> None:
    monkeypatch.setenv("TEABLE_API_KEY", "test-key")
    calls: list[dict[str, object]] = []
    call_state = {"attempt": 0}

    def _request_json(
        self,
        *,
        method: str,
        url: str,
        api_key: str,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append({"method": method, "url": url, "body": body or {}})
        if method == "GET":
            return {"records": []}
        call_state["attempt"] += 1
        if call_state["attempt"] == 1:
            raise ToolExecutionError(
                'teable_http_error:404:{"code":"bad_input","missedFields":["legacy_field","nonexistent"]}'
            )
        return {"records": [{"id": "rec-1"}]}

    monkeypatch.setattr(TeableToolAdapter, "_request_json", _request_json)
    request = _table_sync_request()
    definition = ToolDefinition(
        tool_name="provider.teable.table_sync",
        version="v1",
        input_schema_json={},
        output_schema_json={},
        policy_json={"builtin": True, "action_kind": "table.sync"},
        allowed_channels=(),
        approval_default="none",
        enabled=True,
        updated_at="2026-06-28T00:00:00Z",
    )
    result = TeableToolAdapter().execute_table_sync(request, definition)

    assert result.output_json["synced_tables"] == ["proactive_ooda_runs"]
    assert result.output_json["created_count"] == 1
    post_calls = [item["body"] for item in calls if item["method"] == "POST"]
    assert len(post_calls) == 2
    assert post_calls[0]["records"][0]["fields"]["legacy_field"] == "legacy"
    assert post_calls[1]["records"][0]["fields"] == {"projection_id": "abc", "present_field": "ok"}


def test_teable_table_sync_retries_update_with_missing_fields_filtered(monkeypatch) -> None:
    monkeypatch.setenv("TEABLE_API_KEY", "test-key")
    calls: list[dict[str, object]] = []
    call_state = {"attempt": 0}

    def _request_json(
        self,
        *,
        method: str,
        url: str,
        api_key: str,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append({"method": method, "url": url, "body": body or {}})
        if method == "GET":
            return {"records": [{"id": "rec-1", "fields": {"projection_id": "abc"}}]}
        call_state["attempt"] += 1
        if call_state["attempt"] == 1:
            raise ToolExecutionError(
                'teable_http_error:404:{"code":"bad_input","missedFields":["legacy_field","delivery_next_action"]}'
            )
        return {"id": "rec-1"}

    payload = _table_sync_request_payload()
    payload["projection_scope"] = "proactive_ooda_update"
    payload["tables_json"]["proactive_ooda_runs"][0]["legacy_field"] = "legacy"
    request = _table_sync_request(payload=payload)

    monkeypatch.setattr(TeableToolAdapter, "_request_json", _request_json)
    definition = ToolDefinition(
        tool_name="provider.teable.table_sync",
        version="v1",
        input_schema_json={},
        output_schema_json={},
        policy_json={"builtin": True, "action_kind": "table.sync"},
        allowed_channels=(),
        approval_default="none",
        enabled=True,
        updated_at="2026-06-28T00:00:00Z",
    )
    result = TeableToolAdapter().execute_table_sync(request, definition)

    assert result.output_json["synced_tables"] == ["proactive_ooda_runs"]
    assert result.output_json["updated_count"] == 1
    patch_calls = [item["body"] for item in calls if item["method"] == "PATCH"]
    assert len(patch_calls) == 2
    assert "legacy_field" in patch_calls[0]["record"]["fields"]
    assert "legacy_field" not in patch_calls[1]["record"]["fields"]
