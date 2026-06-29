#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
for candidate in (str(ROOT), str(EA_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.services.proactive_ooda_runtime_artifacts import (  # noqa: E402
    SAFE_WORK_RESULT_SCHEMA,
    STAGE_PACKET_SCHEMA,
    latest_payloads,
    load_runtime_artifact_bundle,
)
from app.services.proactive_ooda_service import (  # noqa: E402
    OodaInk,
    ProactiveOodaDigest,
    ProactiveOodaRunReceipt,
)
from app.services.proactive_ooda_teable_sync import (  # noqa: E402
    sync_proactive_ooda_to_teable,
    teable_sync_enabled,
)


DEFAULT_STATE_PATH = "state/proactive_ooda_notified.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resync existing proactive OODA run artifacts into Teable.")
    parser.add_argument("--principal-id", default="")
    parser.add_argument("--state-path", default=DEFAULT_STATE_PATH)
    parser.add_argument("--receipt-path", default="")
    parser.add_argument("--stage-packet-dir", default="")
    parser.add_argument("--safe-work-result-dir", default="")
    parser.add_argument("--write-receipt", action="store_true")
    parser.add_argument("--require-enabled", action=argparse.BooleanOptionalAction, default=False)
    return parser.parse_args()


def _hash_value(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest() if value else ""


def _json_safe_teable_sync(sync: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": str(sync.get("status") or "").strip(),
        "sync_attempted": bool(sync.get("sync_attempted")),
        "blocked_reason": str(sync.get("blocked_reason") or "").strip(),
        "missing_tables": [
            str(item or "").strip()
            for item in list(sync.get("missing_tables") or [])
            if str(item or "").strip()
        ],
        "projection_summary": dict(sync.get("projection_summary") or {}),
    }


def _run_receipt_from_mapping(row: Mapping[str, Any]) -> ProactiveOodaRunReceipt:
    bool_fields = {"dry_run"}
    int_fields = {"item_count", "stage_packet_error_count", "safe_work_result_error_count"}
    tuple_fields = {
        "notified_ref_hashes",
        "telegram_message_ids",
        "stage_packet_ref_hashes",
        "safe_work_result_ref_hashes",
        "delivery_message_ids",
    }
    values: dict[str, Any] = {}
    for field in fields(ProactiveOodaRunReceipt):
        value = row.get(field.name)
        if field.name in tuple_fields:
            value = tuple(str(item or "").strip() for item in list(value or []) if str(item or "").strip())
        elif field.name == "approval_surface":
            value = dict(value or {}) if isinstance(value, Mapping) else None
        elif field.name in bool_fields:
            value = bool(value)
        elif field.name in int_fields:
            value = int(value or 0)
        else:
            value = str(value or "").strip()
        values[field.name] = value
    return ProactiveOodaRunReceipt(**values)


def _stage_packet_ref(packet: Mapping[str, Any]) -> str:
    return str(packet.get("packet_ref") or packet.get("packet_id") or "").strip()


def _safe_work_result_ref(result: Mapping[str, Any]) -> str:
    result_ref = str(result.get("result_ref") or "").strip()
    if result_ref:
        return result_ref
    result_id = str(result.get("result_id") or "").strip()
    return f"safe_work_result:{result_id}" if result_id else ""


def _matching_stage_packets(*, stage_packet_dir: Path, run_receipt: Mapping[str, Any]) -> list[dict[str, Any]]:
    expected_hashes = {
        str(item or "").strip()
        for item in list(run_receipt.get("stage_packet_ref_hashes") or [])
        if str(item or "").strip()
    }
    rows: list[dict[str, Any]] = []
    for _path, packet, _mtime in latest_payloads(stage_packet_dir, schema=STAGE_PACKET_SCHEMA):
        packet_ref = _stage_packet_ref(packet)
        if packet_ref and _hash_value(packet_ref) in expected_hashes:
            rows.append(packet)
    rows.sort(key=lambda packet: int(packet.get("item_index") or 0))
    return rows


def _matching_safe_work_results(*, safe_work_result_dir: Path, run_receipt: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    expected_hashes = {
        str(item or "").strip()
        for item in list(run_receipt.get("safe_work_result_ref_hashes") or [])
        if str(item or "").strip()
    }
    by_packet_hash: dict[str, dict[str, Any]] = {}
    for _path, result, _mtime in latest_payloads(safe_work_result_dir, schema=SAFE_WORK_RESULT_SCHEMA):
        result_ref = _safe_work_result_ref(result)
        packet_hash = str(result.get("source_packet_ref_hash") or "").strip()
        if result_ref and packet_hash and _hash_value(result_ref) in expected_hashes and packet_hash not in by_packet_hash:
            by_packet_hash[packet_hash] = result
    return by_packet_hash


def _item_from_stage_packet(packet: Mapping[str, Any]) -> OodaInk:
    stage = dict(packet.get("stage") or {})
    approval = dict(packet.get("approval") or {})
    stage_payload = dict(stage.get("payload") or {}) if isinstance(stage.get("payload"), Mapping) else {}
    evidence_hashes = [
        str(item or "").strip()
        for item in list(packet.get("evidence_hashes") or [])
        if str(item or "").strip()
    ]
    signal_ref_hash = str(packet.get("signal_ref_hash") or "").strip()
    packet_id = str(packet.get("packet_id") or _stage_packet_ref(packet) or "").strip()
    return OodaInk(
        signal_ref=f"stage_packet_signal:{signal_ref_hash or _hash_value(packet_id)}",
        priority=str(packet.get("priority") or "normal").strip() or "normal",
        observe=str(packet.get("observe") or "").strip(),
        orient=str(packet.get("orient") or "").strip(),
        decide=str(packet.get("decide") or "").strip(),
        act=str(packet.get("act") or "").strip(),
        evidence=tuple(f"evidence_hash:{value}" for value in evidence_hashes),
        approval_required=bool(approval.get("required")),
        ignored_consequence=str(packet.get("ignored_consequence") or "").strip(),
        notify=True,
        action_plan=tuple(str(item or "").strip() for item in list(packet.get("action_plan") or []) if str(item or "").strip()),
        stage_kind=str(stage.get("kind") or "").strip(),
        stage_summary=str(stage.get("summary") or "").strip(),
        stage_artifacts=tuple(str(item or "").strip() for item in list(stage.get("artifacts") or []) if str(item or "").strip()),
        stage_payload=stage_payload,
        approval_gate=str(approval.get("gate") or "").strip(),
        external_action_policy=str(approval.get("external_action_policy") or "").strip(),
    )


def main() -> int:
    args = parse_args()
    if args.require_enabled and not teable_sync_enabled():
        print(json.dumps({"status": "blocked", "blocked_reason": "teable_sync_disabled"}, sort_keys=True))
        return 2
    bundle = load_runtime_artifact_bundle(
        root=ROOT,
        state_path=args.state_path,
        receipt_path=args.receipt_path,
        stage_packet_dir=args.stage_packet_dir,
        safe_work_result_dir=args.safe_work_result_dir,
    )
    run_receipt = dict(bundle.get("run_receipt") or {})
    run_receipt_path = bundle.get("run_receipt_path")
    stage_packet_dir = bundle.get("stage_packet_dir")
    safe_work_result_dir = bundle.get("safe_work_result_dir")
    if not run_receipt or not isinstance(run_receipt_path, Path):
        print(json.dumps({"status": "blocked", "blocked_reason": "run_receipt_missing"}, sort_keys=True))
        return 2
    if not isinstance(stage_packet_dir, Path) or not isinstance(safe_work_result_dir, Path):
        print(json.dumps({"status": "blocked", "blocked_reason": "artifact_dirs_missing"}, sort_keys=True))
        return 2

    stage_packets = _matching_stage_packets(stage_packet_dir=stage_packet_dir, run_receipt=run_receipt)
    safe_work_by_packet_hash = _matching_safe_work_results(safe_work_result_dir=safe_work_result_dir, run_receipt=run_receipt)
    items = [_item_from_stage_packet(packet) for packet in stage_packets]
    safe_work_results = [
        safe_work_by_packet_hash.get(_hash_value(_stage_packet_ref(packet)), {})
        for packet in stage_packets
    ]
    if not items:
        print(json.dumps({"status": "blocked", "blocked_reason": "stage_packets_missing"}, sort_keys=True))
        return 2

    receipt = _run_receipt_from_mapping(run_receipt)
    digest = ProactiveOodaDigest(
        principal_id=str(args.principal_id or run_receipt.get("principal_id_hash") or "").strip(),
        generated_at=receipt.generated_at,
        items=tuple(items),
        notified_refs=tuple(str(item or "").strip() for item in list(run_receipt.get("notified_ref_hashes") or []) if str(item or "").strip()),
    )
    sync = sync_proactive_ooda_to_teable(
        principal_id=digest.principal_id,
        digest=digest,
        receipt=receipt,
        safe_work_results=tuple(safe_work_results),
    )
    compact_sync = _json_safe_teable_sync(sync)
    if args.write_receipt:
        updated = dict(run_receipt)
        updated["teable_sync"] = compact_sync
        run_receipt_path.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": compact_sync["status"],
                "sync_attempted": compact_sync["sync_attempted"],
                "blocked_reason": compact_sync["blocked_reason"],
                "missing_tables": compact_sync["missing_tables"],
                "record_count": int(dict(compact_sync.get("projection_summary") or {}).get("record_count") or 0),
                "run_receipt_path": run_receipt_path.as_posix(),
                "stage_packet_count": len(stage_packets),
                "safe_work_result_count": len([result for result in safe_work_results if result]),
                "receipt_updated": bool(args.write_receipt),
            },
            sort_keys=True,
        )
    )
    return 0 if compact_sync["status"] in {"synced", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
