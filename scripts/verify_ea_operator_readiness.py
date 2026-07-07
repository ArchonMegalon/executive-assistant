#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts import ea_live_ops
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import ea_live_ops  # type: ignore
    from source_state_head import resolve_source_state_head  # type: ignore
    from source_state_head import resolve_source_worktree_fingerprint  # type: ignore


DEFAULT_RECEIPT = ROOT / ".codex-studio/published/ea_operator_readiness.generated.json"
CONTRACT_NAME = "ea.operator_readiness.v1"
KNOWN_STATUSES = {"ready", "ready_with_actions", "probe_failed"}
FORBIDDEN_DETAIL_KEYS = {
    "pair_url",
    "qr_svg_url",
    "qr_svg_ref",
    "raw_qr",
    "raw_bot_token",
    "raw_chat_id",
    "table_id",
    "route_report",
    "stage_packet",
    "gcloud_probe",
    "telegram_delivery",
}


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _fresh_enough(receipt: dict[str, Any], *, root: Path) -> list[str]:
    issues: list[str] = []
    current_head = resolve_source_state_head(root)
    current_fingerprint = resolve_source_worktree_fingerprint(root)
    source_head = str(receipt.get("source_git_head") or "").strip()
    source_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    if receipt.get("head_semantics") != "source_state":
        issues.append("head_semantics must be source_state")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("source_state_fingerprint_semantics mismatch")
    if not source_head:
        issues.append("source_git_head missing")
    elif source_head != current_head and source_fingerprint != current_fingerprint:
        issues.append("receipt is stale relative to current source HEAD")
    if not source_fingerprint:
        issues.append("source_state_fingerprint missing")
    elif source_fingerprint != current_fingerprint:
        issues.append("receipt is stale relative to current source fingerprint")
    return issues


def _validate_component(component: dict[str, Any], issues: list[str]) -> None:
    key = str(component.get("key") or "").strip()
    if not key:
        issues.append("component key missing")
        return
    label = str(component.get("label") or "").strip()
    if not label:
        issues.append(f"{key} label missing")
    status = str(component.get("status") or "").strip()
    if not status:
        issues.append(f"{key} status missing")
    if not str(component.get("observed_at") or "").strip():
        issues.append(f"{key} observed_at missing")
    if not str(component.get("source") or "").strip():
        issues.append(f"{key} source missing")
    details = dict(component.get("details") or {})
    allowed_detail_keys = ea_live_ops._operator_readiness_public_detail_fields(key)
    unexpected_detail_keys = sorted(set(details) - allowed_detail_keys)
    if unexpected_detail_keys:
        issues.append(f"{key} unexpected detail keys: {','.join(unexpected_detail_keys)}")
    for detail_key in sorted(details):
        if detail_key.startswith("raw_"):
            issues.append(f"{key} must not expose raw detail key: {detail_key}")
        if detail_key in FORBIDDEN_DETAIL_KEYS:
            issues.append(f"{key} must not expose forbidden detail key: {detail_key}")


