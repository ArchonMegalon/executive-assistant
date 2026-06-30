#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://app.teable.ai"
DEFAULT_ENV_FILE = ROOT / ".env"


def _text_field(name: str) -> dict[str, object]:
    return {"name": name, "type": "singleLineText"}


def _long_text_field(name: str) -> dict[str, object]:
    return {"name": name, "type": "longText"}


def _number_field(name: str) -> dict[str, object]:
    return {"name": name, "type": "number"}


def _checkbox_field(name: str) -> dict[str, object]:
    return {"name": name, "type": "checkbox"}


PROACTIVE_OODA_TABLES: dict[str, list[dict[str, object]]] = {
    "proactive_ooda_runs": [
        _text_field("projection_id"),
        _text_field("sync_version"),
        _text_field("generated_at"),
        _text_field("principal_id_hash"),
        _text_field("notification_status"),
        _checkbox_field("dry_run"),
        _number_field("item_count"),
        _number_field("notified_ref_count"),
        _text_field("delivery_channel"),
        _text_field("delivery_transport"),
        _text_field("delivery_selected_by"),
        _text_field("delivery_recipient_hash"),
        _number_field("delivery_message_count"),
        _long_text_field("delivery_message_ids"),
        _text_field("delivery_outbox_id_hash"),
        _text_field("delivery_route_error"),
        _long_text_field("delivery_recovery_hint"),
        _text_field("delivery_next_action"),
        _long_text_field("delivery_next_action_href"),
        _text_field("delivery_next_action_label"),
        _text_field("delivery_next_action_method"),
        _number_field("telegram_message_count"),
        _long_text_field("telegram_message_ids"),
        _checkbox_field("approval_surface_present"),
        _text_field("approval_surface_channel"),
        _text_field("approval_surface_status"),
        _text_field("approval_surface_expires_at"),
        _text_field("approval_surface_callback_token_sha256"),
        _number_field("approval_surface_message_count"),
        _long_text_field("approval_surface_message_ids"),
        _number_field("stage_packet_count"),
        _number_field("stage_packet_error_count"),
        _number_field("safe_work_result_count"),
        _number_field("safe_work_result_error_count"),
        _checkbox_field("approval_outcome_recorded"),
        _checkbox_field("approval_outcome_accepted"),
        _text_field("approval_outcome_status"),
        _text_field("approval_outcome_source_kind"),
        _text_field("approval_outcome_recorded_at"),
        _text_field("approval_outcome_actor_sha256"),
        _text_field("approval_outcome_evidence_sha256"),
        _text_field("error_code"),
        _text_field("deferred_reason"),
        _number_field("high_priority_count"),
        _number_field("approval_required_count"),
        _number_field("staged_item_count"),
        _number_field("suppressed_item_count"),
        _number_field("suppressed_safe_work_review_count"),
        _long_text_field("suppressed_projection_reasons"),
        _long_text_field("suppressed_safe_work_issue_codes"),
        _long_text_field("stage_kinds"),
        _checkbox_field("privacy_raw_principal_id_stored"),
        _checkbox_field("privacy_raw_signal_ref_stored"),
    ],
    "proactive_ooda_items": [
        _text_field("projection_id"),
        _text_field("run_projection_id"),
        _text_field("sync_version"),
        _text_field("generated_at"),
        _text_field("principal_id_hash"),
        _number_field("item_index"),
        _text_field("notification_status"),
        _text_field("signal_ref_hash"),
        _text_field("priority"),
        _checkbox_field("approval_required"),
        _long_text_field("observe"),
        _long_text_field("orient"),
        _long_text_field("decide"),
        _long_text_field("act"),
        _long_text_field("ignored_consequence"),
        _long_text_field("action_plan"),
        _number_field("action_plan_count"),
        _text_field("stage_kind"),
        _long_text_field("stage_summary"),
        _long_text_field("stage_artifacts"),
        _number_field("stage_artifact_count"),
        _long_text_field("approval_gate"),
        _long_text_field("external_action_policy"),
        _number_field("evidence_count"),
        _text_field("safe_work_status"),
        _text_field("safe_work_work_type"),
        _long_text_field("safe_work_summary"),
        _long_text_field("staged_action_url"),
        _text_field("recommended_kind"),
        _long_text_field("recommended_label"),
        _long_text_field("recommended_url"),
        _number_field("shortlist_count"),
        _long_text_field("shortlist"),
        _number_field("comparison_row_count"),
        _number_field("search_candidate_count"),
        _number_field("search_query_count"),
        _checkbox_field("context_fit_location_context_present"),
        _checkbox_field("context_fit_locality_context_applied"),
        _checkbox_field("context_fit_country_context_applied"),
        _long_text_field("recommendation_reasons"),
        _long_text_field("constraint_violations"),
        _long_text_field("approval_prompt"),
        _checkbox_field("privacy_raw_principal_id_stored"),
        _checkbox_field("privacy_raw_signal_ref_stored"),
        _checkbox_field("privacy_raw_location_context_stored"),
        _checkbox_field("privacy_raw_recipient_context_stored"),
    ],
    "proactive_ooda_safe_work": [
        _text_field("projection_id"),
        _text_field("run_projection_id"),
        _text_field("item_projection_id"),
        _text_field("sync_version"),
        _text_field("generated_at"),
        _text_field("principal_id_hash"),
        _number_field("item_index"),
        _text_field("status"),
        _text_field("work_type"),
        _long_text_field("summary"),
        _text_field("recommended_kind"),
        _long_text_field("recommended_label"),
        _long_text_field("recommended_url"),
        _long_text_field("staged_action_url"),
        _number_field("shortlist_count"),
        _long_text_field("shortlist"),
        _number_field("comparison_row_count"),
        _long_text_field("comparison_table"),
        _number_field("risk_count"),
        _long_text_field("risks_or_tradeoffs"),
        _long_text_field("approval_prompt"),
        _checkbox_field("network_fetch_enabled"),
        _number_field("network_fetch_count"),
        _number_field("network_fetch_success_count"),
        _number_field("search_candidate_count"),
        _number_field("search_query_count"),
        _long_text_field("search_queries_used"),
        _checkbox_field("context_fit_provider_discovery_relevant"),
        _checkbox_field("context_fit_location_context_present"),
        _checkbox_field("context_fit_locality_context_applied"),
        _checkbox_field("context_fit_country_context_applied"),
        _number_field("context_fit_location_phrase_count"),
        _number_field("context_fit_city_term_count"),
        _number_field("context_fit_postal_code_count"),
        _number_field("context_fit_country_code_count"),
        _number_field("context_fit_country_name_count"),
        _long_text_field("context_fit_locality_context_hashes"),
        _long_text_field("context_fit_country_context_hashes"),
        _number_field("context_fit_provider_query_term_count"),
        _checkbox_field("context_fit_provider_search_query_too_generic"),
        _checkbox_field("approval_outcome_recorded"),
        _checkbox_field("approval_outcome_accepted"),
        _text_field("approval_outcome_status"),
        _text_field("approval_outcome_source_kind"),
        _text_field("approval_outcome_recorded_at"),
        _text_field("approval_outcome_actor_sha256"),
        _text_field("approval_outcome_evidence_sha256"),
        _checkbox_field("privacy_raw_principal_id_stored"),
        _checkbox_field("privacy_raw_signal_ref_stored"),
        _checkbox_field("privacy_raw_location_context_stored"),
        _checkbox_field("privacy_raw_recipient_context_stored"),
        _checkbox_field("privacy_private_links_may_be_present"),
    ],
    "proactive_ooda_approval_surfaces": [
        _text_field("projection_id"),
        _text_field("run_projection_id"),
        _text_field("safe_work_projection_id"),
        _text_field("sync_version"),
        _text_field("principal_id_hash"),
        _text_field("channel"),
        _text_field("status"),
        _text_field("callback_token_sha256"),
        _text_field("expires_at"),
        _text_field("packet_ref_sha256"),
        _text_field("staged_artifact_sha256"),
        _text_field("approval_prompt_sha256"),
        _text_field("staged_action_url_sha256"),
        _number_field("inline_button_count"),
        _number_field("url_button_count"),
        _number_field("message_count"),
        _long_text_field("message_ids"),
        _checkbox_field("decision_recorded"),
        _checkbox_field("decision_accepted"),
        _text_field("decision_source_kind"),
        _text_field("decision_recorded_at"),
        _text_field("delivery_error_code"),
        _checkbox_field("privacy_raw_principal_id_stored"),
        _checkbox_field("privacy_raw_callback_token_stored"),
        _checkbox_field("privacy_raw_packet_ref_stored"),
        _checkbox_field("privacy_raw_staged_artifact_ref_stored"),
        _checkbox_field("privacy_raw_approval_prompt_stored"),
        _checkbox_field("privacy_raw_staged_action_url_stored"),
    ],
    "proactive_ooda_approval_outcomes": [
        _text_field("projection_id"),
        _text_field("run_projection_id"),
        _text_field("safe_work_projection_id"),
        _text_field("sync_version"),
        _text_field("principal_id_hash"),
        _text_field("outcome"),
        _checkbox_field("accepted"),
        _text_field("status"),
        _text_field("source_kind"),
        _text_field("recorded_at"),
        _text_field("evidence_sha256"),
        _text_field("actor_sha256"),
        _text_field("packet_ref_sha256"),
        _text_field("staged_artifact_sha256"),
        _checkbox_field("privacy_raw_principal_id_stored"),
        _checkbox_field("privacy_raw_actor_exposed"),
        _checkbox_field("privacy_raw_evidence_exposed"),
        _checkbox_field("privacy_raw_packet_ref_exposed"),
        _checkbox_field("privacy_raw_staged_artifact_exposed"),
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or reconcile Teable tables for proactive OODA projections.")
    parser.add_argument("--base-id", default=os.environ.get("EA_ENV_TEABLE_BASE_ID") or "")
    parser.add_argument("--base-url", default=os.environ.get("TEABLE_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--table-name", action="append", dest="table_names", default=[])
    parser.add_argument("--create-missing", action="store_true")
    parser.add_argument("--write-config", action="store_true")
    return parser.parse_args()


def _dotenv_value(name: str, *, env_file: Path) -> str:
    direct = str(os.environ.get(name) or "").strip()
    if direct:
        return direct
    if not env_file.is_file():
        return ""
    prefix = f"{name}="
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        value = line[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    return ""


def _api_key(env_file: Path) -> str:
    return _dotenv_value("TEABLE_API_KEY", env_file=env_file)


def _request_json(*, method: str, url: str, api_key: str, body: dict[str, object] | None = None) -> object:
    data = None if body is None else json.dumps(body, ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://app.teable.ai",
            "Referer": "https://app.teable.ai/",
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:1000]
        raise SystemExit(f"teable_http_error:{exc.code}:{detail}") from exc
    except Exception as exc:
        raise SystemExit(f"teable_request_failed:{exc}") from exc
    if not payload.strip():
        return {}
    try:
        return json.loads(payload)
    except Exception as exc:
        raise SystemExit(f"teable_invalid_json:{exc}") from exc


def _list_tables(*, base_url: str, api_key: str, base_id: str) -> list[dict[str, object]]:
    payload = _request_json(
        method="GET",
        url=f"{base_url.rstrip('/')}/api/base/{urllib.parse.quote(base_id)}/table",
        api_key=api_key,
    )
    if isinstance(payload, dict):
        tables = payload.get("tables") or payload.get("data") or []
    else:
        tables = payload
    return [dict(item) for item in tables if isinstance(item, dict)]


def _discover_table_id(*, base_url: str, api_key: str, base_id: str, table_name: str) -> str:
    for table in _list_tables(base_url=base_url, api_key=api_key, base_id=base_id):
        if str(table.get("name") or "").strip() == table_name:
            return str(table.get("id") or "").strip()
    return ""


def _create_table(*, base_url: str, api_key: str, base_id: str, table_name: str, fields: list[dict[str, object]]) -> str:
    payload = _request_json(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/base/{urllib.parse.quote(base_id)}/table/",
        api_key=api_key,
        body={"name": table_name, "fields": fields, "fieldKeyType": "name"},
    )
    table_id = str(dict(payload if isinstance(payload, dict) else {}).get("id") or "").strip()
    if not table_id:
        raise SystemExit(f"teable_create_table_missing_id:{table_name}")
    return table_id


def _table_fields(*, base_url: str, api_key: str, table_id: str) -> list[dict[str, object]]:
    payload = _request_json(
        method="GET",
        url=f"{base_url.rstrip('/')}/api/table/{urllib.parse.quote(table_id)}/field",
        api_key=api_key,
    )
    if isinstance(payload, dict):
        fields = payload.get("fields") or payload.get("data") or []
    else:
        fields = payload
    return [dict(item) for item in fields if isinstance(item, dict)]


def _ensure_fields(*, base_url: str, api_key: str, table_id: str, fields: list[dict[str, object]]) -> int:
    existing = {str(field.get("name") or "").strip() for field in _table_fields(base_url=base_url, api_key=api_key, table_id=table_id)}
    created = 0
    for field in fields:
        name = str(field.get("name") or "").strip()
        if not name or name in existing:
            continue
        _request_json(
            method="POST",
            url=f"{base_url.rstrip('/')}/api/table/{urllib.parse.quote(table_id)}/field",
            api_key=api_key,
            body=dict(field),
        )
        existing.add(name)
        created += 1
    return created


def _load_table_config(*, env_file: Path) -> dict[str, dict[str, object]]:
    raw = _dotenv_value("TEABLE_TABLE_SYNC_CONFIG_JSON", env_file=env_file)
    if not raw:
        return {}
    loaded = None
    for candidate in (raw, raw.encode("utf-8").decode("unicode_escape")):
        try:
            loaded = json.loads(candidate)
            break
        except Exception:
            continue
    if not isinstance(loaded, dict):
        return {}
    return {
        str(table_name or "").strip(): dict(config or {})
        for table_name, config in loaded.items()
        if str(table_name or "").strip() and isinstance(config, dict)
    }


def _write_table_config(*, env_file: Path, mappings: dict[str, dict[str, object]]) -> None:
    merged = _load_table_config(env_file=env_file)
    merged.update(mappings)
    line = f"TEABLE_TABLE_SYNC_CONFIG_JSON={json.dumps(merged, separators=(',', ':'))}"
    if not env_file.exists():
        env_file.write_text(line + "\n", encoding="utf-8")
        return
    lines = env_file.read_text(encoding="utf-8").splitlines()
    updated: list[str] = []
    replaced = False
    for raw in lines:
        if raw.startswith("TEABLE_TABLE_SYNC_CONFIG_JSON="):
            updated.append(line)
            replaced = True
        else:
            updated.append(raw)
    if not replaced:
        updated.append(line)
    env_file.write_text("\n".join(updated) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    env_file = Path(args.env_file).expanduser()
    api_key = _api_key(env_file)
    if not api_key:
        raise SystemExit("teable_missing_api_key")
    base_id = str(args.base_id or _dotenv_value("EA_ENV_TEABLE_BASE_ID", env_file=env_file)).strip()
    if not base_id:
        raise SystemExit("teable_base_id_required")
    base_url = str(args.base_url or _dotenv_value("TEABLE_BASE_URL", env_file=env_file) or DEFAULT_BASE_URL).strip().rstrip("/")
    selected = [name for name in args.table_names if name in PROACTIVE_OODA_TABLES] or list(PROACTIVE_OODA_TABLES)
    results: list[dict[str, object]] = []
    mappings: dict[str, dict[str, object]] = {}
    for table_name in selected:
        fields = PROACTIVE_OODA_TABLES[table_name]
        table_id = _discover_table_id(base_url=base_url, api_key=api_key, base_id=base_id, table_name=table_name)
        created_table = False
        if not table_id:
            if not args.create_missing:
                raise SystemExit(f"teable_table_missing:{table_name}")
            table_id = _create_table(base_url=base_url, api_key=api_key, base_id=base_id, table_name=table_name, fields=fields)
            created_table = True
        fields_created = _ensure_fields(base_url=base_url, api_key=api_key, table_id=table_id, fields=fields)
        mapping = {
            "table_id": table_id,
            "key_field": "projection_id",
            "field_key_type": "name",
        }
        mappings[table_name] = mapping
        results.append(
            {
                "table_name": table_name,
                "table_id": table_id,
                "created_table": created_table,
                "fields_created": fields_created,
                "field_count": len(fields),
                "mapping": mapping,
            }
        )
    if args.write_config:
        _write_table_config(env_file=env_file, mappings=mappings)
    print(
        json.dumps(
            {
                "status": "ok",
                "base_id_present": True,
                "base_url": base_url,
                "table_count": len(results),
                "tables": results,
                "wrote_env_config": bool(args.write_config),
                "env_file": str(env_file),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
