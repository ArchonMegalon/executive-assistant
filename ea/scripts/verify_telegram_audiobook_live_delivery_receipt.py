from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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

from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint


ALLOWED_STATUSES = {"pass", "blocked"}


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _verify_source_state(receipt: dict[str, Any], issues: list[str]) -> None:
    if receipt.get("head_semantics") != "source_state":
        issues.append("head_semantics must describe source_state")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("source_state_fingerprint_semantics must describe the source worktree fingerprint")
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    recorded_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    current_head = resolve_source_state_head(ROOT)
    current_fingerprint = resolve_source_worktree_fingerprint(ROOT)
    if not recorded_head:
        issues.append("source_git_head missing")
    elif recorded_head != current_head and recorded_fingerprint != current_fingerprint:
        issues.append("source_git_head stale")
    if not recorded_fingerprint:
        issues.append("source_state_fingerprint missing")
    elif recorded_fingerprint != current_fingerprint:
        issues.append("source_state_fingerprint stale")


def verify(path: Path = DEFAULT_OUTPUT) -> list[str]:
    issues: list[str] = []
    receipt = _json(path)
    if not receipt:
        return [f"telegram audiobook live delivery receipt missing or invalid: {path}"]

    if receipt.get("contract_name") != CONTRACT_NAME:
        issues.append(f"contract_name must be {CONTRACT_NAME}")
    if receipt.get("generated_by") != "ea/scripts/materialize_telegram_audiobook_live_delivery_receipt.py":
        issues.append("generated_by must point at the Telegram live delivery materializer")
    _verify_source_state(receipt, issues)

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
    operator_action_packet = dict(receipt.get("operator_action_packet") or {})
    if not operator_action_packet:
        issues.append("operator_action_packet must be present")
    else:
        if operator_action_packet.get("raw_voice_ids_exposed") is not False:
            issues.append("operator_action_packet.raw_voice_ids_exposed must remain false")
        if operator_action_packet.get("callback_tokens_exposed") is not False:
            issues.append("operator_action_packet.callback_tokens_exposed must remain false")
        if bool(operator_action_packet.get("user_action_required")):
            if not str(operator_action_packet.get("operator_action") or "").strip():
                issues.append("action-required operator_action_packet must include operator_action")
            if not str(operator_action_packet.get("instruction") or "").strip():
                issues.append("action-required operator_action_packet must include instruction")
            if int(operator_action_packet.get("candidate_count") or 0) <= 0:
                issues.append("action-required operator_action_packet must include candidate_count")
            labels = list(operator_action_packet.get("candidate_labels") or [])
            if not labels:
                issues.append("action-required operator_action_packet must include candidate_labels")
            if operator_action_packet.get("next_action_href") != next_action_href:
                issues.append("operator_action_packet next_action_href must match receipt next_action_href")
            if operator_action_packet.get("next_action_label") != next_action_label:
                issues.append("operator_action_packet next_action_label must match receipt next_action_label")
            if str(operator_action_packet.get("next_action_method") or "").strip().lower() != next_action_method:
                issues.append("operator_action_packet next_action_method must match receipt next_action_method")
    duplicate_suppression = dict(receipt.get("duplicate_suppression") or {})
    if not duplicate_suppression:
        issues.append("duplicate_suppression must be present")
    else:
        if duplicate_suppression.get("action_required_only") is not True:
            issues.append("duplicate_suppression.action_required_only must be true")
        if duplicate_suppression.get("only_current_jobs_can_require_user_action") is not True:
            issues.append("duplicate_suppression.only_current_jobs_can_require_user_action must be true")
        if duplicate_suppression.get("raw_voice_ids_exposed") is not False:
            issues.append("duplicate_suppression.raw_voice_ids_exposed must remain false")
        if duplicate_suppression.get("callback_tokens_exposed") is not False:
            issues.append("duplicate_suppression.callback_tokens_exposed must remain false")
        if int(duplicate_suppression.get("duplicate_active_pending_source_key_count") or 0) != 0:
            issues.append("duplicate_suppression must not leave duplicate active pending source keys")
        if int(duplicate_suppression.get("active_pending_voice_job_count") or 0) != int(
            receipt.get("pending_user_selected_voice_job_count") or 0
        ):
            issues.append("duplicate_suppression active pending count must match pending_user_selected_voice_job_count")
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
        if "audiobook_voice_choice_pending" in failed_codes or "explicit_replacement_voice_choice_pending" in failed_codes:
            if operator_action_packet.get("user_action_required") is not True:
                issues.append("voice-choice blocked status must set operator_action_packet.user_action_required=true")

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
