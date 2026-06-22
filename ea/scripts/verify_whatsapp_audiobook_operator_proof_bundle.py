from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECEIPT = ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_operator_proof_bundle.generated.json"
ALLOWED_STATUSES = {"pass", "blocked", "waiting_voice_choice", "waiting_provider_throttle", "waiting_for_live_epub"}


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def verify(path: Path = DEFAULT_RECEIPT) -> list[str]:
    issues: list[str] = []
    receipt = _json(path)
    if not receipt:
        return [f"whatsapp audiobook operator proof bundle missing or invalid: {path}"]

    if receipt.get("contract_name") != "ea.whatsapp_audiobook_operator_proof_bundle.v1":
        issues.append("contract_name must be ea.whatsapp_audiobook_operator_proof_bundle.v1")
    if receipt.get("generated_by") != "ea/scripts/materialize_whatsapp_audiobook_operator_proof_bundle.py":
        issues.append("generated_by must point at the WhatsApp operator proof bundle materializer")

    status = str(receipt.get("status") or "").strip()
    if status not in ALLOWED_STATUSES:
        issues.append("status must stay within the allowed WhatsApp operator-bundle states")

    recommended_action = str(receipt.get("recommended_action") or "").strip()
    if not recommended_action:
        issues.append("recommended_action must be present")

    checks = dict(receipt.get("checks") or {})
    required_checks = {
        "local_epub_intake_proof_passed",
        "historical_public_share_playback_proven",
        "live_action_processor_ready",
        "live_action_processor_ran",
        "live_action_processor_no_runtime_errors",
        "live_processor_runtime_alignment_evaluated",
        "live_sidecar_inbox_accessible",
        "live_receipt_materialized",
        "live_receipt_has_explicit_next_action",
        "live_public_share_playback_verified_or_not_required",
        "live_voice_selection_text_fallback_ready_or_not_required",
        "live_voice_selection_shadow_passed_or_not_required",
    }
    waiting_core_checks = {
        "local_epub_intake_proof_passed",
        "live_action_processor_ready",
        "live_action_processor_ran",
        "live_action_processor_no_runtime_errors",
        "live_processor_runtime_alignment_evaluated",
        "live_sidecar_inbox_accessible",
        "live_receipt_materialized",
        "live_receipt_has_explicit_next_action",
        "live_voice_selection_text_fallback_ready_or_not_required",
        "live_voice_selection_shadow_passed_or_not_required",
    }
    missing_checks = sorted(required_checks - set(checks))
    if missing_checks:
        issues.append(f"missing required checks: {', '.join(missing_checks)}")

    if status == "waiting_for_live_epub":
        if not all(bool(checks.get(key)) for key in waiting_core_checks):
            issues.append("waiting_for_live_epub requires all core checks to pass")
        live_delivery = dict(receipt.get("live_delivery") or {})
        if str(live_delivery.get("status") or "").strip() != "waiting_for_live_epub":
            issues.append("waiting_for_live_epub bundle requires matching live_delivery.status")
        if int(live_delivery.get("candidate_count") or 0) != 0:
            issues.append("waiting_for_live_epub bundle requires live_delivery.candidate_count=0")
        if not bool(live_delivery.get("historical_live_path_proven")):
            issues.append("waiting_for_live_epub bundle requires historical_live_path_proven=true")

    if status == "pass":
        live_delivery = dict(receipt.get("live_delivery") or {})
        if str(live_delivery.get("status") or "").strip() != "pass":
            issues.append("pass bundle requires live_delivery.status=pass")
        if not bool(live_delivery.get("live_delivery_claim_allowed")):
            issues.append("pass bundle requires live_delivery_claim_allowed=true")
        if not bool(checks.get("live_public_share_playback_verified_or_not_required")):
            issues.append("pass bundle requires live public-share playback verification")

    runtime_alignment = dict(receipt.get("runtime_alignment") or {})
    if not bool(runtime_alignment.get("evaluated")):
        issues.append("runtime_alignment.evaluated must remain true")
    if runtime_alignment.get("secret_values_exposed") is not False:
        issues.append("runtime_alignment.secret_values_exposed must remain false")

    live_readiness = dict(receipt.get("live_readiness") or {})
    if "ready" not in live_readiness:
        issues.append("live_readiness.ready missing")
    live_processor = dict(receipt.get("live_processor") or {})
    if "status" not in live_processor:
        issues.append("live_processor.status missing")
    live_delivery = dict(receipt.get("live_delivery") or {})
    if "status" not in live_delivery:
        issues.append("live_delivery.status missing")
    public_share_playback = dict(receipt.get("public_share_playback") or {})
    if "status" not in public_share_playback:
        issues.append("public_share_playback.status missing")

    return issues


def main() -> int:
    import sys

    if any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python ea/scripts/verify_whatsapp_audiobook_operator_proof_bundle.py [options]\n\n"
            "Verify the WhatsApp audiobook operator proof bundle."
        )
        return 0
    parser = argparse.ArgumentParser(description="Verify the WhatsApp audiobook operator proof bundle.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    issues = verify(args.receipt)
    payload = {"status": "pass" if not issues else "blocked", "issues": issues}
    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
