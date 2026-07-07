#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
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


DEFAULT_OUTPUT = ROOT / ".codex-studio/published/ea_operator_readiness.generated.json"
CONTRACT_NAME = "ea.operator_readiness.v1"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_state() -> dict[str, str]:
    return {
        "source_git_head": resolve_source_state_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _default_probe_args() -> argparse.Namespace:
    return argparse.Namespace(
        database_url=ea_live_ops._env("DATABASE_URL"),
        binding_json=ea_live_ops._env("EA_WHATSAPP_WEB_READINESS_BINDING_JSON"),
        binding_id=ea_live_ops._env("EA_WHATSAPP_WEB_DEFAULT_BINDING_ID", "ea-whatsapp-web-session"),
        principal_id=ea_live_ops._default_whatsapp_principal_id(),
        session_api_base_url=ea_live_ops._env(
            "EA_WHATSAPP_WEB_SESSION_API_BASE_URL",
            ea_live_ops.DEFAULT_SESSION_API_BASE_URL,
        ),
        session_ref=ea_live_ops._env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF"),
        timeout_seconds=None,
        dry_run=False,
    )


def build_receipt(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    generated_at: str = "",
    telegram_principal_id: str = "",
    proactive_principal_id: str = "",
    compose_file: str = "",
    runtime_service: str = "",
    receipt_path: str = "",
    timeout_seconds: float = 30.0,
    include_proactive: bool = True,
    include_pairing: bool = True,
    sonarr_series_id: int | str | None = 0,
    sonarr_series_title: str = "",
    sonarr_season_number: int | str | None = 0,
    args: argparse.Namespace | None = None,
) -> dict[str, Any]:
    sonarr_target = ea_live_ops._operator_readiness_sonarr_target(
        series_id=sonarr_series_id,
        series_title=sonarr_series_title,
        season_number=sonarr_season_number,
    )
    probe = ea_live_ops.probe_operator_readiness(
        args=args or _default_probe_args(),
        telegram_principal_id=str(telegram_principal_id or ea_live_ops._default_proactive_principal_id()).strip(),
        proactive_principal_id=str(proactive_principal_id or ea_live_ops._default_proactive_principal_id()).strip(),
        compose_file=str(
            compose_file
            or ea_live_ops._env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(ea_live_ops.DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))
        ).strip(),
        runtime_service=str(
            runtime_service
            or ea_live_ops._env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", ea_live_ops.DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)
        ).strip(),
        receipt_path=str(receipt_path or ea_live_ops._env("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH")).strip(),
        timeout_seconds=max(float(timeout_seconds or 30.0), 1.0),
        include_proactive=bool(include_proactive),
        include_pairing=bool(include_pairing),
        sonarr_series_id=int(sonarr_target.get("series_id") or 0),
        sonarr_series_title=str(sonarr_target.get("series_title") or "").strip(),
        sonarr_season_number=int(sonarr_target.get("season_number") or 0),
        output_format="json",
    )
    probe = ea_live_ops._operator_readiness_public_report(dict(probe))
    components = [dict(item) for item in list(probe.get("components") or []) if isinstance(item, dict)]
    next_actions = ea_live_ops._operator_readiness_next_actions(components)
    component_keys = [str(item.get("key") or "").strip() for item in components if str(item.get("key") or "").strip()]
    ready_component_keys = [str(item.get("key") or "").strip() for item in components if bool(item.get("ready"))]
    attention_component_keys = ea_live_ops._operator_readiness_attention_component_keys(components)
    blocked_component_keys = ea_live_ops._operator_readiness_blocked_component_keys(components)
    probe_failed_component_keys = ea_live_ops._operator_readiness_probe_failed_component_keys(components)
    steering_component_keys = [
        str(item.get("key") or "").strip()
        for item in ea_live_ops._operator_readiness_steering_components(components)
        if str(item.get("key") or "").strip()
    ]
    supplemental_attention_component_keys = ea_live_ops._operator_readiness_supplemental_attention_component_keys(components)
    supplemental_blocked_component_keys = ea_live_ops._operator_readiness_supplemental_blocked_component_keys(components)
    supplemental_probe_failed_component_keys = ea_live_ops._operator_readiness_supplemental_probe_failed_component_keys(components)
    supplemental_next_actions = ea_live_ops._operator_readiness_supplemental_next_actions(components)
    derived_probe_ok = len(probe_failed_component_keys) == 0
    derived_ready = len(attention_component_keys) == 0
    derived_status = "probe_failed" if not derived_probe_ok else ("ready_with_actions" if not derived_ready else "ready")
    first_action = dict(next_actions[0]) if next_actions else {}
    receipt: dict[str, Any] = {
        "contract_name": CONTRACT_NAME,
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_ea_operator_readiness.py",
        **_source_state(),
        "output_path": str(output_path),
        "status": derived_status,
        "probe_ok": derived_probe_ok,
        "ready": derived_ready,
        "claim": (
            "This receipt proves only a no-secret aggregate snapshot of EA operator readiness across the current "
            "runtime lanes at the observed timestamp. It does not prove any later live delivery, pairing, playback, "
            "or operator remediation outcome."
        ),
        "claim_boundary": (
            "control_plane_snapshot_only_not_live_delivery_or_pairing_completion"
        ),
        "live_delivery_claim_allowed": False,
        "live_pairing_claim_allowed": False,
        "published_qr_artifact_claim_allowed": False,
        "pairing_probe_mode": "active" if include_pairing else "passive",
        "include_proactive": bool(include_proactive),
        "include_pairing": bool(include_pairing),
        "include_sonarr": bool(sonarr_target.get("enabled")),
        "sonarr_target_series_id": int(sonarr_target.get("series_id") or 0),
        "sonarr_target_series_title": str(sonarr_target.get("series_title") or "").strip(),
        "sonarr_target_season_number": int(sonarr_target.get("season_number") or 0),
        "component_count": len(components),
        "component_keys": component_keys,
        "steering_component_keys": steering_component_keys,
        "ready_component_keys": ready_component_keys,
        "attention_component_keys": attention_component_keys,
        "blocked_component_keys": blocked_component_keys,
        "probe_failed_component_keys": probe_failed_component_keys,
        "attention_required_count": len(attention_component_keys),
        "blocked_count": len(blocked_component_keys),
        "probe_failed_count": len(probe_failed_component_keys),
        "supplemental_attention_component_keys": supplemental_attention_component_keys,
        "supplemental_blocked_component_keys": supplemental_blocked_component_keys,
        "supplemental_probe_failed_component_keys": supplemental_probe_failed_component_keys,
        "supplemental_attention_count": len(supplemental_attention_component_keys),
        "supplemental_blocked_count": len(supplemental_blocked_component_keys),
        "supplemental_probe_failed_count": len(supplemental_probe_failed_component_keys),
        "supplemental_next_actions": supplemental_next_actions,
        "next_action": str(first_action.get("action") or "").strip(),
        "next_action_href": str(first_action.get("href") or "").strip(),
        "next_action_label": str(first_action.get("label") or "").strip(),
        "next_action_method": str(first_action.get("method") or "").strip(),
        "summary": ea_live_ops._operator_text_for_operator_readiness(
            {
                "status": derived_status,
                "ready": derived_ready,
                "components": components,
                "attention_required_count": len(attention_component_keys),
                "blocked_count": len(blocked_component_keys),
                "probe_failed_count": len(probe_failed_component_keys),
                "next_actions": next_actions,
                "supplemental_attention_count": len(supplemental_attention_component_keys),
                "supplemental_blocked_count": len(supplemental_blocked_component_keys),
                "supplemental_probe_failed_count": len(supplemental_probe_failed_component_keys),
                "supplemental_next_actions": supplemental_next_actions,
                "observed_at": probe.get("observed_at"),
                "source": probe.get("source"),
            }
        ),
        "observed_at": str(probe.get("observed_at") or "").strip(),
        "source": str(probe.get("source") or "").strip(),
        "privacy": {
            "raw_component_payload_exposed": False,
            "raw_delivery_token_exposed": False,
            "raw_qr_artifact_exposed": False,
            "raw_chat_ref_exposed": False,
        },
        "rules": [
            "A ready aggregate receipt does not prove a live delivery, live pairing, or end-user playback succeeded.",
            "Current runtime config gaps take precedence over stale linked receipt blockers; linked receipt state may appear only as context.",
            "Passive operator readiness receipts must not require QR generation or live pairing handoff artifacts.",
            "Each component remains authoritative only for its own lane; this aggregate is control-plane synthesis, not canonical product truth.",
        ],
        "components": components,
        "next_actions": next_actions,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    if argv is None and any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python scripts/materialize_ea_operator_readiness.py [options]\n\n"
            "Materialize the no-secret aggregate EA operator readiness receipt."
        )
        raise SystemExit(0)
    parser = argparse.ArgumentParser(description="Materialize the no-secret aggregate EA operator readiness receipt.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--telegram-principal-id", default=ea_live_ops._default_proactive_principal_id())
    parser.add_argument("--proactive-principal-id", default=ea_live_ops._default_proactive_principal_id())
    parser.add_argument(
        "--compose-file",
        default=ea_live_ops._env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(ea_live_ops.DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)),
    )
    parser.add_argument(
        "--runtime-service",
        default=ea_live_ops._env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", ea_live_ops.DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE),
    )
    parser.add_argument("--receipt-path", default=ea_live_ops._env("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH"))
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--no-proactive", dest="include_proactive", action="store_false", default=True)
    parser.add_argument("--include-pairing", dest="include_pairing", action="store_true", default=True)
    parser.add_argument("--no-pairing", dest="include_pairing", action="store_false")
    parser.add_argument(
        "--sonarr-series-id",
        type=int,
        default=ea_live_ops._operator_readiness_int_value(ea_live_ops._env("EA_OPERATOR_READINESS_SONARR_SERIES_ID", "0"), default=0),
    )
    parser.add_argument("--sonarr-series-title", default=ea_live_ops._env("EA_OPERATOR_READINESS_SONARR_SERIES_TITLE", ""))
    parser.add_argument(
        "--sonarr-season-number",
        type=int,
        default=ea_live_ops._operator_readiness_int_value(ea_live_ops._env("EA_OPERATOR_READINESS_SONARR_SEASON_NUMBER", "0"), default=0),
    )
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    receipt = build_receipt(
        output_path=args.output,
        generated_at=args.generated_at,
        telegram_principal_id=args.telegram_principal_id,
        proactive_principal_id=args.proactive_principal_id,
        compose_file=args.compose_file,
        runtime_service=args.runtime_service,
        receipt_path=args.receipt_path,
        timeout_seconds=args.timeout_seconds,
        include_proactive=args.include_proactive,
        include_pairing=args.include_pairing,
        sonarr_series_id=args.sonarr_series_id,
        sonarr_series_title=args.sonarr_series_title,
        sonarr_season_number=args.sonarr_season_number,
    )
    print(json.dumps(receipt, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
