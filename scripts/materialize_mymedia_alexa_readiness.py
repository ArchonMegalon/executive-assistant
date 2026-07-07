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

DEFAULT_OUTPUT = ROOT / ".codex-studio/published/mymedia_alexa_readiness.generated.json"
CONTRACT_NAME = "ea.mymedia_alexa_readiness.v1"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_state() -> dict[str, str]:
    return {
        "source_git_head": resolve_source_state_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _public_href(value: Any) -> str:
    return ea_live_ops._operator_readiness_public_href(value)


def _public_source_ref(value: Any) -> str:
    return ea_live_ops._operator_readiness_public_source_ref(value)


def _public_probe(report: dict[str, Any]) -> dict[str, Any]:
    public = dict(report)
    public["next_action_href"] = _public_href(report.get("next_action_href"))
    public["source"] = _public_source_ref(report.get("source"))
    public["public_surface_next_action_href"] = _public_href(report.get("public_surface_next_action_href"))
    public["public_surface_source"] = _public_source_ref(report.get("public_surface_source"))
    return public


def _public_telegram_delivery(delivery: dict[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {
        "sent": bool(delivery.get("sent")),
        "reason": str(delivery.get("reason") or "").strip(),
        "delivery_transport": str(delivery.get("delivery_transport") or "").strip(),
        "observed_at": str(delivery.get("observed_at") or "").strip(),
        "source": _public_source_ref(delivery.get("source")),
    }
    if "ready" in delivery:
        public["ready"] = bool(delivery.get("ready"))
    if "readiness_probe_ok" in delivery:
        public["readiness_probe_ok"] = bool(delivery.get("readiness_probe_ok"))
    if "readiness_status" in delivery:
        public["readiness_status"] = str(delivery.get("readiness_status") or "").strip()
    if "readiness_reason" in delivery:
        public["readiness_reason"] = str(delivery.get("readiness_reason") or "").strip()
    if "principal_id" in delivery:
        public["principal_id_present"] = bool(str(delivery.get("principal_id") or "").strip())
    if "binding_id" in delivery:
        public["binding_id_present"] = bool(str(delivery.get("binding_id") or "").strip())
    if "next_action" in delivery:
        public["next_action"] = str(delivery.get("next_action") or "").strip()
    if "next_action_href" in delivery:
        public["next_action_href"] = _public_href(delivery.get("next_action_href"))
    if "next_action_label" in delivery:
        public["next_action_label"] = str(delivery.get("next_action_label") or "").strip()
    if "next_action_method" in delivery:
        public["next_action_method"] = str(delivery.get("next_action_method") or "").strip()
    if "chat_ref_present" in delivery:
        public["chat_ref_present"] = bool(delivery.get("chat_ref_present"))
    if "chat_ref_sha256" in delivery:
        public["chat_ref_sha256"] = str(delivery.get("chat_ref_sha256") or "").strip()
    if "bot_key" in delivery:
        public["bot_key"] = str(delivery.get("bot_key") or "").strip()
    if "bot_handle" in delivery:
        public["bot_handle"] = str(delivery.get("bot_handle") or "").strip()
    if "bot_token_present" in delivery:
        public["bot_token_present"] = bool(delivery.get("bot_token_present"))
    if "message_count" in delivery:
        public["message_count"] = int(delivery.get("message_count") or 0)
    if "message_ids" in delivery:
        public["message_ids_present"] = bool(list(delivery.get("message_ids") or []))
    if "runtime_container" in delivery:
        public["runtime_container"] = str(delivery.get("runtime_container") or "").strip()
    return public


def build_receipt(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    web_base_url: str = "",
    public_web_base_url: str = "",
    container_name: str = "",
    timeout_seconds: float = 15.0,
    generated_at: str = "",
) -> dict[str, Any]:
    probe = ea_live_ops.probe_mymedia_alexa(
        container_name=container_name,
        web_base_url=web_base_url,
        public_web_base_url=public_web_base_url,
        timeout_seconds=max(float(timeout_seconds or 15.0), 1.0),
        output_format="json",
    )
    probe = _public_probe(dict(probe))
    probe.setdefault("public_surface_configured", False)
    probe.setdefault("public_surface_scope", "")
    probe.setdefault("public_surface_probe_attempted", False)
    probe.setdefault("public_surface_ready", False)
    probe.setdefault("public_surface_status", "not_configured")
    probe.setdefault("public_surface_reason", "")
    probe.setdefault("public_surface_http_status_code", 0)
    probe.setdefault("public_surface_access_protected", False)
    probe.setdefault("public_surface_cloudflare_blocked", False)
    probe.setdefault("public_surface_redirect_host", "")
    probe.setdefault("public_surface_content_type", "")
    probe.setdefault("public_surface_next_action", "")
    probe.setdefault("public_surface_next_action_href", "")
    probe.setdefault("public_surface_next_action_label", "")
    probe.setdefault("public_surface_next_action_method", "")
    probe.setdefault("public_surface_source", "http.public_surface_probe")
    probe_privacy = dict(probe.get("privacy") or {})
    probe_privacy.setdefault("raw_public_surface_redirect_exposed", False)
    probe_privacy.setdefault("raw_public_surface_response_body_exposed", False)
    probe["privacy"] = probe_privacy
    pairing_telegram_delivery = ea_live_ops.send_mymedia_amazon_pairing_telegram(
        web_base_url=web_base_url,
        dry_run=True,
        timeout_seconds=max(float(timeout_seconds or 15.0), 1.0),
        output_format="json",
    )
    ready = bool(probe.get("ready"))
    pairing_resume_ready = bool(probe.get("pairing_resume_ready"))
    pairing_resume_command = "make submit-mymedia-amazon-pairing-code OTP_CODE=123456" if pairing_resume_ready else ""
    next_action = str(probe.get("next_action") or "").strip()
    delivery = dict(pairing_telegram_delivery.get("telegram_delivery") or {})
    public_delivery = _public_telegram_delivery(delivery)
    pairing_session_pending = bool(probe.get("pairing_session_pending"))
    delivery_reason = str(
        delivery.get("readiness_reason")
        or delivery.get("reason")
        or pairing_telegram_delivery.get("delivery_reason")
        or pairing_telegram_delivery.get("reason")
        or pairing_telegram_delivery.get("next_action")
        or ""
    ).strip()
    receipt: dict[str, Any] = {
        "contract_name": CONTRACT_NAME,
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_mymedia_alexa_readiness.py",
        **_source_state(),
        "output_path": str(output_path),
        "status": str(probe.get("status") or "unknown").strip() or "unknown",
        "ready": ready,
        "probe_ok": bool(probe.get("probe_ok")),
        "reason": str(probe.get("reason") or "").strip(),
        "next_action": next_action,
        "next_action_href": _public_href(probe.get("next_action_href")),
        "next_action_label": str(probe.get("next_action_label") or "").strip(),
        "next_action_method": str(probe.get("next_action_method") or "").strip(),
        "claim": (
            "This receipt proves only the My Media for Alexa runtime posture: container health, redacted Amazon pairing "
            "state, watch-folder/index readiness, and whether a no-secret pairing handoff is resumable. "
            "It does not prove Alexa/Echo playback from a real device."
        ),
        "echo_playback_claim_allowed": False,
        "pairing_resume_ready": pairing_resume_ready,
        "pairing_resume_command": pairing_resume_command,
        "public_console_surface": {
            "claim": (
                "This section proves only whether an explicitly configured public My Media operator URL responds, "
                "redirects into Cloudflare Access, or fails at the public edge/origin. "
                "It does not prove Echo playback or that public exposure is broadly safe."
            ),
            "configured": bool(probe.get("public_surface_configured")),
            "base_url_scope": str(probe.get("public_surface_scope") or "").strip(),
            "probe_attempted": bool(probe.get("public_surface_probe_attempted")),
            "ready": bool(probe.get("public_surface_ready")),
            "status": str(probe.get("public_surface_status") or "").strip(),
            "reason": str(probe.get("public_surface_reason") or "").strip(),
            "http_status_code": int(probe.get("public_surface_http_status_code") or 0),
            "access_protected": bool(probe.get("public_surface_access_protected")),
            "cloudflare_blocked": bool(probe.get("public_surface_cloudflare_blocked")),
            "redirect_host": str(probe.get("public_surface_redirect_host") or "").strip(),
            "content_type": str(probe.get("public_surface_content_type") or "").strip(),
            "next_action": str(probe.get("public_surface_next_action") or "").strip(),
            "next_action_href": _public_href(probe.get("public_surface_next_action_href")),
            "next_action_label": str(probe.get("public_surface_next_action_label") or "").strip(),
            "next_action_method": str(probe.get("public_surface_next_action_method") or "").strip(),
            "source": _public_source_ref(probe.get("public_surface_source")),
            "privacy": {
                "raw_redirect_url_exposed": False,
                "raw_response_headers_exposed": False,
                "raw_response_body_exposed": False,
            },
        },
        "operator_action": {
            "user_action_required": not ready,
            "delivery_policy": "action_required_only" if not ready else "queue_only",
            "interruption_budget": "action_required" if not ready else "none",
            "next_action": next_action,
            "next_action_href": _public_href(probe.get("next_action_href")),
            "next_action_label": str(probe.get("next_action_label") or "").strip(),
            "next_action_method": str(probe.get("next_action_method") or "").strip(),
            "pairing_resume_ready": pairing_resume_ready,
            "pairing_resume_command": pairing_resume_command,
            "telegram_delivery_ready": bool(public_delivery.get("ready")),
            "raw_private_context_exposed": False,
        },
        "pairing_telegram_delivery": {
            "claim": (
                "This section proves only the no-secret My Media pairing Telegram handoff routing and operator delivery readiness. "
                "It is materialized with dry_run=true and does not send a live Telegram message."
            ),
            "dry_run": True,
            "live_message_claim_allowed": False,
            "status": str(pairing_telegram_delivery.get("status") or "").strip(),
            "reason": str(pairing_telegram_delivery.get("reason") or "").strip(),
            "next_action": str(pairing_telegram_delivery.get("next_action") or "").strip(),
            "next_action_href": _public_href(pairing_telegram_delivery.get("next_action_href")),
            "next_action_label": str(pairing_telegram_delivery.get("next_action_label") or "").strip(),
            "next_action_method": str(pairing_telegram_delivery.get("next_action_method") or "").strip(),
            "surface_kind": str(pairing_telegram_delivery.get("surface_kind") or "").strip(),
            "site": str(pairing_telegram_delivery.get("site") or "").strip(),
            "otp_channel": str(pairing_telegram_delivery.get("otp_channel") or "").strip(),
            "phone_suffix": str(pairing_telegram_delivery.get("phone_suffix") or "").strip(),
            "pairing_resume_ready": bool(pairing_telegram_delivery.get("pairing_resume_ready")),
            "pairing_session_pending": pairing_session_pending,
            "uses_saved_session": str(pairing_telegram_delivery.get("source") or "").strip() == "mymedia_setup.saved_session",
            "delivery_transport": str(public_delivery.get("delivery_transport") or "").strip(),
            "delivery_ready": bool(public_delivery.get("ready")),
            "delivery_reason": delivery_reason,
            "delivery_bot_handle": str(public_delivery.get("bot_handle") or "").strip(),
            "delivery_chat_ref_present": bool(public_delivery.get("chat_ref_present")),
            "delivery_chat_ref_sha256": str(public_delivery.get("chat_ref_sha256") or "").strip(),
            "delivery_message_count": int(public_delivery.get("message_count") or 0),
            "delivery_message_ids_present": bool(public_delivery.get("message_ids_present")),
            "delivery_runtime_container": str(public_delivery.get("runtime_container") or "").strip(),
            "source": _public_source_ref(pairing_telegram_delivery.get("source")),
            "observed_at": str(pairing_telegram_delivery.get("observed_at") or "").strip(),
            "privacy": {
                "raw_chat_ref_exposed": False,
                "raw_message_ids_exposed": False,
                "raw_message_text_exposed": False,
            },
            "telegram_delivery": public_delivery,
        },
        "privacy": {
            "raw_refresh_token_exposed": False,
            "raw_paired_user_exposed": False,
            "raw_watch_folder_paths_exposed": False,
            "raw_public_ip_exposed": False,
            "raw_pairing_resume_url_exposed": False,
        },
        "rules": [
            "A ready My Media receipt does not prove Alexa playback on a real Echo device.",
            "A blocked pairing receipt may still be recoverable when pairing_resume_ready=true and the saved browser handoff is fresh.",
            "Pairing recovery artifacts must stay local under .runtime and never be mirrored into published receipts.",
            "Public IP presence may be reported only as a boolean posture flag, never as the literal IP value.",
            "The embedded pairing_telegram_delivery section is a dry-run readiness probe and does not prove a live Telegram message was sent.",
        ],
        "probe": probe,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    if argv is None and any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python scripts/materialize_mymedia_alexa_readiness.py [options]\n\n"
            "Materialize the My Media for Alexa no-secret readiness receipt."
        )
        raise SystemExit(0)
    parser = argparse.ArgumentParser(description="Materialize the My Media for Alexa no-secret readiness receipt.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--web-base-url", default="")
    parser.add_argument("--public-web-base-url", default="")
    parser.add_argument("--container-name", default="")
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    receipt = build_receipt(
        output_path=args.output,
        web_base_url=args.web_base_url,
        public_web_base_url=args.public_web_base_url,
        container_name=args.container_name,
        timeout_seconds=args.timeout_seconds,
        generated_at=args.generated_at,
    )
    print(json.dumps(receipt, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
