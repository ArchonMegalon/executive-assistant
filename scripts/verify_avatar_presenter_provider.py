#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LTD_PATH = ROOT / "LTDs.md"
DEFAULT_OUT_DIR = Path("/docker/fleet/state/chummer6/avatar_presenter_provider")


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


def build_payload(provider_key: str, *, allow_fallback: bool) -> dict[str, object]:
    normalized = provider_key.strip().lower()
    if normalized not in PROVIDER_SPECS:
        raise SystemExit(f"unknown provider: {provider_key}")
    spec = dict(PROVIDER_SPECS[normalized])
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
    args = parser.parse_args()
    payload = build_payload(args.provider, allow_fallback=bool(args.allow_fallback))
    path = write_payload(payload, Path(args.write_dir))
    print(path)
    return 0 if payload["verdict"] != "NOT_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
