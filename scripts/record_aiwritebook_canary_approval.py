#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re

from materialize_aiwritebook_canary_approval_request import load_request, write_private_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUEST = ROOT / "ea/_completion/aiwritebook/canary/AIWRITEBOOK_CANARY_APPROVAL_REQUEST.generated.json"
DEFAULT_OUTPUT = ROOT / "ea/_completion/aiwritebook/canary/AIWRITEBOOK_CANARY_APPROVAL.generated.json"
SAFE_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("approved_at_must_be_an_iso_timestamp_with_timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError("approved_at_must_be_an_iso_timestamp_with_timezone")
    return parsed.astimezone(UTC).isoformat()


def record_approval(
    *,
    request_path: Path,
    output_path: Path,
    confirmation: str,
    approved_by_ref: str,
    approved_at: str,
    replace: bool = False,
) -> dict[str, object]:
    request = load_request(request_path)
    if confirmation != request["required_confirmation_token"]:
        raise ValueError("exact_aiwritebook_canary_confirmation_required")
    if not SAFE_REF_PATTERN.fullmatch(approved_by_ref):
        raise ValueError("approved_by_ref_must_be_an_opaque_safe_reference")
    actions = request.get("requested_actions")
    if not isinstance(actions, dict):
        raise ValueError("aiwritebook_canary_approval_request_invalid")
    payload: dict[str, object] = {
        "contract": "ea.aiwritebook.canary_approval",
        "contract_version": 1,
        "status": "approved",
        "fixture_manifest_sha256": request["fixture_manifest_sha256"],
        "approval_request_sha256": request["request_sha256"],
        "approved_by_ref": approved_by_ref,
        "approved_at": _timestamp(approved_at),
        "maximum_credits": request["maximum_credits"],
        "approved_actions": actions,
        "secret_material_in_receipt": False,
    }
    write_private_json(output_path, payload, replace=replace)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Record an exact, digest-bound AIWriteBook canary approval.")
    parser.add_argument("--request", type=Path, default=DEFAULT_REQUEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--approved-by-ref", required=True)
    parser.add_argument("--approved-at", required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    payload = record_approval(
        request_path=args.request,
        output_path=args.output,
        confirmation=args.confirmation,
        approved_by_ref=args.approved_by_ref,
        approved_at=args.approved_at,
        replace=args.replace,
    )
    print(json.dumps({"status": payload["status"], "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
