from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECEIPT = ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_live_delivery.generated.json"
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
        return [f"whatsapp audiobook live delivery receipt missing or invalid: {path}"]

    if receipt.get("contract_name") != "ea.whatsapp_audiobook_live_delivery_receipt.v1":
        issues.append("contract_name must be ea.whatsapp_audiobook_live_delivery_receipt.v1")
    if receipt.get("generated_by") != "ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py":
        issues.append("generated_by must point at the WhatsApp live delivery materializer")

    status = str(receipt.get("status") or "").strip()
    if status not in ALLOWED_STATUSES:
        issues.append("status must stay within the allowed WhatsApp live-delivery states")

    claim_allowed = bool(receipt.get("live_delivery_claim_allowed"))
    failed_codes = [str(item).strip() for item in list(receipt.get("failed_codes") or []) if str(item).strip()]
    next_action = str(receipt.get("next_action") or "").strip()
    runtime = dict(receipt.get("runtime_readiness") or {})
    historical = dict(receipt.get("historical_evidence") or {})

    if status == "pass":
        if not claim_allowed:
            issues.append("pass status requires live_delivery_claim_allowed=true")
        if failed_codes:
            issues.append("pass status must not carry failed_codes")
    else:
        if claim_allowed:
            issues.append("non-pass status must not claim live delivery")
        if not failed_codes:
            issues.append("non-pass status must carry failed_codes")
        if not next_action:
            issues.append("non-pass status must include next_action")

    if status == "waiting_for_live_epub":
        if int(receipt.get("candidate_count") or 0) != 0:
            issues.append("waiting_for_live_epub requires candidate_count=0")
        if not bool(runtime.get("ready")):
            issues.append("waiting_for_live_epub requires runtime_readiness.ready=true")
        if not bool(historical.get("historical_live_path_proven")):
            issues.append("waiting_for_live_epub requires historical_live_path_proven=true")

    if status == "waiting_voice_choice":
        if "choose_whatsapp_audiobook_voice_sample" not in next_action:
            issues.append("waiting_voice_choice must keep the explicit voice-choice next action")
        if "voice_selection_text_fallback_ready" not in receipt:
            issues.append("waiting_voice_choice must expose voice_selection_text_fallback_ready")
        elif not isinstance(receipt.get("voice_selection_text_fallback_ready"), bool):
            issues.append("voice_selection_text_fallback_ready must be a boolean")
        pending = [
            row
            for row in list(receipt.get("pending_user_selected_voice_jobs") or [])
            if isinstance(row, dict) and (row.get("voice_selection_waiting") or row.get("replacement_choice_pending"))
        ]
        if pending and not all("voice_selection_text_fallback_ready" in row for row in pending):
            issues.append("waiting voice-choice pending jobs must expose voice_selection_text_fallback_ready")

    if status == "waiting_provider_throttle" and "wait_until_provider_retry_after" not in next_action:
        issues.append("waiting_provider_throttle must keep the retry-after next action")

    if not isinstance(receipt.get("stage_summary"), dict):
        issues.append("stage_summary must be an object")
    if not isinstance(receipt.get("historical_evidence"), dict):
        issues.append("historical_evidence must be an object")
    if not isinstance(receipt.get("runtime_readiness"), dict):
        issues.append("runtime_readiness must be an object")

    if receipt.get("goal_completion_claim_allowed") is not False:
        issues.append("goal_completion_claim_allowed must remain false")

    return issues


def main() -> int:
    import sys

    if any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python ea/scripts/verify_whatsapp_audiobook_live_delivery_receipt.py [options]\n\n"
            "Verify the WhatsApp audiobook live delivery receipt."
        )
        return 0
    parser = argparse.ArgumentParser(description="Verify the WhatsApp audiobook live delivery receipt.")
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
