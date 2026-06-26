from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from uuid import uuid4

from app.domain.models import ToolDefinition, ToolInvocationRequest
from app.services.proactive_ooda_service import OodaInk, ProactiveOodaDigest, ProactiveOodaRunReceipt
from app.services.proactive_ooda_stage_packets import build_stage_packets
from app.services.tool_execution_common import ToolExecutionError
from app.services.tool_execution_teable_adapter import TeableToolAdapter


PROACTIVE_OODA_TEABLE_TABLE_NAMES = (
    "proactive_ooda_runs",
    "proactive_ooda_items",
    "proactive_ooda_safe_work",
)
PROACTIVE_OODA_TEABLE_SYNC_VERSION = "proactive_ooda_teable_projection_v1"


def teable_sync_enabled() -> bool:
    raw = str(os.environ.get("EA_PROACTIVE_OODA_TEABLE_SYNC_ENABLED") or "0").strip().lower()
    return raw not in {"", "0", "false", "no", "off", "disabled"}


def build_proactive_ooda_teable_projection_records(
    *,
    digest: ProactiveOodaDigest,
    receipt: ProactiveOodaRunReceipt,
    safe_work_results: Iterable[Mapping[str, Any]] = (),
) -> dict[str, list[dict[str, object]]]:
    run_projection_id = _run_projection_id(receipt)
    safe_work_rows = [dict(item) for item in safe_work_results if isinstance(item, Mapping)]
    item_rows: list[dict[str, object]] = []
    safe_work_table_rows: list[dict[str, object]] = []
    for index, item in enumerate(digest.items, start=1):
        safe_work_result = safe_work_rows[index - 1] if index - 1 < len(safe_work_rows) else {}
        item_projection_id = _item_projection_id(run_projection_id=run_projection_id, item=item, index=index)
        item_rows.append(
            _item_projection_row(
                digest=digest,
                receipt=receipt,
                item=item,
                item_index=index,
                run_projection_id=run_projection_id,
                item_projection_id=item_projection_id,
                safe_work_result=safe_work_result,
            )
        )
        if safe_work_result:
            safe_work_table_rows.append(
                _safe_work_projection_row(
                    digest=digest,
                    receipt=receipt,
                    run_projection_id=run_projection_id,
                    item_projection_id=item_projection_id,
                    safe_work_result=safe_work_result,
                    item_index=index,
                )
            )
    return {
        "proactive_ooda_runs": [_run_projection_row(digest=digest, receipt=receipt, run_projection_id=run_projection_id)],
        "proactive_ooda_items": item_rows,
        "proactive_ooda_safe_work": safe_work_table_rows,
    }


def build_proactive_ooda_teable_projection_summary(
    records: Mapping[str, Iterable[Mapping[str, Any]]],
) -> dict[str, object]:
    normalized = {
        str(table_name or "").strip(): [dict(row) for row in rows if isinstance(row, Mapping)]
        for table_name, rows in dict(records or {}).items()
        if str(table_name or "").strip()
    }
    return {
        "sync_version": PROACTIVE_OODA_TEABLE_SYNC_VERSION,
        "table_count": len(normalized),
        "record_count": sum(len(rows) for rows in normalized.values()),
        "tables": {
            table_name: {
                "record_count": len(rows),
                "sample_projection_ids": [str(row.get("projection_id") or "") for row in rows[:3]],
            }
            for table_name, rows in normalized.items()
        },
    }


