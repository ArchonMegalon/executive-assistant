from __future__ import annotations

import json
import os
from dataclasses import asdict, fields
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from uuid import uuid4

from app.domain.models import ToolDefinition, ToolInvocationRequest
from app.services.proactive_ooda_operator_actions import proactive_next_action_surface
from app.services.proactive_ooda_service import OodaInk, ProactiveOodaDigest, ProactiveOodaRunReceipt
from app.services.proactive_ooda_stage_packets import build_stage_packets
from app.services.tool_execution_common import ToolExecutionError
from app.services.tool_execution_teable_adapter import TeableToolAdapter


PROACTIVE_OODA_TEABLE_TABLE_NAMES = (
    "proactive_ooda_runs",
    "proactive_ooda_items",
    "proactive_ooda_safe_work",
    "proactive_ooda_approval_surfaces",
    "proactive_ooda_approval_outcomes",
)
PROACTIVE_OODA_TEABLE_SYNC_VERSION = "proactive_ooda_teable_projection_v1"


def _next_action_surface_fields(action: Any, *, prefix: str) -> dict[str, object]:
    surface = proactive_next_action_surface(str(action or "").strip())
    return {
        f"{prefix}_href": _compact_text(surface.get("href"), 500),
        f"{prefix}_label": _compact_text(surface.get("label"), 120),
        f"{prefix}_method": _compact_text(surface.get("method"), 24),
    }


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
    approval_surface_rows: list[dict[str, object]] = []
    suppressed = _suppressed_safe_work_projection_summary(digest=digest, safe_work_rows=safe_work_rows)
    for index, item in enumerate(digest.items, start=1):
        safe_work_result = safe_work_rows[index - 1] if index - 1 < len(safe_work_rows) else {}
        if not _safe_work_result_is_projectable(safe_work_result):
            continue
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
            approval_surface = _receipt_approval_surface(receipt)
            if approval_surface and not approval_surface_rows:
                approval_surface_rows.append(
                    _approval_surface_projection_row(
                        receipt=receipt,
                        run_projection_id=run_projection_id,
                        safe_work_projection_id=_safe_work_projection_id(
                            safe_work_result=safe_work_result,
                            item_projection_id=item_projection_id,
                        ),
                        approval_surface=approval_surface,
                    )
                )
    rows = {
        "proactive_ooda_runs": [
            _run_projection_row(
                digest=digest,
                receipt=receipt,
                run_projection_id=run_projection_id,
                suppressed_projection=suppressed,
            )
        ],
        "proactive_ooda_items": item_rows,
        "proactive_ooda_safe_work": safe_work_table_rows,
    }
    if approval_surface_rows:
        rows["proactive_ooda_approval_surfaces"] = approval_surface_rows
    return rows


