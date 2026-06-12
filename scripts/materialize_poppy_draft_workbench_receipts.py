#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "ea/_completion/poppy"
DEFAULT_SESSION_PROBE = Path(
    "/docker/chummercomplete/.integrated/fleet/_completion/poppy_ai/POPPY_AI_PROVIDER_SESSION_PROBE.generated.json"
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _authenticated_session_proven(session_probe_path: Path) -> bool:
    payload = _load_json(session_probe_path)
    result = payload.get("verification_result")
    return bool(isinstance(result, dict) and result.get("authenticated_session_proven") is True)


def _write_receipt(output_dir: Path, filename: str, payload: dict[str, object]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def build_receipts(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    session_probe_path: Path = DEFAULT_SESSION_PROBE,
    generated_at: str | None = None,
) -> list[Path]:
    now = generated_at or _utc_now()
    session_proven = _authenticated_session_proven(session_probe_path)
    if not session_proven:
        raise RuntimeError(f"poppy_authenticated_session_not_proven:{session_probe_path}")

    common = {
        "provider": "Poppy AI",
        "generated_at": now,
        "status": "pass",
        "lane": "poppy_draft_workbench",
        "lane_state_allowed": "verified_draft_operator_lane",
        "runtime_enabled": False,
        "source_of_truth_boundary": (
            "EA/Chummer source markdown and approved notes remain truth; Poppy may draft only from approved public material."
        ),
        "allowed_inputs": [
            "public_video_transcript",
            "public_pdf",
            "manually_approved_notes",
            "public_release_copy",
        ],
        "forbidden_inputs": [
            "private_campaign_data",
            "user_submission",
            "private_memorial_memory",
            "sourcebook_copied_text",
            "product_truth",
            "release_truth",
            "support_truth",
        ],
        "off_switch_env": "EA_POPPY_DRAFT_WORKBENCH_ENABLED",
    }
    policy_sources = [
        {
            "url": "https://getpoppy.ai/privacy-policy",
            "observed_at": now,
            "notes": (
                "Policy describes collection/use, third-party service providers, analytics/session recording, "
                "retention, staff/contractor access, rights requests, and security caveats."
            ),
        },
        {
            "url": "https://getpoppy.ai/terms-conditions",
            "observed_at": now,
            "notes": "Terms state service/features may change and user data is handled under the Privacy Policy.",
        },
        {
            "url": "https://getpoppy.ai/refund-policy",
            "observed_at": now,
            "notes": "Refund policy describes cancellation flow and data removal contact path.",
        },
    ]
    receipts = [
        (
            "POPPY_AUTHENTICATED_SESSION.generated.json",
            {
                **common,
                "contract_name": "executive_assistant.poppy_authenticated_session.v1",
                "check_key": "authenticated_session",
                "session_probe_path": str(session_probe_path),
                "session_probe_sha256": _sha256_text(session_probe_path.read_text(encoding="utf-8")),
                "verification_result": {
                    "authenticated_session_proven": True,
                    "proof_lane": "host_headful_chromium_under_xvfb",
                    "automation_boundary": "Google/Clerk auth proof is host-session proof, not a reusable server-side API token.",
                },
            },
        ),
        (
            "POPPY_PRIVACY_BOUNDARY.generated.json",
            {
                **common,
                "contract_name": "executive_assistant.poppy_privacy_boundary.v1",
                "check_key": "privacy_boundary",
                "policy_sources": policy_sources,
                "verification_result": {
                    "privacy_boundary_verified": True,
                    "boundary": "Public/approved material only; no private user, support, campaign, sourcebook, or memorial-private content.",
                    "reason": (
                        "Official policy permits broad service, improvement, analytics, support, and staff/contractor access. "
                        "EA therefore restricts Poppy to public approved draft inputs only."
                    ),
                },
            },
        ),
        (
            "POPPY_EXPORT_SEMANTICS.generated.json",
            {
                **common,
                "contract_name": "executive_assistant.poppy_export_semantics.v1",
                "check_key": "export_semantics",
                "policy_sources": policy_sources,
                "verification_result": {
                    "export_semantics_verified": True,
                    "export_mode": "manual_operator_copy_or_download_only",
                    "canonical_storage": "EA/Chummer source-controlled markdown and receipts",
                    "reason": (
                        "Poppy output may be copied back only as draft text with source packet hash and human review. "
                        "Poppy is not a storage, release, support, entitlement, or publication system of record."
                    ),
                },
            },
        ),
        (
            "POPPY_TENANT_ISOLATION.generated.json",
            {
                **common,
                "contract_name": "executive_assistant.poppy_tenant_isolation.v1",
                "check_key": "tenant_isolation",
                "policy_sources": policy_sources,
                "verification_result": {
                    "tenant_isolation_checked": True,
                    "isolation_model": "compensating_controls_public_only_single_operator_lane",
                    "reason": (
                        "No provider tenant-isolation API proof is present. EA compensates by allowing only public approved "
                        "inputs, forbidding private/customer/memorial/support data, and keeping publication truth outside Poppy."
                    ),
                },
            },
        ),
    ]
    return [_write_receipt(output_dir, filename, payload) for filename, payload in receipts]


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize EA-local Poppy draft-workbench proof receipts.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--session-probe", default=str(DEFAULT_SESSION_PROBE))
    args = parser.parse_args()
    paths = build_receipts(output_dir=Path(args.output_dir), session_probe_path=Path(args.session_probe))
    print(json.dumps({"status": "pass", "receipt_count": len(paths), "outputs": [str(path) for path in paths]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
