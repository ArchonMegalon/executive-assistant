#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "ea/_completion/poppy/drafts"
ALLOWED_INPUT_KINDS = {
    "public_video_transcript",
    "public_pdf",
    "manually_approved_notes",
    "public_release_copy",
}
FORBIDDEN_FLAGS = {
    "contains_private_campaign_data",
    "contains_user_submission",
    "contains_private_memorial_memory",
    "contains_sourcebook_copied_text",
    "contains_product_truth",
    "contains_release_truth",
    "contains_support_truth",
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("source_packet_must_be_object")
    return payload


def _slug(value: str) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    text = "-".join(part for part in text.split("-") if part)
    return text[:80] or "poppy-draft"


def _verify_poppy_lane() -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_poppy_session.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    if completed.returncode != 0:
        missing = payload.get("missing_checks") if isinstance(payload, dict) else []
        raise RuntimeError(f"poppy_lane_not_verified:{missing}")
    if payload.get("lane_state") != "verified_draft_operator_lane":
        raise RuntimeError(f"poppy_lane_wrong_state:{payload.get('lane_state')}")
    if payload.get("runtime_enabled") is not False:
        raise RuntimeError("poppy_runtime_must_remain_disabled")
    return payload


def _validate_source_packet(packet: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    input_kind = str(packet.get("input_kind") or "").strip()
    if input_kind not in ALLOWED_INPUT_KINDS:
        failures.append(f"input_kind_not_allowed:{input_kind or '<missing>'}")

    visibility = str(packet.get("visibility") or "").strip().lower()
    if visibility not in {"public", "approved_public", "operator_approved"}:
        failures.append(f"visibility_not_allowed:{visibility or '<missing>'}")

    review_status = str(packet.get("review_status") or "").strip().lower()
    if review_status not in {"approved", "operator_approved", "public"}:
        failures.append(f"review_status_not_approved:{review_status or '<missing>'}")

    for flag in sorted(FORBIDDEN_FLAGS):
        if bool(packet.get(flag)):
            failures.append(f"forbidden_flag_set:{flag}")

    if not str(packet.get("source_packet_id") or "").strip():
        failures.append("source_packet_id_missing")
    if not (packet.get("source_refs") or packet.get("source_text")):
        failures.append("source_refs_or_source_text_missing")
    return failures


def build_draft_receipt(
    *,
    source_packet_path: Path,
    draft_output_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at: str | None = None,
) -> dict[str, Any]:
    lane_receipt = _verify_poppy_lane()
    packet = _load_json(source_packet_path)
    failures = _validate_source_packet(packet)
    if failures:
        raise RuntimeError("poppy_source_packet_rejected:" + ",".join(failures))

    draft_text = draft_output_path.read_text(encoding="utf-8").strip()
    if not draft_text:
        raise RuntimeError("poppy_draft_output_empty")

    packet_bytes = source_packet_path.read_bytes()
    draft_bytes = draft_output_path.read_bytes()
    source_packet_id = str(packet.get("source_packet_id") or "").strip()
    workflow_id = _slug(source_packet_id)
    now = generated_at or _utc_now()
    receipt = {
        "contract_name": "executive_assistant.poppy_draft_packet.v1",
        "generated_at": now,
        "provider": "Poppy AI",
        "lane": "poppy_draft_workbench",
        "lane_state": lane_receipt.get("lane_state"),
        "runtime_enabled": False,
        "source_packet_id": source_packet_id,
        "source_packet_sha256": _sha256_bytes(packet_bytes),
        "draft_output_sha256": _sha256_bytes(draft_bytes),
        "input_kind": str(packet.get("input_kind") or "").strip(),
        "visibility": str(packet.get("visibility") or "").strip(),
        "review_status": str(packet.get("review_status") or "").strip(),
        "export_mode": "manual_operator_copy_or_download_only",
        "draft_storage": "EA receipt stores hashes and review metadata; source markdown remains canonical truth.",
        "human_review_required": True,
        "allowed_use": "Draft text may be reviewed and copied into source-controlled EA/Chummer content only after human approval.",
        "forbidden_use": [
            "runtime_answer_generation",
            "product_truth",
            "release_truth",
            "support_truth",
            "private_user_content",
            "private_memorial_memory",
            "sourcebook_copied_text",
        ],
        "off_switch_env": "EA_POPPY_DRAFT_WORKBENCH_ENABLED",
        "status": "pending_human_review",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"POPPY_DRAFT_PACKET_{workflow_id.upper()}.generated.json"
    output_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return {**receipt, "output": str(output_path)}


def main() -> int:
    if any(arg in {"--help", "-h"} for arg in sys.argv[1:]):
        print(
            "Usage:\n"
            "  python3 scripts/materialize_poppy_draft_packet.py --source-packet <packet.json> --draft-output <draft.txt> [--output-dir <dir>]\n\n"
            "Materialize a governed Poppy draft packet receipt for public or operator-approved source packets."
        )
        return 0
    parser = argparse.ArgumentParser(description="Materialize a governed Poppy draft packet receipt.")
    parser.add_argument("--source-packet", required=True, help="Approved public/approved source packet JSON.")
    parser.add_argument("--draft-output", required=True, help="Manual Poppy draft text copied/downloaded by the operator.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for generated draft receipts.")
    args = parser.parse_args()

    try:
        receipt = build_draft_receipt(
            source_packet_path=Path(args.source_packet),
            draft_output_path=Path(args.draft_output),
            output_dir=Path(args.output_dir),
        )
    except Exception as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
    print(json.dumps({"status": "pass", "output": receipt["output"], "source_packet_id": receipt["source_packet_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
