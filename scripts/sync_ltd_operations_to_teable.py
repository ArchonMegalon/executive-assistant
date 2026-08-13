#!/usr/bin/env python3
"""Reconcile the secret-safe LTD operations projections into Teable.

The source projections contain booleans and governance metadata only. This
script deliberately refuses a source that claims to expose secret material.
Remote writes require ``--apply``; the default command is a local-only plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
import urllib.parse

try:
    from scripts.bootstrap_proactive_ooda_teable_tables import (
        DEFAULT_BASE_URL,
        _api_key,
        _create_table,
        _discover_table_id,
        _dotenv_value,
        _ensure_fields,
        _request_json,
    )
except ImportError:  # Direct execution adds scripts/, not the repository root.
    from bootstrap_proactive_ooda_teable_tables import (  # type: ignore[no-redef]
        DEFAULT_BASE_URL,
        _api_key,
        _create_table,
        _discover_table_id,
        _dotenv_value,
        _ensure_fields,
        _request_json,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = ROOT / ".env"
DEFAULT_PROVIDER_STATUS = ROOT / ".codex-studio/published/LTD_CAPACITY_STATUS.generated.json"
DEFAULT_PROOF_DEBT = ROOT / ".codex-studio/published/LTD_PROOF_DEBT.generated.json"
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/LTD_TEABLE_OPERATIONS.generated.json"
PAGE_SIZE = 1000
WRITE_BATCH_SIZE = 100
FORBIDDEN_SOURCE_FIELDS = {"api_key", "secret", "raw_prompt", "raw_output", "exit_ip"}


def _text(name: str, **options: object) -> dict[str, object]:
    return {"name": name, "type": "singleLineText", **options}


def _long_text(name: str) -> dict[str, object]:
    return {"name": name, "type": "longText"}


def _checkbox(name: str) -> dict[str, object]:
    return {"name": name, "type": "checkbox"}


TABLES: dict[str, list[dict[str, object]]] = {
    "ltd_provider_status": [
        _text("projection_id"),
        _text("generated_at"),
        _text("provider"),
        _long_text("task_class"),
        _text("slot_ref_sha256"),
        _long_text("credit_basis"),
        _text("route_decision"),
        _text("configured_state"),
        _checkbox("credential_present"),
        _text("credential_slot"),
        _text("maximum_blast_radius"),
        _checkbox("review_required"),
        _text("route_state"),
        _text("source_status"),
        _text("source_sha256"),
        _long_text("truth_posture"),
        _text("current_or_stale"),
        _checkbox("privacy_secret_material_exposed"),
    ],
    "ltd_proof_debt": [
        _text("projection_id"),
        _text("generated_at"),
        _text("service"),
        _text("current_workspace_tier"),
        _text("candidate_lane"),
        _long_text("next_proof"),
        _long_text("must_not_claim"),
        _checkbox("owner_review_required"),
        _text("source_status"),
        _text("source_sha256"),
        _long_text("truth_posture"),
        _text("current_or_stale"),
        _checkbox("privacy_secret_material_exposed"),
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan or apply secret-safe LTD operations projections to Teable.")
    parser.add_argument("--apply", action="store_true", help="Create/reconcile tables and upsert rows.")
    parser.add_argument("--create-missing", action="store_true", help="Allow --apply to create missing tables.")
    parser.add_argument("--base-id", default=os.environ.get("EA_ENV_TEABLE_BASE_ID") or "")
    parser.add_argument("--base-url", default=os.environ.get("TEABLE_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--provider-status-path", default=str(DEFAULT_PROVIDER_STATUS))
    parser.add_argument("--proof-debt-path", default=str(DEFAULT_PROOF_DEBT))
    parser.add_argument("--receipt-path", default=str(DEFAULT_RECEIPT))
    parser.add_argument(
        "--write-plan-receipt",
        action="store_true",
        help="Persist a local-only plan receipt. By default plans are stdout-only.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"ltd_projection_missing:{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"ltd_projection_invalid:{path}:{exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"ltd_projection_not_object:{path}")
    return payload


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _slug(value: object) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _forbidden_source_field(value: object) -> str:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")
            if normalized in FORBIDDEN_SOURCE_FIELDS:
                return normalized
            found = _forbidden_source_field(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _forbidden_source_field(nested)
            if found:
                return found
    return ""


def build_rows(*, provider_status_path: Path, proof_debt_path: Path) -> dict[str, list[dict[str, object]]]:
    provider_payload = _load_json(provider_status_path)
    proof_payload = _load_json(proof_debt_path)
    if bool(provider_payload.get("secret_material_exposed")):
        raise SystemExit("ltd_provider_projection_exposes_secret_material")
    if bool(proof_payload.get("secret_material_exposed")):
        raise SystemExit("ltd_proof_projection_exposes_secret_material")
    forbidden_field = _forbidden_source_field(provider_payload) or _forbidden_source_field(proof_payload)
    if forbidden_field:
        raise SystemExit(f"ltd_projection_forbidden_field:{forbidden_field}")

    provider_source_sha = _sha256_file(provider_status_path)
    proof_source_sha = _sha256_file(proof_debt_path)
    provider_rows: list[dict[str, object]] = []
    for source in provider_payload.get("providers") or []:
        if not isinstance(source, dict):
            continue
        provider = str(source.get("provider") or "").strip()
        if not provider:
            continue
        slot_ref_sha256 = str(source.get("slot_ref_sha256") or "").strip()
        if slot_ref_sha256 and not re.fullmatch(r"[0-9a-f]{64}", slot_ref_sha256):
            raise SystemExit(f"ltd_provider_projection_invalid_slot_ref:{_slug(provider)}")
        provider_rows.append(
            {
                "projection_id": f"ltd-provider:{_slug(provider)}",
                "generated_at": str(provider_payload.get("generated_at") or ""),
                "provider": provider,
                "task_class": str(source.get("task_class") or ""),
                "slot_ref_sha256": slot_ref_sha256,
                "credit_basis": str(source.get("credit_basis") or ""),
                "route_decision": str(source.get("route_decision") or source.get("route_state") or ""),
                "configured_state": str(source.get("configured_state") or ""),
                "credential_present": bool(source.get("credential_present")),
                "credential_slot": str(source.get("credential_slot") or ""),
                "maximum_blast_radius": str(source.get("maximum_blast_radius") or ""),
                "review_required": bool(source.get("review_required", True)),
                "route_state": str(source.get("route_state") or ""),
                "source_status": str(provider_payload.get("status") or ""),
                "source_sha256": provider_source_sha,
                "truth_posture": str(provider_payload.get("truth_posture") or ""),
                "current_or_stale": "current",
                "privacy_secret_material_exposed": False,
            }
        )

    proof_rows: list[dict[str, object]] = []
    for source in proof_payload.get("rows") or []:
        if not isinstance(source, dict):
            continue
        service = str(source.get("service") or "").strip()
        if not service:
            continue
        proof_rows.append(
            {
                "projection_id": f"ltd-proof-debt:{_slug(service)}",
                "generated_at": str(proof_payload.get("generated_at") or ""),
                "service": service,
                "current_workspace_tier": str(source.get("current_workspace_tier") or ""),
                "candidate_lane": str(source.get("candidate_lane") or ""),
                "next_proof": str(source.get("next_proof") or ""),
                "must_not_claim": str(source.get("must_not_claim") or ""),
                "owner_review_required": bool(source.get("owner_review_required", True)),
                "source_status": str(proof_payload.get("status") or ""),
                "source_sha256": proof_source_sha,
                "truth_posture": str(proof_payload.get("truth_posture") or ""),
                "current_or_stale": "current",
                "privacy_secret_material_exposed": False,
            }
        )
    return {"ltd_provider_status": provider_rows, "ltd_proof_debt": proof_rows}


def _list_records(*, base_url: str, api_key: str, table_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    skip = 0
    while True:
        query = urllib.parse.urlencode(
            {
                "fieldKeyType": "name",
                "cellFormat": "json",
                "take": PAGE_SIZE,
                "skip": skip,
            }
        )
        payload = _request_json(
            method="GET",
            url=f"{base_url.rstrip('/')}/api/table/{urllib.parse.quote(table_id)}/record?{query}",
            api_key=api_key,
        )
        source = payload.get("records") or payload.get("data") or [] if isinstance(payload, dict) else payload
        batch = [dict(item) for item in source if isinstance(item, dict)]
        records.extend(batch)
        if len(batch) < PAGE_SIZE:
            return records
        skip += PAGE_SIZE


def _chunked(rows: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    return [rows[index : index + WRITE_BATCH_SIZE] for index in range(0, len(rows), WRITE_BATCH_SIZE)]


def _teable_value_matches(current: object, expected: object) -> bool:
    # Teable omits false checkboxes and empty text cells from record payloads.
    if isinstance(expected, bool):
        return bool(current) is expected
    if expected == "":
        return current in {None, ""}
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return current == expected or str(current) == str(expected)
    return current == expected


def _upsert_rows(
    *, base_url: str, api_key: str, table_id: str, rows: list[dict[str, object]]
) -> dict[str, int]:
    existing: dict[str, dict[str, Any]] = {}
    for record in _list_records(base_url=base_url, api_key=api_key, table_id=table_id):
        fields = dict(record.get("fields") or {})
        projection_id = str(fields.get("projection_id") or "").strip()
        if projection_id:
            existing[projection_id] = record

    creates: list[dict[str, object]] = []
    updates: list[dict[str, object]] = []
    current_ids = {str(row.get("projection_id") or "") for row in rows}
    for row in rows:
        projection_id = str(row.get("projection_id") or "").strip()
        record = existing.get(projection_id)
        if not record:
            creates.append({"fields": row})
            continue
        record_id = str(record.get("id") or "").strip()
        current_fields = dict(record.get("fields") or {})
        if record_id and any(
            not _teable_value_matches(current_fields.get(key), value)
            for key, value in row.items()
        ):
            updates.append({"id": record_id, "fields": row})

    for projection_id, record in existing.items():
        fields = dict(record.get("fields") or {})
        record_id = str(record.get("id") or "").strip()
        if projection_id not in current_ids and record_id and fields.get("current_or_stale") != "stale":
            updates.append({"id": record_id, "fields": {"current_or_stale": "stale"}})

    for batch in _chunked(creates):
        _request_json(
            method="POST",
            url=f"{base_url.rstrip('/')}/api/table/{urllib.parse.quote(table_id)}/record",
            api_key=api_key,
            body={"fieldKeyType": "name", "typecast": True, "records": batch},
        )
    for batch in _chunked(updates):
        _request_json(
            method="PATCH",
            url=f"{base_url.rstrip('/')}/api/table/{urllib.parse.quote(table_id)}/record",
            api_key=api_key,
            body={"fieldKeyType": "name", "typecast": True, "records": batch},
        )
    return {"created": len(creates), "updated": len(updates), "current": len(rows)}


def _table_id_receipt(table_id: str) -> dict[str, object]:
    return {
        "present": bool(table_id),
        "sha256": hashlib.sha256(table_id.encode("utf-8")).hexdigest() if table_id else "",
    }


def _write_receipt(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    env_file = Path(args.env_file).expanduser()
    rows_by_table = build_rows(
        provider_status_path=Path(args.provider_status_path),
        proof_debt_path=Path(args.proof_debt_path),
    )
    receipt: dict[str, object] = {
        "contract": "ea.ltd.teable_operations.v1",
        "status": "plan_ready" if not args.apply else "projection_ready",
        "applied": bool(args.apply),
        "secret_material_exposed": False,
        "tables": {
            name: {"row_count": len(rows), "remote_table_id": {"present": False, "sha256": ""}}
            for name, rows in rows_by_table.items()
        },
        "truth_posture": "Teable is an operator projection only; source receipts remain authoritative.",
    }
    if not args.apply:
        if args.write_plan_receipt:
            _write_receipt(Path(args.receipt_path), receipt)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0

    api_key = _api_key(env_file)
    if not api_key:
        raise SystemExit("teable_missing_api_key")
    base_id = str(args.base_id or _dotenv_value("EA_ENV_TEABLE_BASE_ID", env_file=env_file)).strip()
    if not base_id:
        raise SystemExit("teable_base_id_required")
    base_url = str(args.base_url or _dotenv_value("TEABLE_BASE_URL", env_file=env_file) or DEFAULT_BASE_URL).strip().rstrip("/")
    table_receipts: dict[str, object] = {}
    for table_name, rows in rows_by_table.items():
        table_id = _discover_table_id(
            base_url=base_url,
            api_key=api_key,
            base_id=base_id,
            table_name=table_name,
        )
        created_table = False
        if not table_id:
            if not args.create_missing:
                raise SystemExit(f"teable_table_missing:{table_name}")
            table_id = _create_table(
                base_url=base_url,
                api_key=api_key,
                base_id=base_id,
                table_name=table_name,
                fields=TABLES[table_name],
            )
            created_table = True
        fields_created = _ensure_fields(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            fields=TABLES[table_name],
        )
        upsert = _upsert_rows(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            rows=rows,
        )
        table_receipts[table_name] = {
            "row_count": len(rows),
            "created_table": created_table,
            "fields_created": fields_created,
            "upsert": upsert,
            "remote_table_id": _table_id_receipt(table_id),
        }
    receipt["tables"] = table_receipts
    _write_receipt(Path(args.receipt_path), receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