def build_proactive_ooda_teable_projection_summary(
    records: Mapping[str, Iterable[Mapping[str, Any]]],
) -> dict[str, object]:
    normalized = {
        str(table_name or "").strip(): [dict(row) for row in rows if isinstance(row, Mapping)]
        for table_name, rows in dict(records or {}).items()
        if str(table_name or "").strip()
    }
    run_rows = [dict(row) for row in normalized.get("proactive_ooda_runs", [])]
    suppressed_reasons: list[str] = []
    suppressed_issue_codes: list[str] = []
    for row in run_rows:
        suppressed_reasons.extend(
            str(item or "").strip()
            for item in list(row.get("suppressed_projection_reasons") or [])
            if str(item or "").strip()
        )
        suppressed_issue_codes.extend(
            str(item or "").strip()
            for item in list(row.get("suppressed_safe_work_issue_codes") or [])
            if str(item or "").strip()
        )
    return {
        "sync_version": PROACTIVE_OODA_TEABLE_SYNC_VERSION,
        "table_count": len(normalized),
        "record_count": sum(len(rows) for rows in normalized.values()),
        "suppressed_item_count": sum(int(row.get("suppressed_item_count") or 0) for row in run_rows),
        "suppressed_safe_work_review_count": sum(
            int(row.get("suppressed_safe_work_review_count") or 0) for row in run_rows
        ),
        "suppressed_projection_reasons": sorted(dict.fromkeys(suppressed_reasons))[:8],
        "suppressed_safe_work_issue_codes": sorted(dict.fromkeys(suppressed_issue_codes))[:12],
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


def build_proactive_ooda_approval_outcome_projection_records(
    *,
    receipt: ProactiveOodaRunReceipt | Mapping[str, Any],
    safe_work_result: Mapping[str, Any] | None,
    approval_outcome: Mapping[str, Any] | None,
) -> dict[str, list[dict[str, object]]]:
    outcome = dict(approval_outcome or {})
    if not outcome:
        return {}
    run_projection_id = _run_projection_id(receipt)
    safe_work = dict(safe_work_result or {})
    approval_surface = _receipt_approval_surface(receipt)
    safe_work_projection_id = _safe_work_projection_id(
        safe_work_result=safe_work,
        item_projection_id=f"{run_projection_id}:approval_outcome",
    ) if safe_work else ""
    principal_id_hash = _receipt_value(receipt, "principal_id_hash")
    approval_surface_message_ids = [
        str(item or "").strip()
        for item in list(approval_surface.get("message_ids") or [])
        if str(item or "").strip()
    ]
    summary_fields = {
        "approval_outcome_recorded": bool(outcome.get("approval_outcome_recorded")),
        "approval_outcome_accepted": bool(outcome.get("accepted")),
        "approval_outcome_status": _compact_text(outcome.get("status"), 80),
        "approval_outcome_source_kind": _compact_text(outcome.get("source_kind"), 80),
        "approval_outcome_recorded_at": _compact_text(outcome.get("recorded_at"), 64),
        "approval_outcome_actor_sha256": _compact_text(outcome.get("actor_sha256"), 80),
        "approval_outcome_evidence_sha256": _compact_text(outcome.get("evidence_sha256"), 80),
    }
    run_summary_fields = {
        **summary_fields,
        "delivery_next_action": _compact_text(_receipt_value(receipt, "delivery_next_action"), 120),
        **_next_action_surface_fields(_receipt_value(receipt, "delivery_next_action"), prefix="delivery_next_action"),
        "approval_surface_present": bool(approval_surface.get("present")),
        "approval_surface_channel": _compact_text(approval_surface.get("channel"), 80),
        "approval_surface_status": _compact_text(outcome.get("outcome") or approval_surface.get("status"), 80),
        "approval_surface_expires_at": _compact_text(approval_surface.get("expires_at"), 64),
        "approval_surface_callback_token_sha256": _compact_text(approval_surface.get("callback_token_sha256"), 80),
        "approval_surface_message_count": len(approval_surface_message_ids),
        "approval_surface_message_ids": approval_surface_message_ids,
    }
    rows: dict[str, list[dict[str, object]]] = {
        "proactive_ooda_runs": [{"projection_id": run_projection_id, **run_summary_fields}],
        "proactive_ooda_approval_outcomes": [
            {
                "projection_id": _approval_outcome_projection_id(outcome),
                "run_projection_id": run_projection_id,
                "safe_work_projection_id": safe_work_projection_id,
                "sync_version": PROACTIVE_OODA_TEABLE_SYNC_VERSION,
                "principal_id_hash": principal_id_hash,
                "outcome": _compact_text(outcome.get("outcome"), 80),
                "accepted": bool(outcome.get("accepted")),
                "status": _compact_text(outcome.get("status"), 80),
                "source_kind": _compact_text(outcome.get("source_kind"), 80),
                "recorded_at": _compact_text(outcome.get("recorded_at"), 64),
                "evidence_sha256": _compact_text(outcome.get("evidence_sha256"), 80),
                "actor_sha256": _compact_text(outcome.get("actor_sha256"), 80),
                "packet_ref_sha256": _compact_text(outcome.get("packet_ref_sha256"), 80),
                "staged_artifact_sha256": _compact_text(outcome.get("staged_artifact_sha256"), 80),
                "privacy_raw_principal_id_stored": False,
                "privacy_raw_actor_exposed": False,
                "privacy_raw_evidence_exposed": False,
                "privacy_raw_packet_ref_exposed": False,
                "privacy_raw_staged_artifact_exposed": False,
            }
        ],
    }
    if safe_work_projection_id:
        rows["proactive_ooda_safe_work"] = [{"projection_id": safe_work_projection_id, **summary_fields}]
    if approval_surface:
        rows["proactive_ooda_approval_surfaces"] = [
            _approval_surface_projection_row(
                receipt=receipt,
                run_projection_id=run_projection_id,
                safe_work_projection_id=safe_work_projection_id,
                approval_surface=approval_surface,
                approval_outcome=outcome,
            )
        ]
    return rows


def sync_proactive_ooda_approval_outcome_to_teable(
    *,
    receipt: ProactiveOodaRunReceipt | Mapping[str, Any],
    safe_work_result: Mapping[str, Any] | None,
    approval_outcome: Mapping[str, Any] | None,
) -> dict[str, object]:
    records = build_proactive_ooda_approval_outcome_projection_records(
        receipt=receipt,
        safe_work_result=safe_work_result,
        approval_outcome=approval_outcome,
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
        session_id=f"proactive-ooda-teable-approval-sync:{uuid4()}",
        step_id=f"proactive-ooda-teable-approval-sync-step:{uuid4()}",
        tool_name=definition.tool_name,
        action_kind="table.sync",
        payload_json={
            "projection_scope": "proactive_ooda_approval",
            "person_id": _receipt_value(receipt, "principal_id_hash"),
            "tables_json": syncable_tables,
            "table_config_json": {table_name: configured_tables[table_name] for table_name in syncable_tables},
        },
        context_json={"approval_outcome_id": str(dict(approval_outcome or {}).get("outcome_id") or "").strip()},
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
    suppressed_projection: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    stage_kinds = [
        _normalized_stage_kind(item.stage_kind)
        for item in digest.items
        if _normalized_stage_kind(item.stage_kind)
    ]
    approval_surface = _receipt_approval_surface(receipt)
    approval_surface_message_ids = [
        str(item or "").strip()
        for item in list(approval_surface.get("message_ids") or [])
        if str(item or "").strip()
    ]
    delivery_next_action_surface = _next_action_surface_fields(
        receipt.delivery_next_action,
        prefix="delivery_next_action",
    )
    suppressed = dict(suppressed_projection or {})
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
        "delivery_route_error": _compact_text(receipt.delivery_route_error, 160),
        "delivery_recovery_hint": _compact_text(receipt.delivery_recovery_hint, 500),
        "delivery_next_action": _compact_text(receipt.delivery_next_action, 120),
        **delivery_next_action_surface,
        "telegram_message_count": len(receipt.telegram_message_ids),
        "telegram_message_ids": list(receipt.telegram_message_ids),
        "approval_surface_present": bool(approval_surface.get("present")),
        "approval_surface_channel": _compact_text(approval_surface.get("channel"), 80),
        "approval_surface_status": _compact_text(approval_surface.get("status"), 80),
        "approval_surface_expires_at": _compact_text(approval_surface.get("expires_at"), 64),
        "approval_surface_callback_token_sha256": _compact_text(approval_surface.get("callback_token_sha256"), 80),
        "approval_surface_message_count": len(approval_surface_message_ids),
        "approval_surface_message_ids": approval_surface_message_ids,
        "stage_packet_count": len(receipt.stage_packet_ref_hashes),
        "stage_packet_error_count": int(receipt.stage_packet_error_count or 0),
        "safe_work_result_count": len(receipt.safe_work_result_ref_hashes),
        "safe_work_result_error_count": int(receipt.safe_work_result_error_count or 0),
        "error_code": _compact_text(receipt.error_code, 160),
        "deferred_reason": _compact_text(receipt.error_code, 160) if receipt.notification_status == "deferred" else "",
        "high_priority_count": sum(1 for item in digest.items if item.priority == "high"),
        "approval_required_count": sum(1 for item in digest.items if item.approval_required),
        "staged_item_count": sum(1 for item in digest.items if _item_has_stage(item)),
        "suppressed_item_count": int(suppressed.get("suppressed_item_count") or 0),
        "suppressed_safe_work_review_count": int(suppressed.get("suppressed_safe_work_review_count") or 0),
        "suppressed_projection_reasons": list(suppressed.get("suppressed_projection_reasons") or []),
        "suppressed_safe_work_issue_codes": list(suppressed.get("suppressed_safe_work_issue_codes") or []),
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
    receipt_details = dict(safe_work_result.get("execution_receipt") or {}) if safe_work_result else {}
    context_fit = dict(receipt_details.get("context_fit_receipt") or {})
    search_queries = _search_query_texts(receipt_details)
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
        "search_candidate_count": int(receipt_details.get("search_candidate_count") or 0),
        "search_query_count": len(search_queries),
        "context_fit_location_context_present": bool(context_fit.get("location_context_present")),
        "context_fit_locality_context_applied": bool(context_fit.get("locality_context_applied")),
        "context_fit_country_context_applied": bool(context_fit.get("country_context_applied")),
        "recommendation_reasons": list(recommended_comparison.get("recommendation_reasons") or []),
        "constraint_violations": list(recommended_comparison.get("constraint_violations") or []),
        "approval_prompt": _compact_text(safe_work_result.get("approval_prompt"), 500),
        "privacy_raw_principal_id_stored": False,
        "privacy_raw_signal_ref_stored": False,
        "privacy_raw_location_context_stored": False,
        "privacy_raw_recipient_context_stored": False,
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
    context_fit = dict(receipt_details.get("context_fit_receipt") or {})
    search_queries = _search_query_texts(receipt_details)
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
        "network_fetch_enabled": bool(receipt_details.get("network_fetch_enabled")),
        "network_fetch_count": int(receipt_details.get("network_fetch_count") or 0),
        "network_fetch_success_count": int(receipt_details.get("network_fetch_success_count") or 0),
        "search_candidate_count": int(receipt_details.get("search_candidate_count") or 0),
        "search_query_count": len(search_queries),
        "search_queries_used": search_queries[:6],
        "context_fit_provider_discovery_relevant": bool(context_fit.get("provider_discovery_relevant")),
        "context_fit_location_context_present": bool(context_fit.get("location_context_present")),
        "context_fit_locality_context_applied": bool(context_fit.get("locality_context_applied")),
        "context_fit_country_context_applied": bool(context_fit.get("country_context_applied")),
        "context_fit_location_phrase_count": int(context_fit.get("location_phrase_count") or 0),
        "context_fit_city_term_count": int(context_fit.get("city_term_count") or 0),
        "context_fit_postal_code_count": int(context_fit.get("postal_code_count") or 0),
        "context_fit_country_code_count": int(context_fit.get("country_code_count") or 0),
        "context_fit_country_name_count": int(context_fit.get("country_name_count") or 0),
        "context_fit_locality_context_hashes": [
            str(item).strip()
            for item in list(context_fit.get("locality_context_hashes") or [])
            if str(item).strip()
        ][:8],
        "context_fit_country_context_hashes": [
            str(item).strip()
            for item in list(context_fit.get("country_context_hashes") or [])
            if str(item).strip()
        ][:4],
        "context_fit_provider_query_term_count": int(context_fit.get("provider_query_term_count") or 0),
        "context_fit_provider_search_query_too_generic": bool(context_fit.get("provider_search_query_too_generic")),
        "privacy_raw_principal_id_stored": False,
        "privacy_raw_signal_ref_stored": False,
        "privacy_raw_location_context_stored": False,
        "privacy_raw_recipient_context_stored": False,
        "privacy_private_links_may_be_present": bool(dict(safe_work_result.get("privacy") or {}).get("private_links_may_be_present")),
    }


def _approval_surface_projection_row(
    *,
    receipt: ProactiveOodaRunReceipt | Mapping[str, Any],
    run_projection_id: str,
    safe_work_projection_id: str,
    approval_surface: Mapping[str, Any],
    approval_outcome: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    outcome = dict(approval_outcome or {})
    message_ids = [
        str(item or "").strip()
        for item in list(approval_surface.get("message_ids") or [])
        if str(item or "").strip()
    ]
    return {
        "projection_id": _approval_surface_projection_id(approval_surface),
        "run_projection_id": run_projection_id,
        "safe_work_projection_id": safe_work_projection_id,
        "sync_version": PROACTIVE_OODA_TEABLE_SYNC_VERSION,
        "principal_id_hash": _receipt_value(receipt, "principal_id_hash"),
        "channel": _compact_text(approval_surface.get("channel"), 80),
        "status": _compact_text(outcome.get("outcome") or approval_surface.get("status"), 80),
        "callback_token_sha256": _compact_text(approval_surface.get("callback_token_sha256"), 80),
        "expires_at": _compact_text(approval_surface.get("expires_at"), 64),
        "packet_ref_sha256": _compact_text(approval_surface.get("packet_ref_sha256"), 80),
        "staged_artifact_sha256": _compact_text(approval_surface.get("staged_artifact_sha256"), 80),
        "approval_prompt_sha256": _compact_text(approval_surface.get("approval_prompt_sha256"), 80),
        "staged_action_url_sha256": _compact_text(approval_surface.get("staged_action_url_sha256"), 80),
        "inline_button_count": int(approval_surface.get("inline_button_count") or 0),
        "url_button_count": int(approval_surface.get("url_button_count") or 0),
        "message_count": len(message_ids),
        "message_ids": message_ids,
        "decision_recorded": bool(outcome.get("approval_outcome_recorded")),
        "decision_accepted": bool(outcome.get("accepted")),
        "decision_source_kind": _compact_text(outcome.get("source_kind"), 80),
        "decision_recorded_at": _compact_text(outcome.get("recorded_at"), 64),
        "delivery_error_code": _compact_text(approval_surface.get("delivery_error_code"), 80),
        "privacy_raw_principal_id_stored": False,
        "privacy_raw_callback_token_stored": False,
        "privacy_raw_packet_ref_stored": False,
        "privacy_raw_staged_artifact_ref_stored": False,
        "privacy_raw_approval_prompt_stored": False,
        "privacy_raw_staged_action_url_stored": False,
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


def _safe_work_result_is_projectable(safe_work_result: Mapping[str, Any]) -> bool:
    safe_work = dict(safe_work_result or {})
    if not safe_work:
        return False
    audit = dict(safe_work.get("audit") or {})
    if str(audit.get("status") or "").strip().lower() == "pass":
        return True
    browser_receipt = dict(safe_work.get("browser_action_receipt") or {})
    return bool(
        str(safe_work.get("status") or "").strip() == "blocked_human_handoff_required"
        and browser_receipt.get("user_action_required") is True
    )


def _safe_work_projection_suppression_reason(safe_work_result: Mapping[str, Any]) -> str:
    safe_work = dict(safe_work_result or {})
    if not safe_work:
        return "safe_work_missing"
    audit = dict(safe_work.get("audit") or {})
    audit_status = str(audit.get("status") or "").strip().lower()
    if not audit:
        return "safe_work_audit_missing"
    return f"safe_work_audit_{audit_status or 'unknown'}"


def _safe_work_issue_codes(safe_work_result: Mapping[str, Any]) -> list[str]:
    audit = dict(dict(safe_work_result or {}).get("audit") or {})
    return [
        str(issue.get("code") or "").strip()
        for issue in list(audit.get("issues") or [])
        if isinstance(issue, Mapping) and str(issue.get("code") or "").strip()
    ]


def _suppressed_safe_work_projection_summary(
    *,
    digest: ProactiveOodaDigest,
    safe_work_rows: list[dict[str, Any]],
) -> dict[str, object]:
    suppressed_reasons: list[str] = []
    suppressed_issue_codes: list[str] = []
    review_count = 0
    for index, _item in enumerate(digest.items, start=1):
        safe_work_result = safe_work_rows[index - 1] if index - 1 < len(safe_work_rows) else {}
        if _safe_work_result_is_projectable(safe_work_result):
            continue
        reason = _safe_work_projection_suppression_reason(safe_work_result)
        suppressed_reasons.append(reason)
        audit_status = str(dict(safe_work_result.get("audit") or {}).get("status") or "").strip().lower()
        if audit_status == "review":
            review_count += 1
        suppressed_issue_codes.extend(_safe_work_issue_codes(safe_work_result))
    return {
        "suppressed_item_count": len(suppressed_reasons),
        "suppressed_safe_work_review_count": review_count,
        "suppressed_projection_reasons": sorted(dict.fromkeys(suppressed_reasons))[:8],
        "suppressed_safe_work_issue_codes": sorted(dict.fromkeys(suppressed_issue_codes))[:12],
    }


def _run_projection_id(receipt: ProactiveOodaRunReceipt) -> str:
    return f"proactive_ooda_run:{_hash_value(json.dumps(_receipt_projection_payload(receipt), sort_keys=True))[:24]}"


def _item_projection_id(*, run_projection_id: str, item: OodaInk, index: int) -> str:
    item_key = _hash_value(f"{item.signal_ref}|{index}")[:16]
    return f"{run_projection_id}:item:{index}:{item_key}"


def _safe_work_projection_id(*, safe_work_result: Mapping[str, Any], item_projection_id: str) -> str:
    result_id = str(safe_work_result.get("result_id") or "").strip()
    if result_id:
        return f"proactive_ooda_safe_work:{result_id}"
    return f"{item_projection_id}:safe_work"


def _approval_surface_projection_id(approval_surface: Mapping[str, Any]) -> str:
    callback_hash = str(approval_surface.get("callback_token_sha256") or "").strip()
    if callback_hash:
        return f"proactive_ooda_approval_surface:{callback_hash[:24]}"
    return f"proactive_ooda_approval_surface:{_hash_value(json.dumps(dict(approval_surface), sort_keys=True))[:24]}"


def _approval_outcome_projection_id(approval_outcome: Mapping[str, Any]) -> str:
    outcome_id = str(approval_outcome.get("outcome_id") or "").strip()
    if outcome_id:
        return f"proactive_ooda_approval_outcome:{outcome_id}"
    return f"proactive_ooda_approval_outcome:{_hash_value(json.dumps(dict(approval_outcome), sort_keys=True))[:24]}"


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


def _receipt_projection_payload(receipt: ProactiveOodaRunReceipt | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(receipt, Mapping):
        allowed = {field.name for field in fields(ProactiveOodaRunReceipt)}
        return {
            str(key): value
            for key, value in dict(receipt).items()
            if str(key) in allowed
        }
    return asdict(receipt)


def _receipt_value(receipt: ProactiveOodaRunReceipt | Mapping[str, Any], key: str) -> str:
    if isinstance(receipt, Mapping):
        return str(receipt.get(key) or "").strip()
    return str(getattr(receipt, key, "") or "").strip()


def _receipt_approval_surface(receipt: ProactiveOodaRunReceipt | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(receipt, Mapping):
        value = receipt.get("approval_surface")
    else:
        value = getattr(receipt, "approval_surface", None)
    return dict(value or {}) if isinstance(value, Mapping) else {}


def _search_query_texts(receipt_details: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for item in list(receipt_details.get("search_queries_used") or []):
        text = _compact_text(item, 240)
        if text:
            values.append(text)
    return values


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    return text if len(text) <= limit else f"{text[: max(limit - 1, 1)].rstrip()}..."


def _hash_value(value: str) -> str:
    import hashlib

    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