def verify_receipt_for_test(receipt: dict[str, Any], *, root: Path = ROOT) -> list[str]:
    issues: list[str] = []
    if not receipt:
        return ["operator readiness receipt missing or invalid"]
    if receipt.get("contract_name") != CONTRACT_NAME:
        issues.append("contract_name mismatch")
    if receipt.get("generated_by") != "scripts/materialize_ea_operator_readiness.py":
        issues.append("generated_by mismatch")
    issues.extend(_fresh_enough(receipt, root=root))

    status = str(receipt.get("status") or "").strip()
    if status not in KNOWN_STATUSES:
        issues.append(f"status must be one of {sorted(KNOWN_STATUSES)}")
    if receipt.get("claim_boundary") != "control_plane_snapshot_only_not_live_delivery_or_pairing_completion":
        issues.append("claim_boundary mismatch")
    if not str(receipt.get("claim") or "").strip():
        issues.append("claim missing")
    if receipt.get("live_delivery_claim_allowed") is not False:
        issues.append("live_delivery_claim_allowed must be false")
    if receipt.get("live_pairing_claim_allowed") is not False:
        issues.append("live_pairing_claim_allowed must be false")
    if receipt.get("published_qr_artifact_claim_allowed") is not False:
        issues.append("published_qr_artifact_claim_allowed must be false")
    if receipt.get("pairing_probe_mode") not in {"passive", "active"}:
        issues.append("pairing_probe_mode must be passive or active")
    if bool(receipt.get("include_pairing")) != (receipt.get("pairing_probe_mode") == "active"):
        issues.append("include_pairing must match pairing_probe_mode")
    include_sonarr = bool(receipt.get("include_sonarr"))
    sonarr_target_series_id = int(receipt.get("sonarr_target_series_id") or 0)
    sonarr_target_series_title = str(receipt.get("sonarr_target_series_title") or "").strip()
    sonarr_target_season_number = int(receipt.get("sonarr_target_season_number") or 0)
    expected_include_sonarr = sonarr_target_season_number > 0 and (sonarr_target_series_id > 0 or bool(sonarr_target_series_title))
    if include_sonarr != expected_include_sonarr:
        issues.append("include_sonarr must match the configured Sonarr target fields")
    if receipt.get("source") != "ea_live_ops.aggregate":
        issues.append("source must remain ea_live_ops.aggregate")
    if not str(receipt.get("observed_at") or "").strip():
        issues.append("observed_at missing")

    privacy = dict(receipt.get("privacy") or {})
    for key in (
        "raw_component_payload_exposed",
        "raw_delivery_token_exposed",
        "raw_qr_artifact_exposed",
        "raw_chat_ref_exposed",
    ):
        if privacy.get(key) is not False:
            issues.append(f"privacy.{key} must be false")

    components = [dict(item) for item in list(receipt.get("components") or []) if isinstance(item, dict)]
    component_keys = [str(item.get("key") or "").strip() for item in components if str(item.get("key") or "").strip()]
    if int(receipt.get("component_count") or 0) != len(components):
        issues.append("component_count mismatch")
    if list(receipt.get("component_keys") or []) != component_keys:
        issues.append("component_keys must preserve component order")
    if len(component_keys) != len(set(component_keys)):
        issues.append("component keys must be unique")
    if not bool(receipt.get("include_pairing")) and any(
        key in {"whatsapp_pairing", "mymedia_pairing_telegram"} for key in component_keys
    ):
        issues.append("passive operator readiness receipt must not include pairing recovery components")
    if include_sonarr and "sonarr_tv_season" not in component_keys:
        issues.append("include_sonarr receipt must include the sonarr_tv_season component")
    if not include_sonarr and "sonarr_tv_season" in component_keys:
        issues.append("receipt must not include sonarr_tv_season when include_sonarr is false")

    for component in components:
        _validate_component(component, issues)

    blocked_component_keys = ea_live_ops._operator_readiness_blocked_component_keys(components)
    probe_failed_component_keys = ea_live_ops._operator_readiness_probe_failed_component_keys(components)
    attention_component_keys = ea_live_ops._operator_readiness_attention_component_keys(components)
    supplemental_blocked_component_keys = ea_live_ops._operator_readiness_supplemental_blocked_component_keys(components)
    supplemental_probe_failed_component_keys = ea_live_ops._operator_readiness_supplemental_probe_failed_component_keys(components)
    supplemental_attention_component_keys = ea_live_ops._operator_readiness_supplemental_attention_component_keys(components)
    ready_component_keys = [
        str(component.get("key") or "").strip()
        for component in components
        if bool(component.get("ready"))
    ]
    if list(receipt.get("blocked_component_keys") or []) != blocked_component_keys:
        issues.append("blocked_component_keys mismatch")
    if list(receipt.get("probe_failed_component_keys") or []) != probe_failed_component_keys:
        issues.append("probe_failed_component_keys mismatch")
    if list(receipt.get("attention_component_keys") or []) != attention_component_keys:
        issues.append("attention_component_keys mismatch")
    if list(receipt.get("supplemental_blocked_component_keys") or []) != supplemental_blocked_component_keys:
        issues.append("supplemental_blocked_component_keys mismatch")
    if list(receipt.get("supplemental_probe_failed_component_keys") or []) != supplemental_probe_failed_component_keys:
        issues.append("supplemental_probe_failed_component_keys mismatch")
    if list(receipt.get("supplemental_attention_component_keys") or []) != supplemental_attention_component_keys:
        issues.append("supplemental_attention_component_keys mismatch")
    if list(receipt.get("ready_component_keys") or []) != ready_component_keys:
        issues.append("ready_component_keys mismatch")
    if int(receipt.get("blocked_count") or 0) != len(blocked_component_keys):
        issues.append("blocked_count mismatch")
    if int(receipt.get("probe_failed_count") or 0) != len(probe_failed_component_keys):
        issues.append("probe_failed_count mismatch")
    if int(receipt.get("attention_required_count") or 0) != len(attention_component_keys):
        issues.append("attention_required_count mismatch")
    if int(receipt.get("supplemental_blocked_count") or 0) != len(supplemental_blocked_component_keys):
        issues.append("supplemental_blocked_count mismatch")
    if int(receipt.get("supplemental_probe_failed_count") or 0) != len(supplemental_probe_failed_component_keys):
        issues.append("supplemental_probe_failed_count mismatch")
    if int(receipt.get("supplemental_attention_count") or 0) != len(supplemental_attention_component_keys):
        issues.append("supplemental_attention_count mismatch")

    expected_probe_ok = len(probe_failed_component_keys) == 0
    expected_ready = not attention_component_keys
    expected_status = "probe_failed" if probe_failed_component_keys else ("ready_with_actions" if attention_component_keys else "ready")
    if bool(receipt.get("probe_ok")) is not expected_probe_ok:
        issues.append("probe_ok mismatch")
    if bool(receipt.get("ready")) is not expected_ready:
        issues.append("ready mismatch")
    if status != expected_status:
        issues.append("status does not match component readiness")

    next_actions = [dict(item) for item in list(receipt.get("next_actions") or []) if isinstance(item, dict)]
    supplemental_next_actions = [dict(item) for item in list(receipt.get("supplemental_next_actions") or []) if isinstance(item, dict)]
    referenced_component_keys = {str(item.get("component_key") or "").strip() for item in next_actions}
    missing_component_refs = sorted(key for key in referenced_component_keys if key and key not in component_keys)
    if missing_component_refs:
        issues.append(f"next_actions reference unknown components: {','.join(missing_component_refs)}")
    supplemental_component_refs = {str(item.get("component_key") or "").strip() for item in supplemental_next_actions}
    missing_supplemental_refs = sorted(key for key in supplemental_component_refs if key and key not in component_keys)
    if missing_supplemental_refs:
        issues.append(f"supplemental_next_actions reference unknown components: {','.join(missing_supplemental_refs)}")
    if next_actions:
        first = next_actions[0]
        if str(receipt.get("next_action") or "").strip() != str(first.get("action") or "").strip():
            issues.append("next_action must match the first next_actions entry")
        if str(receipt.get("next_action_href") or "").strip() != str(first.get("href") or "").strip():
            issues.append("next_action_href must match the first next_actions entry")
        if str(receipt.get("next_action_label") or "").strip() != str(first.get("label") or "").strip():
            issues.append("next_action_label must match the first next_actions entry")
        if str(receipt.get("next_action_method") or "").strip() != str(first.get("method") or "").strip():
            issues.append("next_action_method must match the first next_actions entry")
    else:
        for key in ("next_action", "next_action_href", "next_action_label", "next_action_method"):
            if str(receipt.get(key) or "").strip():
                issues.append(f"{key} must be empty when next_actions is empty")

    expected_summary = ea_live_ops._operator_text_for_operator_readiness(
        {
            "status": receipt.get("status"),
            "ready": receipt.get("ready"),
            "components": components,
            "attention_required_count": receipt.get("attention_required_count"),
            "blocked_count": receipt.get("blocked_count"),
            "probe_failed_count": receipt.get("probe_failed_count"),
            "next_actions": next_actions,
            "supplemental_attention_count": receipt.get("supplemental_attention_count"),
            "supplemental_blocked_count": receipt.get("supplemental_blocked_count"),
            "supplemental_probe_failed_count": receipt.get("supplemental_probe_failed_count"),
            "supplemental_next_actions": supplemental_next_actions,
            "observed_at": receipt.get("observed_at"),
            "source": receipt.get("source"),
        }
    )
    if str(receipt.get("summary") or "").strip() != expected_summary:
        issues.append("summary must match operator readiness formatter output")

    return issues


def main(argv: list[str] | None = None) -> int:
    if argv is None and any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python scripts/verify_ea_operator_readiness.py [options]\n\n"
            "Verify the published aggregate EA operator readiness receipt."
        )
        return 0
    parser = argparse.ArgumentParser(description="Verify the published aggregate EA operator readiness receipt.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    issues = verify_receipt_for_test(_json(args.receipt))
    payload = {
        "contract_name": "ea.operator_readiness.verify.v1",
        "status": "pass" if not issues else "fail",
        "issues": issues,
    }
    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