def sync_proactive_ooda_to_teable(
    *,
    principal_id: str,
    digest: ProactiveOodaDigest,
    receipt: ProactiveOodaRunReceipt,
    safe_work_results: Iterable[Mapping[str, Any]] = (),
) -> dict[str, object]:
    records = build_proactive_ooda_teable_projection_records(
        digest=digest,
        receipt=receipt,
        safe_work_results=safe_work_results,
    )
    non_empty_tables = {
        table_name: [dict(row) for row in rows if isinstance(row, Mapping)]
        for table_name, rows in records.items()
        if rows
    }
    summary = build_proactive_ooda_teable_projection_summary(non_empty_tables)
    if not non_empty_tables:
        return {
            "status": "noop",
            "sync_attempted": False,
            "blocked_reason": "",
            "missing_tables": [],
            "projection_summary": summary,
        }

    if not str(os.environ.get("TEABLE_API_KEY") or "").strip():
        return {
            "status": "blocked",
            "sync_attempted": False,
            "blocked_reason": "teable_missing_api_key",
            "missing_tables": list(non_empty_tables),
            "projection_summary": summary,
        }

    configured_tables = _configured_teable_tables()
    syncable_tables = {
        table_name: rows
        for table_name, rows in non_empty_tables.items()
        if _table_has_mapping(configured_tables.get(table_name))
    }
    missing_tables = sorted(table_name for table_name in non_empty_tables if table_name not in syncable_tables)
    if not syncable_tables:
        return {
            "status": "blocked",
            "sync_attempted": False,
            "blocked_reason": "proactive_ooda_teable_table_sync_config_missing",
            "missing_tables": missing_tables,
            "projection_summary": summary,
            "records_preview": {table_name: rows[:2] for table_name, rows in non_empty_tables.items()},
        }

    adapter = TeableToolAdapter()
    definition = ToolDefinition(
        tool_name="provider.teable.table_sync",
        version="v1",
        input_schema_json={},
        output_schema_json={},
        policy_json={"builtin": True, "action_kind": "table.sync"},
        allowed_channels=(),
        approval_default="none",
        enabled=True,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    request = ToolInvocationRequest(
        session_id=f"proactive-ooda-teable-sync:{uuid4()}",
        step_id=f"proactive-ooda-teable-sync-step:{uuid4()}",
        tool_name=definition.tool_name,
        action_kind="table.sync",
        payload_json={
            "projection_scope": "proactive_ooda",
            "person_id": str(receipt.principal_id_hash or principal_id or "").strip(),
            "tables_json": syncable_tables,
            "table_config_json": {table_name: configured_tables[table_name] for table_name in syncable_tables},
        },
        context_json={"principal_id": principal_id},
    )
    try:
        result = adapter.execute_table_sync(request, definition)
    except ToolExecutionError as exc:
        return {
            "status": "failed",
            "sync_attempted": True,
            "blocked_reason": str(exc),
            "missing_tables": missing_tables,
            "projection_summary": summary,
            "records_preview": {table_name: rows[:2] for table_name, rows in non_empty_tables.items()},
        }
    status = "partial" if missing_tables else "synced"
    return {
        "status": status,
        "sync_attempted": True,
        "blocked_reason": "",
        "missing_tables": missing_tables,
        "projection_summary": summary,
        "tool_execution": {
            "tool_name": result.tool_name,
            "action_kind": result.action_kind,
            "target_ref": result.target_ref,
            "output_json": dict(result.output_json or {}),
            "receipt_json": dict(result.receipt_json or {}),
        },
    }


def _run_projection_row(
    *,
    digest: ProactiveOodaDigest,
    receipt: ProactiveOodaRunReceipt,
    run_projection_id: str,
) -> dict[str, object]:
    stage_kinds = [
        _normalized_stage_kind(item.stage_kind)
        for item in digest.items
        if _normalized_stage_kind(item.stage_kind)
    ]
    return {
        "projection_id": run_projection_id,
        "sync_version": PROACTIVE_OODA_TEABLE_SYNC_VERSION,
        "generated_at": receipt.generated_at,
        "principal_id_hash": receipt.principal_id_hash,
        "notification_status": receipt.notification_status,
        "dry_run": bool(receipt.dry_run),
        "item_count": int(receipt.item_count or 0),
        "notified_ref_count": len(receipt.notified_ref_hashes),
        "delivery_channel": _compact_text(receipt.delivery_channel, 80),
        "delivery_transport": _compact_text(receipt.delivery_transport, 80),
        "delivery_selected_by": _compact_text(receipt.delivery_selected_by, 80),
        "delivery_recipient_hash": _compact_text(receipt.delivery_recipient_hash, 80),
        "delivery_message_count": len(receipt.delivery_message_ids),
        "delivery_message_ids": list(receipt.delivery_message_ids),
        "delivery_outbox_id_hash": _compact_text(receipt.delivery_outbox_id_hash, 80),
        "telegram_message_count": len(receipt.telegram_message_ids),
        "telegram_message_ids": list(receipt.telegram_message_ids),
        "stage_packet_count": len(receipt.stage_packet_ref_hashes),
        "stage_packet_error_count": int(receipt.stage_packet_error_count or 0),
        "safe_work_result_count": len(receipt.safe_work_result_ref_hashes),
        "safe_work_result_error_count": int(receipt.safe_work_result_error_count or 0),
        "error_code": _compact_text(receipt.error_code, 160),
        "deferred_reason": _compact_text(receipt.error_code, 160) if receipt.notification_status == "deferred" else "",
        "high_priority_count": sum(1 for item in digest.items if item.priority == "high"),
        "approval_required_count": sum(1 for item in digest.items if item.approval_required),
        "staged_item_count": sum(1 for item in digest.items if _item_has_stage(item)),
        "stage_kinds": sorted(dict.fromkeys(stage_kinds)),
        "privacy_raw_principal_id_stored": False,
        "privacy_raw_signal_ref_stored": False,
    }


def _item_projection_row(
    *,
    digest: ProactiveOodaDigest,
    receipt: ProactiveOodaRunReceipt,
    item: OodaInk,
    item_index: int,
    run_projection_id: str,
    item_projection_id: str,
    safe_work_result: Mapping[str, Any],
) -> dict[str, object]:
    recommended = dict(safe_work_result.get("recommended_option_or_draft") or {}) if safe_work_result else {}
    recommended_value = dict(recommended.get("value") or {}) if isinstance(recommended.get("value"), Mapping) else {}
    shortlist = [dict(row) for row in safe_work_result.get("shortlist") or [] if isinstance(row, Mapping)] if safe_work_result else []
    comparison_rows = [dict(row) for row in safe_work_result.get("comparison_table") or [] if isinstance(row, Mapping)] if safe_work_result else []
    recommended_comparison = next((row for row in comparison_rows if row.get("recommended") is True), {})
    return {
        "projection_id": item_projection_id,
        "run_projection_id": run_projection_id,
        "sync_version": PROACTIVE_OODA_TEABLE_SYNC_VERSION,
        "generated_at": receipt.generated_at,
        "principal_id_hash": receipt.principal_id_hash,
        "item_index": item_index,
        "notification_status": receipt.notification_status,
        "signal_ref_hash": _hash_value(item.signal_ref),
        "priority": _compact_text(item.priority, 24),
        "approval_required": bool(item.approval_required),
        "observe": _compact_text(item.observe, 240),
        "orient": _compact_text(item.orient, 500),
        "decide": _compact_text(item.decide, 500),
        "act": _compact_text(item.act, 500),
        "ignored_consequence": _compact_text(item.ignored_consequence, 500),
        "action_plan": list(item.action_plan),
        "action_plan_count": len(item.action_plan),
        "stage_kind": _normalized_stage_kind(item.stage_kind),
        "stage_summary": _compact_text(item.stage_summary, 500),
        "stage_artifacts": list(item.stage_artifacts),
        "stage_artifact_count": len(item.stage_artifacts),
        "approval_gate": _compact_text(item.approval_gate, 300),
        "external_action_policy": _compact_text(item.external_action_policy, 300),
        "evidence_count": len(item.evidence),
        "safe_work_status": _compact_text(safe_work_result.get("status"), 80),
        "safe_work_work_type": _compact_text(safe_work_result.get("work_type"), 80),
        "safe_work_summary": _compact_text(safe_work_result.get("summary"), 500),
        "staged_action_url": _compact_text(safe_work_result.get("staged_action_url"), 500),
        "recommended_kind": _compact_text(recommended.get("kind"), 80),
        "recommended_label": _compact_text(
            recommended_value.get("label") or recommended_value.get("title") or recommended.get("value"),
            240,
        ),
        "recommended_url": _compact_text(
            recommended_value.get("url") or recommended_value.get("link") or recommended_value.get("href"),
            500,
        ),
        "shortlist_count": len(shortlist),
        "shortlist": [_shortlist_projection_item(candidate) for candidate in shortlist[:5]],
        "comparison_row_count": len(comparison_rows),
        "recommendation_reasons": list(recommended_comparison.get("recommendation_reasons") or []),
        "constraint_violations": list(recommended_comparison.get("constraint_violations") or []),
        "approval_prompt": _compact_text(safe_work_result.get("approval_prompt"), 500),
        "privacy_raw_principal_id_stored": False,
        "privacy_raw_signal_ref_stored": False,
    }


def _safe_work_projection_row(
    *,
    digest: ProactiveOodaDigest,
    receipt: ProactiveOodaRunReceipt,
    run_projection_id: str,
    item_projection_id: str,
    safe_work_result: Mapping[str, Any],
    item_index: int,
) -> dict[str, object]:
    recommended = dict(safe_work_result.get("recommended_option_or_draft") or {})
    recommended_value = dict(recommended.get("value") or {}) if isinstance(recommended.get("value"), Mapping) else {}
    shortlist = [dict(row) for row in safe_work_result.get("shortlist") or [] if isinstance(row, Mapping)]
    comparison_rows = [dict(row) for row in safe_work_result.get("comparison_table") or [] if isinstance(row, Mapping)]
    receipt_details = dict(safe_work_result.get("execution_receipt") or {})
    risks = [str(item).strip() for item in safe_work_result.get("risks_or_tradeoffs") or [] if str(item).strip()]
    projection_id = _safe_work_projection_id(safe_work_result=safe_work_result, item_projection_id=item_projection_id)
    return {
        "projection_id": projection_id,
        "run_projection_id": run_projection_id,
        "item_projection_id": item_projection_id,
        "sync_version": PROACTIVE_OODA_TEABLE_SYNC_VERSION,
        "generated_at": _compact_text(safe_work_result.get("generated_at") or receipt.generated_at, 64),
        "principal_id_hash": receipt.principal_id_hash,
        "item_index": item_index,
        "status": _compact_text(safe_work_result.get("status"), 80),
        "work_type": _compact_text(safe_work_result.get("work_type"), 80),
        "summary": _compact_text(safe_work_result.get("summary"), 500),
        "recommended_kind": _compact_text(recommended.get("kind"), 80),
        "recommended_label": _compact_text(
            recommended_value.get("label") or recommended_value.get("title") or recommended.get("value"),
            240,
        ),
        "recommended_url": _compact_text(
            recommended_value.get("url") or recommended_value.get("link") or recommended_value.get("href"),
            500,
        ),
        "staged_action_url": _compact_text(safe_work_result.get("staged_action_url"), 500),
        "shortlist_count": len(shortlist),
        "shortlist": [_shortlist_projection_item(candidate) for candidate in shortlist[:5]],
        "comparison_row_count": len(comparison_rows),
        "comparison_table": comparison_rows[:5],
        "risk_count": len(risks),
        "risks_or_tradeoffs": risks[:5],
        "approval_prompt": _compact_text(safe_work_result.get("approval_prompt"), 500),
        "network_fetch_count": int(receipt_details.get("network_fetch_count") or 0),
        "network_fetch_success_count": int(receipt_details.get("network_fetch_success_count") or 0),
        "privacy_raw_principal_id_stored": False,
        "privacy_raw_signal_ref_stored": False,
        "privacy_private_links_may_be_present": bool(dict(safe_work_result.get("privacy") or {}).get("private_links_may_be_present")),
    }


def _configured_teable_tables() -> dict[str, dict[str, object]]:
    raw = str(os.environ.get("TEABLE_TABLE_SYNC_CONFIG_JSON") or "").strip()
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {
        str(table_name or "").strip(): dict(config or {})
        for table_name, config in loaded.items()
        if str(table_name or "").strip() and isinstance(config, dict)
    }


def _table_has_mapping(config: Mapping[str, Any] | None) -> bool:
    if not isinstance(config, Mapping):
        return False
    return bool(str(config.get("table_id") or "").strip())


def _run_projection_id(receipt: ProactiveOodaRunReceipt) -> str:
    return f"proactive_ooda_run:{_hash_value(json.dumps(asdict(receipt), sort_keys=True))[:24]}"


def _item_projection_id(*, run_projection_id: str, item: OodaInk, index: int) -> str:
    item_key = _hash_value(f"{item.signal_ref}|{index}")[:16]
    return f"{run_projection_id}:item:{index}:{item_key}"


def _safe_work_projection_id(*, safe_work_result: Mapping[str, Any], item_projection_id: str) -> str:
    result_id = str(safe_work_result.get("result_id") or "").strip()
    if result_id:
        return f"proactive_ooda_safe_work:{result_id}"
    return f"{item_projection_id}:safe_work"


def _item_has_stage(item: OodaInk) -> bool:
    return bool(item.stage_kind or item.stage_summary or item.stage_artifacts)


def _normalized_stage_kind(value: str) -> str:
    return _compact_text(str(value or "").strip().lower().replace("-", "_").replace(" ", "_"), 80)


def _shortlist_projection_item(candidate: Mapping[str, Any]) -> dict[str, object]:
    return {
        "label": _compact_text(candidate.get("label") or candidate.get("title"), 160),
        "url": _compact_text(candidate.get("url") or candidate.get("link") or candidate.get("href"), 500),
        "reachable": candidate.get("reachable") if isinstance(candidate.get("reachable"), bool) else None,
        "page_title": _compact_text(candidate.get("page_title"), 160),
        "assistant_rank": int(candidate.get("assistant_rank") or 0) if str(candidate.get("assistant_rank") or "").strip() else 0,
    }


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    return text if len(text) <= limit else f"{text[: max(limit - 1, 1)].rstrip()}..."


def _hash_value(value: str) -> str:
    import hashlib

    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
