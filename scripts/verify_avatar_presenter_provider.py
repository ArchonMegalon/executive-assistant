#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LTD_PATH = ROOT / "LTDs.md"
DEFAULT_OUT_DIR = Path("/docker/fleet/state/chummer6/avatar_presenter_provider")
DEFAULT_RECEIPT_DIR = DEFAULT_OUT_DIR / "receipts"


PROVIDER_SPECS = {
    "vidboard": {
        "provider": "VidBoard",
        "service_key": "VidBoard.ai",
        "role": "photoreal_avatar_presenter_candidate",
        "account_email_hint": "the.girscheles@gmail.com",
        "status": "pilot",
        "commercial_use_allowed": False,
        "watermark_free": False,
        "lip_sync_verified": False,
        "viseme_quality_verified": False,
        "api_available": False,
        "manual_workflow_allowed": True,
        "privacy_terms_reviewed": False,
        "source_data_allowed": False,
        "max_duration": "unknown",
        "max_resolution": "unknown",
        "fallback_mode": "fallback_static_storyboard",
        "notes": "Primary candidate for a photoreal talking-avatar lane, but still blocked pending provider proof.",
    },
    "nonverbia": {
        "provider": "Nonverbia",
        "service_key": "Nonverbia",
        "role": "avatar_presenter_candidate",
        "account_email_hint": "",
        "status": "pilot",
        "commercial_use_allowed": False,
        "watermark_free": False,
        "lip_sync_verified": False,
        "viseme_quality_verified": False,
        "api_available": False,
        "manual_workflow_allowed": True,
        "privacy_terms_reviewed": False,
        "source_data_allowed": False,
        "max_duration": "unknown",
        "max_resolution": "unknown",
        "fallback_mode": "fallback_static_storyboard",
        "notes": "Secondary presenter candidate; evaluate after or alongside VidBoard.",
    },
}

RECEIPT_FIELD_MAP = {
    "login_capture": None,
    "commercial_use_terms_receipt": "commercial_use_allowed",
    "watermark_export_receipt": "watermark_free",
    "lip_sync_review_receipt": "lip_sync_verified",
    "viseme_quality_receipt": "viseme_quality_verified",
    "privacy_terms_receipt": "privacy_terms_reviewed",
    "source_data_boundary_receipt": "source_data_allowed",
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_ltd_rows() -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    if not LTD_PATH.is_file():
        return rows
    headers = ["service", "plan_tier", "holding", "status", "redeem_by", "workspace_integration_tier", "local_integration", "notes"]
    for raw_line in LTD_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("| `"):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) != len(headers):
            continue
        row = {header: value.strip(" `") for header, value in zip(headers, parts)}
        rows[row["service"]] = row
    return rows


