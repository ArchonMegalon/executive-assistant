from __future__ import annotations

import json
import os
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import uuid

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_common import ToolExecutionError


def _jsonable_field_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return str(value)


class TeableToolAdapter:
    def _api_key(self) -> str:
        return str(os.environ.get("TEABLE_API_KEY") or "").strip()

    def _base_url(self, payload: dict[str, Any]) -> str:
        value = str(payload.get("base_url") or os.environ.get("TEABLE_BASE_URL") or "https://app.teable.ai").strip()
        return value.rstrip("/")

    def _table_config(self, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        raw = payload.get("table_config_json")
        if not isinstance(raw, dict) or not raw:
            env_raw = str(os.environ.get("TEABLE_TABLE_SYNC_CONFIG_JSON") or "").strip()
            if not env_raw:
                raise ToolExecutionError("teable_table_sync_config_missing")
            try:
                raw = json.loads(env_raw)
            except Exception as exc:
                raise ToolExecutionError("teable_table_sync_config_invalid") from exc
        config = {
            str(table_name or "").strip(): dict(table_value or {})
            for table_name, table_value in dict(raw or {}).items()
            if str(table_name or "").strip()
        }
        if not config:
            raise ToolExecutionError("teable_table_sync_config_invalid")
        return config

    def _request_json(
        self,
        *,
        method: str,
        url: str,
        api_key: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None if body is None else json.dumps(body, ensure_ascii=True).encode("utf-8")
        origin = "https://app.teable.ai"
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Content-Type": "application/json",
                "Origin": origin,
                "Referer": f"{origin}/",
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8")[:500]
            except Exception:
                detail = str(exc)[:500]
            raise ToolExecutionError(f"teable_http_error:{exc.code}:{detail}") from exc
        except Exception as exc:
            raise ToolExecutionError(f"teable_request_failed:{str(exc)[:400]}") from exc
        if not payload.strip():
            return {}
        try:
            loaded = json.loads(payload)
        except Exception as exc:
            raise ToolExecutionError("teable_response_invalid_json") from exc
        return dict(loaded or {})

    def _list_existing_records(
        self,
        *,
        base_url: str,
        api_key: str,
        table_id: str,
        key_field: str,
        field_key_type: str,
    ) -> dict[str, str]:
        found: dict[str, str] = {}
        skip = 0
        take = 1000
        while True:
            query = urllib.parse.urlencode(
                {
                    "fieldKeyType": field_key_type,
                    "cellFormat": "json",
                    "take": take,
                    "skip": skip,
                    "projection": key_field,
                },
                doseq=True,
            )
            payload = self._request_json(
                method="GET",
                url=f"{base_url}/api/table/{urllib.parse.quote(table_id)}/record?{query}",
                api_key=api_key,
            )
            records = [dict(item) for item in payload.get("records") or [] if isinstance(item, dict)]
            for record in records:
                fields = dict(record.get("fields") or {})
                key_value = str(fields.get(key_field) or "").strip()
                record_id = str(record.get("id") or "").strip()
                if key_value and record_id:
                    found[key_value] = record_id
            if len(records) < take:
                break
            skip += take
        return found

    def _create_records(
        self,
        *,
        base_url: str,
        api_key: str,
        table_id: str,
        field_key_type: str,
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._request_json(
            method="POST",
            url=f"{base_url}/api/table/{urllib.parse.quote(table_id)}/record",
            api_key=api_key,
            body={
                "fieldKeyType": field_key_type,
                "typecast": True,
                "records": records,
            },
        )

    def _update_record(
        self,
        *,
        base_url: str,
        api_key: str,
        table_id: str,
        record_id: str,
        field_key_type: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request_json(
            method="PATCH",
            url=f"{base_url}/api/table/{urllib.parse.quote(table_id)}/record/{urllib.parse.quote(record_id)}",
            api_key=api_key,
            body={
                "fieldKeyType": field_key_type,
                "typecast": True,
                "record": {"fields": fields},
            },
        )

    def execute_table_sync(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        api_key = self._api_key()
        if not api_key:
            raise ToolExecutionError("teable_missing_api_key")
        table_config = self._table_config(payload)
        tables_json = {
            str(table_name or "").strip(): [dict(row) for row in rows if isinstance(row, dict)]
            for table_name, rows in dict(payload.get("tables_json") or {}).items()
            if str(table_name or "").strip()
        }
        if not tables_json:
            raise ToolExecutionError("teable_tables_required")
        base_url = self._base_url(payload)
        table_results: list[dict[str, Any]] = []
        total_created = 0
        total_updated = 0
        for table_name, rows in tables_json.items():
            config = dict(table_config.get(table_name) or {})
            table_id = str(config.get("table_id") or "").strip()
            key_field = str(config.get("key_field") or "projection_id").strip() or "projection_id"
            field_key_type = str(config.get("field_key_type") or "name").strip() or "name"
            if not table_id:
                raise ToolExecutionError(f"teable_table_mapping_missing:{table_name}")
            existing = self._list_existing_records(
                base_url=base_url,
                api_key=api_key,
                table_id=table_id,
                key_field=key_field,
                field_key_type=field_key_type,
            )
            pending_creates: list[dict[str, Any]] = []
            created = 0
            updated = 0
            for row in rows:
                normalized_fields = {
                    str(field_name or "").strip(): _jsonable_field_value(field_value)
                    for field_name, field_value in dict(row or {}).items()
                    if str(field_name or "").strip()
                }
                projection_id = str(normalized_fields.get(key_field) or "").strip()
                if not projection_id:
                    raise ToolExecutionError(f"teable_projection_key_missing:{table_name}:{key_field}")
                existing_record_id = str(existing.get(projection_id) or "").strip()
                if existing_record_id:
                    self._update_record(
                        base_url=base_url,
                        api_key=api_key,
                        table_id=table_id,
                        record_id=existing_record_id,
                        field_key_type=field_key_type,
                        fields=normalized_fields,
                    )
                    updated += 1
                    continue
                pending_creates.append({"fields": normalized_fields})
            if pending_creates:
                for start in range(0, len(pending_creates), 50):
                    chunk = pending_creates[start : start + 50]
                    response = self._create_records(
                        base_url=base_url,
                        api_key=api_key,
                        table_id=table_id,
                        field_key_type=field_key_type,
                        records=chunk,
                    )
                    created += len(response.get("records") or chunk)
            total_created += created
            total_updated += updated
            table_results.append(
                {
                    "table_name": table_name,
                    "table_id": table_id,
                    "record_count": len(rows),
                    "created_count": created,
                    "updated_count": updated,
                    "key_field": key_field,
                    "field_key_type": field_key_type,
                }
            )
        projection_scope = str(payload.get("projection_scope") or "projection").strip() or "projection"
        person_id = str(payload.get("person_id") or "").strip()
        target_suffix = f"{projection_scope}:{person_id}" if person_id else projection_scope
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=str(request.action_kind or "table.sync").strip() or "table.sync",
            target_ref=f"teable-sync:{target_suffix}",
            output_json={
                "projection_scope": projection_scope,
                "person_id": person_id,
                "base_url": base_url,
                "synced_tables": [str(item["table_name"]) for item in table_results],
                "table_results_json": table_results,
                "created_count": total_created,
                "updated_count": total_updated,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "provider_key": "teable",
                "table_count": len(table_results),
                "created_count": total_created,
                "updated_count": total_updated,
                "tool_version": definition.version,
                "sync_id": str(uuid.uuid4()),
            },
        )
