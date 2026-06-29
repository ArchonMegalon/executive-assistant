from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from materialize_telegram_audiobook_live_delivery_receipt import ACTION_METHOD
    from materialize_telegram_audiobook_live_delivery_receipt import CONTRACT_NAME
    from materialize_telegram_audiobook_live_delivery_receipt import DEFAULT_OUTPUT
    from materialize_telegram_audiobook_live_delivery_receipt import TELEGRAM_ACTION_SURFACES
except ModuleNotFoundError:  # pragma: no cover - package import path
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import ACTION_METHOD
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import CONTRACT_NAME
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import DEFAULT_OUTPUT
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import TELEGRAM_ACTION_SURFACES


ALLOWED_STATUSES = {"pass", "blocked"}


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def verify(path: Path = DEFAULT_OUTPUT) -> list[str]:
    issues: list[str] = []
    receipt = _json(path)
    if not receipt:
        return [f"telegram audiobook live delivery receipt missing or invalid: {path}"]

    if receipt.get("contract_name") != CONTRACT_NAME:
        issues.append(f"contract_name must be {CONTRACT_NAME}")
    if receipt.get("generated_by") != "ea/scripts/materialize_telegram_audiobook_live_delivery_receipt.py":
        issues.append("generated_by must point at the Telegram live delivery materializer")

    status = str(receipt.get("status") or "").strip()
    if status not in ALLOWED_STATUSES:
        issues.append("status must stay within the allowed Telegram live-delivery states")

    claim_allowed = bool(receipt.get("live_delivery_claim_allowed"))
    failed_codes = [str(item).strip() for item in list(receipt.get("failed_codes") or []) if str(item).strip()]
    next_action = str(receipt.get("next_action") or "").strip()
    next_action_href = str(receipt.get("next_action_href") or "").strip()
    next_action_label = str(receipt.get("next_action_label") or "").strip()
    next_action_method = str(receipt.get("next_action_method") or "").strip().lower()
    expected_surface = TELEGRAM_ACTION_SURFACES.get(next_action)
    if not next_action:
        issues.append("next_action must be present")
    elif expected_surface is None:
        issues.append("next_action must map to a known Telegram operator surface")
    else:
        expected_href, expected_label, expected_method = expected_surface
        if next_action_href != expected_href:
            issues.append("next_action_href must match the mapped Telegram operator surface")
        if next_action_label != expected_label:
            issues.append("next_action_label must match the mapped Telegram operator surface")
        if next_action_method != expected_method.lower():
            issues.append("next_action_method must match the mapped Telegram operator surface")
    if receipt.get("goal_completion_claim_allowed") is not False:
        issues.append("goal_completion_claim_allowed must remain false")
    privacy = dict(receipt.get("privacy") or {})
    for key in ("provider_secret_exposed", "audiobookshelf_token_exposed"):
        if privacy.get(key) is not False:
            issues.append(f"privacy.{key} must remain false")

    real_user_accepted = bool(receipt.get("real_user_playback_acceptance_verified"))
    machine_verified = bool(receipt.get("machine_playback_e2e_verified"))
    if status == "pass":
        if not claim_allowed:
            issues.append("pass status requires live_delivery_claim_allowed=true")
        if failed_codes:
            issues.append("pass status must not carry failed_codes")
        if not machine_verified:
            issues.append("pass status requires machine_playback_e2e_verified=true")
        if real_user_accepted:
            if next_action != "close_operator_loop":
                issues.append("accepted human playback must close the operator loop")
        else:
            if next_action != "capture_real_user_playback_acceptance_or_close_operator_loop":
                issues.append("machine-only pass must keep playback-acceptance capture as the next action")
    else:
        if claim_allowed:
            issues.append("blocked status must not claim live delivery")
        if not failed_codes:
            issues.append("blocked status must carry failed_codes")
        if next_action == "close_operator_loop":
            issues.append("blocked status cannot close the operator loop")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Telegram audiobook live delivery receipt.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_OUTPUT)
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
