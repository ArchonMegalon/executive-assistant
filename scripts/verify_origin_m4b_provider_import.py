#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any


CONTRACT_NAME = "ea.origin_m4b_provider_import_gate.v1"
APPROVED_PROVIDERS = {"inkfluence", "unmixr", "unmixr ai"}
REJECT_MARKERS = (
    "fallback",
    "probe",
    "placeholder",
    "sentinel",
    "self_generated",
    "self-generated",
    "browser proof",
    "local_fixture",
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: JSON object required")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _string(value: object) -> str:
    return str(value or "").strip()


def _contains_marker(value: object) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return any(marker in lowered for marker in REJECT_MARKERS)
    if isinstance(value, dict):
        return any(_contains_marker(key) or _contains_marker(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_marker(item) for item in value)
    return False


def _display_path(path: Path, namespace: str, branch: str) -> str:
    return f"{namespace}/{branch}/{path.name}"


def _verified_receipt(payload: dict[str, Any]) -> bool:
    return _string(payload.get("status")).lower() in {"verified", "pass", "imported", "ready"}


def verify(
    *,
    namespace: str,
    m4b: Path,
    cover: Path,
    provider_receipt: Path,
    cover_receipt: Path,
    source_sha256: str,
    output: Path | None = None,
) -> dict[str, Any]:
    issues: list[str] = []
    provider_payload: dict[str, Any] = {}
    cover_payload: dict[str, Any] = {}
    m4b_sha = ""
    cover_sha = ""

    if not m4b.is_file():
        issues.append("m4b_missing")
    elif m4b.suffix.lower() != ".m4b":
        issues.append("m4b_suffix_not_m4b")
    elif m4b.stat().st_size <= 0:
        issues.append("m4b_empty")
    else:
        m4b_sha = _sha256_file(m4b)

    if not cover.is_file():
        issues.append("cover_missing")
    elif cover.stat().st_size <= 0:
        issues.append("cover_empty")
    else:
        cover_sha = _sha256_file(cover)

    if not provider_receipt.is_file():
        issues.append("provider_receipt_missing")
    else:
        try:
            provider_payload = _read_json(provider_receipt)
            provider = _string(provider_payload.get("provider") or provider_payload.get("sourceProvider"))
            if provider.lower() not in APPROVED_PROVIDERS:
                issues.append("provider_not_approved")
            if not _verified_receipt(provider_payload):
                issues.append("provider_receipt_not_verified")
            if m4b_sha and _string(provider_payload.get("m4bSha256") or provider_payload.get("audiobookSha256")) != m4b_sha:
                issues.append("provider_receipt_m4b_hash_mismatch")
            if source_sha256 and _string(provider_payload.get("sourceSha256") or provider_payload.get("manuscriptSha256")) != source_sha256:
                issues.append("provider_receipt_source_hash_mismatch")
            if _contains_marker(provider_payload):
                issues.append("provider_receipt_contains_rejected_marker")
        except (OSError, json.JSONDecodeError, ValueError):
            issues.append("provider_receipt_unreadable")

    if not cover_receipt.is_file():
        issues.append("m4b_cover_receipt_missing")
    else:
        try:
            cover_payload = _read_json(cover_receipt)
            if not _verified_receipt(cover_payload):
                issues.append("m4b_cover_receipt_not_verified")
            if cover_sha and _string(cover_payload.get("coverSha256") or cover_payload.get("cover_sha256")) != cover_sha:
                issues.append("m4b_cover_hash_mismatch")
            if m4b_sha and _string(cover_payload.get("m4bSha256") or cover_payload.get("audiobookSha256")) != m4b_sha:
                issues.append("m4b_cover_receipt_audio_hash_mismatch")
            if _contains_marker(cover_payload):
                issues.append("m4b_cover_receipt_contains_rejected_marker")
        except (OSError, json.JSONDecodeError, ValueError):
            issues.append("m4b_cover_receipt_unreadable")

    if m4b.name and _contains_marker(m4b.name):
        issues.append("m4b_filename_contains_rejected_marker")

    payload: dict[str, Any] = {
        "contractName": CONTRACT_NAME,
        "operation": "origin_m4b_provider_import_gate",
        "provider": "EA",
        "status": "pass" if not issues else "blocked",
        "goldEligible": not issues,
        "createdAtUtc": _now_iso(),
        "namespace": namespace,
        "m4bPath": _display_path(m4b, namespace, "audiobook"),
        "m4bSha256": m4b_sha,
        "coverPath": _display_path(cover, namespace, "audiobook"),
        "coverSha256": cover_sha,
        "sourceSha256": source_sha256,
        "providerReceiptPath": _display_path(provider_receipt, namespace, "audiobook"),
        "coverReceiptPath": _display_path(cover_receipt, namespace, "audiobook"),
        "issues": issues,
        "shareCreated": False,
        "rawRuntimePathsExposed": False,
        "rawCredentialExposed": False,
        "rawProviderTokenExposed": False,
        "tokens": [
            namespace,
            m4b_sha,
            cover_sha,
            source_sha256,
            *([] if issues else ["provider_m4b_verified", "m4b_cover_embedded"]),
        ],
    }
    if output is not None:
        _write_json(output, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an Origin Edition M4B is provider-backed and cover-bound.")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--m4b", required=True, type=Path)
    parser.add_argument("--cover", required=True, type=Path)
    parser.add_argument("--provider-receipt", required=True, type=Path)
    parser.add_argument("--cover-receipt", required=True, type=Path)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = verify(
        namespace=args.namespace,
        m4b=args.m4b,
        cover=args.cover,
        provider_receipt=args.provider_receipt,
        cover_receipt=args.cover_receipt,
        source_sha256=args.source_sha256,
        output=args.output,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