def _provider_ready(spec: dict[str, object]) -> bool:
    return bool(
        spec["status"] == "verified"
        and spec["commercial_use_allowed"]
        and spec["watermark_free"]
        and spec["lip_sync_verified"]
        and spec["viseme_quality_verified"]
        and spec["privacy_terms_reviewed"]
        and spec["source_data_allowed"]
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _capture_summary_is_authenticated(capture_path: Path, provider_key: str) -> bool:
    if not capture_path.is_file():
        return False
    try:
        payload = json.loads(capture_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    return (
        str(payload.get("provider_key") or "").strip().lower() == provider_key
        and bool(payload.get("authenticated_workspace_detected") is True)
        and str(payload.get("render_status") or "").strip().lower() in {"completed", "completed_with_warnings"}
    )


def _receipt_capture_path(receipt: dict[str, Any]) -> Path | None:
    raw = str(receipt.get("capture_path") or "").strip()
    if not raw:
        return None
    return Path(raw)


def _receipt_capture_matches(receipt: dict[str, Any], provider_key: str) -> bool:
    capture_path = _receipt_capture_path(receipt)
    expected_sha = str(receipt.get("capture_file_sha256") or "").strip().lower()
    if capture_path is None or not expected_sha or not capture_path.is_file():
        return False
    try:
        actual_sha = _sha256_file(capture_path)
    except Exception:
        return False
    if actual_sha.lower() != expected_sha:
        return False
    return _capture_summary_is_authenticated(capture_path, provider_key)


def _manual_review_complete(receipt: dict[str, Any]) -> bool:
    return all(str(receipt.get(field) or "").strip() for field in ("reviewed_by", "reviewed_at", "evidence_ref"))


def _receipt_is_trusted(receipt: dict[str, Any], provider_key: str, receipt_type: str) -> tuple[bool, str]:
    verified = bool(receipt.get("verified") is True)
    if not verified:
        return False, "receipt_not_verified"
    if not _receipt_capture_matches(receipt, provider_key):
        return False, "capture_missing_or_hash_mismatch"
    if receipt_type == "login_capture":
        if bool(receipt.get("source_capture_authenticated") is not True):
            return False, "login_capture_not_authenticated"
        return True, "trusted_login_capture"
    if not _manual_review_complete(receipt):
        return False, "manual_review_metadata_missing"
    return True, "trusted_manual_review"


def _load_receipts(provider_key: str, receipt_dir: Path) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    if not receipt_dir.is_dir():
        return receipts
    for path in sorted(receipt_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        receipt_provider = str(payload.get("provider_key") or "").strip().lower()
        if receipt_provider and receipt_provider != provider_key:
            continue
        receipt = dict(payload)
        receipt["path"] = path.as_posix()
        receipts.append(receipt)
    return receipts


def _apply_receipts(spec: dict[str, object], receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = []
    provider_key = str(spec.get("provider") or "").strip().lower()
    for receipt in receipts:
        receipt_type = str(receipt.get("receipt_type") or "").strip()
        target_field = RECEIPT_FIELD_MAP.get(receipt_type)
        trusted, trust_status = _receipt_is_trusted(receipt, provider_key, receipt_type)
        loaded.append(
            {
                "receipt_type": receipt_type,
                "verified": bool(receipt.get("verified") is True),
                "trusted": trusted,
                "trust_status": trust_status,
                "path": str(receipt.get("path") or ""),
                "captured_at": str(receipt.get("captured_at") or ""),
            }
        )
        if target_field and trusted:
            spec[target_field] = True
        if receipt_type == "login_capture" and trusted:
            spec["status"] = "verified"
    return loaded


def build_payload(provider_key: str, *, allow_fallback: bool, receipt_dir: Path | None = None) -> dict[str, object]:
    normalized = provider_key.strip().lower()
    if normalized not in PROVIDER_SPECS:
        raise SystemExit(f"unknown provider: {provider_key}")
    spec = dict(PROVIDER_SPECS[normalized])
    loaded_receipts = _apply_receipts(spec, _load_receipts(normalized, receipt_dir or DEFAULT_RECEIPT_DIR))
    ltd_rows = _parse_ltd_rows()
    row = dict(ltd_rows.get(str(spec["service_key"])) or {})
    provider_ready = _provider_ready(spec)
    verdict = "VERIFIED_PROVIDER" if provider_ready else ("READY_VIA_FALLBACK" if allow_fallback else "NOT_READY")
    blocking_reasons: list[str] = []
    if not spec["commercial_use_allowed"]:
        blocking_reasons.append("Commercial-use rights are not yet verified.")
    if not spec["watermark_free"]:
        blocking_reasons.append("Watermark-free export is not yet verified.")
    if not spec["lip_sync_verified"]:
        blocking_reasons.append("Lip-sync quality is not yet verified.")
    if not spec["viseme_quality_verified"]:
        blocking_reasons.append("Viseme / mouth-shape quality is not yet verified.")
    if not spec["privacy_terms_reviewed"]:
        blocking_reasons.append("Privacy / retention terms have not been reviewed.")
    if not spec["source_data_allowed"]:
        blocking_reasons.append("No proof exists yet that memorial-source data is allowed for this provider.")
    return {
        "generated_at": _utc_now(),
        "contract_name": "executive_assistant.avatar_presenter_provider_proof.v1",
        "provider": str(spec["provider"]),
        "provider_key": normalized,
        "verdict": verdict,
        "fallback_mode": str(spec["fallback_mode"]),
        "provider_ready": provider_ready,
        "receipts_loaded": loaded_receipts,
        "account": {
            "service_key": str(spec["service_key"]),
            "account_status": str(row.get("status") or "tracked"),
            "account_email_hint": str(spec["account_email_hint"]),
            "tier": str(row.get("plan_tier") or "unknown"),
            "workspace_integration_tier": str(row.get("workspace_integration_tier") or "unknown"),
            "local_integration": str(row.get("local_integration") or ""),
        },
        "verification_checklist": {
            "commercial_use_rights": {"verified": bool(spec["commercial_use_allowed"]), "value": "proven" if spec["commercial_use_allowed"] else "not_proven"},
            "watermark_free_export": {"verified": bool(spec["watermark_free"]), "value": "proven" if spec["watermark_free"] else "not_proven"},
            "lip_sync_quality": {"verified": bool(spec["lip_sync_verified"]), "value": "proven" if spec["lip_sync_verified"] else "not_proven"},
            "viseme_quality": {"verified": bool(spec["viseme_quality_verified"]), "value": "proven" if spec["viseme_quality_verified"] else "not_proven"},
            "privacy_terms_reviewed": {"verified": bool(spec["privacy_terms_reviewed"]), "value": "reviewed" if spec["privacy_terms_reviewed"] else "not_reviewed"},
            "source_memorial_data_allowed": {"verified": bool(spec["source_data_allowed"]), "value": "allowed" if spec["source_data_allowed"] else "not_proven"},
            "api_available": {"verified": bool(spec["api_available"]), "value": bool(spec["api_available"])},
            "manual_workflow_allowed": {"verified": bool(spec["manual_workflow_allowed"]), "value": bool(spec["manual_workflow_allowed"])},
            "max_duration": {"verified": False, "value": str(spec["max_duration"])},
            "max_resolution": {"verified": False, "value": str(spec["max_resolution"])},
        },
        "notes": str(row.get("notes") or spec["notes"]),
        "blocking_reasons": blocking_reasons,
        "next_required_receipts": [
            "provider_login_capture",
            "commercial_use_terms_receipt",
            "watermark_export_receipt",
            "lip_sync_review_receipt",
            "source_data_boundary_receipt",
        ],
    }


def write_payload(payload: dict[str, object], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{str(payload['provider_key'])}_AVATAR_PRESENTER_PROVIDER_PROOF.generated.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a named avatar-presenter provider and fail closed if proof is incomplete.")
    parser.add_argument("--provider", required=True, choices=sorted(PROVIDER_SPECS.keys()))
    parser.add_argument("--allow-fallback", action="store_true")
    parser.add_argument("--write-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--receipt-dir", default=str(DEFAULT_RECEIPT_DIR))
    args = parser.parse_args()
    payload = build_payload(
        args.provider,
        allow_fallback=bool(args.allow_fallback),
        receipt_dir=Path(args.receipt_dir),
    )
    path = write_payload(payload, Path(args.write_dir))
    print(path)
    return 0 if payload["verdict"] != "NOT_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
