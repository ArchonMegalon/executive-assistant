#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "ea/_completion/aiwritebook/canary/AIWRITEBOOK_CANARY_MANIFEST.generated.json"
DEFAULT_OUTPUT = ROOT / "ea/_completion/aiwritebook/canary/AIWRITEBOOK_CANARY_APPROVAL_REQUEST.generated.json"
CONTRACT = "ea.aiwritebook.canary_approval_request"
EXPECTED_FIXTURE_ID = "aiwritebook-chronicle-export-canary-v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _timestamp(value: str | None = None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat()
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at_must_be_an_iso_timestamp_with_timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError("generated_at_must_be_an_iso_timestamp_with_timezone")
    return parsed.astimezone(UTC).isoformat()


def load_manifest(path: Path) -> dict[str, Any]:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("aiwritebook_canary_manifest_missing_or_unsafe")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("aiwritebook_canary_manifest_invalid")
    recorded = str(payload.get("manifest_sha256") or "")
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256", None)
    computed = _sha256(_canonical_json(unsigned))
    boundary = payload.get("execution_boundary")
    credit_budget = payload.get("credit_budget")
    source_packet = payload.get("source")
    if (
        payload.get("contract") != "ea.aiwritebook.synthetic_canary"
        or payload.get("contract_version") != 1
        or payload.get("fixture_id") != EXPECTED_FIXTURE_ID
        or not SHA256_PATTERN.fullmatch(recorded)
        or recorded != computed
        or not isinstance(boundary, dict)
        or boundary.get("operator_required") is not True
        or boundary.get("unattended_browser_automation_allowed") is not False
        or boundary.get("publication_allowed") is not False
        or boundary.get("external_send_allowed") is not False
        or not isinstance(source_packet, dict)
        or not SHA256_PATTERN.fullmatch(str(source_packet.get("sha256") or ""))
        or not isinstance(credit_budget, dict)
        or credit_budget.get("maximum_approved_credits") != 18
    ):
        raise ValueError("aiwritebook_canary_manifest_invalid")
    return payload


def confirmation_token(manifest_sha256: str) -> str:
    return f"approve-aiwritebook-canary-{manifest_sha256[:12]}-max18"


def build_request(manifest: dict[str, Any], *, generated_at: str | None = None) -> dict[str, Any]:
    manifest_sha256 = str(manifest["manifest_sha256"])
    token = confirmation_token(manifest_sha256)
    payload: dict[str, Any] = {
        "contract": CONTRACT,
        "contract_version": 1,
        "status": "awaiting_explicit_approval",
        "generated_at": _timestamp(generated_at),
        "fixture_id": manifest["fixture_id"],
        "fixture_manifest_sha256": manifest_sha256,
        "source_sha256": manifest["source"]["sha256"],
        "data_classification": "synthetic_no_personal_or_campaign_data",
        "maximum_credits": 18,
        "requested_actions": {
            "provider_project_creation": True,
            "source_upload": True,
            "generation": True,
            "credit_spend": True,
            "export_download": True,
            "provider_project_deletion": True,
            "publication": False,
            "external_send": False,
        },
        "required_confirmation_token": token,
        "approval_effect": (
            "Authorizes only the synthetic canary project, upload, generation up to 18 credits, "
            "PDF/EPUB/DOCX download, and deletion. It never authorizes publication or external send."
        ),
        "provider_action_performed": False,
        "secret_material_in_receipt": False,
    }
    payload["request_sha256"] = _sha256(_canonical_json(payload))
    return payload


def load_request(path: Path) -> dict[str, Any]:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("aiwritebook_canary_approval_request_missing_or_unsafe")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("aiwritebook_canary_approval_request_invalid")
    recorded = str(payload.get("request_sha256") or "")
    expected_actions = {
        "provider_project_creation": True,
        "source_upload": True,
        "generation": True,
        "credit_spend": True,
        "export_download": True,
        "provider_project_deletion": True,
        "publication": False,
        "external_send": False,
    }
    unsigned = dict(payload)
    unsigned.pop("request_sha256", None)
    if (
        payload.get("contract") != CONTRACT
        or payload.get("contract_version") != 1
        or payload.get("status") != "awaiting_explicit_approval"
        or payload.get("fixture_id") != EXPECTED_FIXTURE_ID
        or payload.get("maximum_credits") != 18
        or payload.get("requested_actions") != expected_actions
        or payload.get("provider_action_performed") is not False
        or payload.get("secret_material_in_receipt") is not False
        or not SHA256_PATTERN.fullmatch(str(payload.get("fixture_manifest_sha256") or ""))
        or not SHA256_PATTERN.fullmatch(str(payload.get("source_sha256") or ""))
        or payload.get("required_confirmation_token") != confirmation_token(str(payload.get("fixture_manifest_sha256")))
        or not SHA256_PATTERN.fullmatch(recorded)
        or recorded != _sha256(_canonical_json(unsigned))
    ):
        raise ValueError("aiwritebook_canary_approval_request_invalid")
    return payload


def write_private_json(path: Path, payload: dict[str, Any], *, replace: bool) -> None:
    target = Path(path)
    for parent in (target.parent, *target.parent.parents):
        if parent.is_symlink():
            raise RuntimeError("output_parent_symlink_not_allowed")
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise RuntimeError("output_target_unsafe")
    if target.exists() and not replace:
        raise FileExistsError("output_exists_use_replace")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    temp = Path(raw_temp)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(_canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise RuntimeError("output_target_changed")
            os.replace(temp, target)
        else:
            os.link(temp, target, follow_symlinks=False)
            temp.unlink()
        os.chmod(target, 0o600, follow_symlinks=False)
    finally:
        temp.unlink(missing_ok=True)


def materialize_request(
    *, manifest_path: Path = DEFAULT_MANIFEST,
    output_path: Path = DEFAULT_OUTPUT,
    generated_at: str | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    request = build_request(load_manifest(manifest_path), generated_at=generated_at)
    write_private_json(output_path, request, replace=replace)
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a non-authorizing AIWriteBook canary approval request.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    payload = materialize_request(
        manifest_path=args.manifest,
        output_path=args.output,
        generated_at=args.generated_at,
        replace=args.replace,
    )
    print(json.dumps({"status": payload["status"], "confirmation_token": payload["required_confirmation_token"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
