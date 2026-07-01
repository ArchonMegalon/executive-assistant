#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint

DEFAULT_RECEIPT = ROOT / ".codex-studio/published/whatsapp_web_action_processor_readiness.generated.json"
EXPECTED_RULES = {
    "A ready runtime receipt does not prove a live audiobook delivery happened.",
    "Ready runtime means WhatsApp can process both button callbacks and degraded text controls for audiobook voice selection when the upstream transport preserves those messages.",
    "A blocked runtime receipt means the WhatsApp action processor cannot be trusted for fresh live EPUB evidence yet.",
    "Live delivery still requires a fresh WhatsApp job receipt plus public-share delivery and playback evidence.",
}


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _git_head(path: Path = ROOT) -> str:
    return resolve_source_state_head(path)


def _source_fingerprint(path: Path = ROOT) -> str:
    return resolve_source_worktree_fingerprint(path)


def verify(path: Path = DEFAULT_RECEIPT, *, root: Path = ROOT) -> list[str]:
    issues: list[str] = []
    receipt = _json(path)
    if not receipt:
        return [f"whatsapp web action processor readiness missing or invalid: {path}"]

    if receipt.get("contract_name") != "ea.whatsapp_web_action_processor_readiness.v1":
        issues.append("contract_name must be ea.whatsapp_web_action_processor_readiness.v1")
    if receipt.get("generated_by") != "scripts/materialize_whatsapp_web_action_processor_readiness.py":
        issues.append("generated_by must point at the WhatsApp readiness materializer")
    if receipt.get("head_semantics") != "source_state":
        issues.append("head_semantics must remain source_state")

    current_head = _git_head(root)
    current_fingerprint = _source_fingerprint(root)
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    recorded_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    fingerprint_matches = bool(current_fingerprint and recorded_fingerprint and current_fingerprint == recorded_fingerprint)
    if not recorded_head:
        issues.append("source_git_head missing")
    elif current_head and recorded_head != current_head and not fingerprint_matches:
        issues.append("receipt is stale relative to current source HEAD")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("source_state_fingerprint_semantics must describe the source worktree fingerprint")
    if not recorded_fingerprint:
        issues.append("source_state_fingerprint missing")
    elif current_fingerprint and recorded_fingerprint != current_fingerprint:
        issues.append("receipt is stale relative to current source fingerprint")

    status = str(receipt.get("status") or "").strip()
    if status not in {"ready", "blocked"}:
        issues.append("status must stay ready or blocked")

    ready = bool(receipt.get("ready"))
    runtime_ready_claim_allowed = bool(receipt.get("runtime_ready_claim_allowed"))
    if status == "ready":
        if not ready:
            issues.append("ready status requires ready=true")
        if not runtime_ready_claim_allowed:
            issues.append("ready status requires runtime_ready_claim_allowed=true")
        if str(receipt.get("reason") or "").strip() != "ready":
            issues.append("ready status requires reason=ready")
        if list(receipt.get("reasons") or []):
            issues.append("ready status must not list blocking reasons")
    else:
        if ready:
            issues.append("blocked status must not claim ready=true")
        if runtime_ready_claim_allowed:
            issues.append("blocked status must not claim runtime_ready_claim_allowed=true")
        if not list(receipt.get("reasons") or []):
            issues.append("blocked status must list reasons")

    if receipt.get("live_delivery_claim_allowed") is not False:
        issues.append("live_delivery_claim_allowed must remain false")
    if receipt.get("goal_completion_claim_allowed") is not False:
        issues.append("goal_completion_claim_allowed must remain false")

    rules = set(str(item).strip() for item in list(receipt.get("rules") or []) if str(item).strip())
    if rules != EXPECTED_RULES:
        issues.append("rules drifted")

    if not str(receipt.get("next_action") or "").strip():
        issues.append("next_action must be present")

    if "callback_secret_present" not in receipt:
        issues.append("callback_secret_present missing")
    if "action_processor_enabled" not in receipt:
        issues.append("action_processor_enabled missing")
    if "sidecar_ready" not in receipt:
        issues.append("sidecar_ready missing")
    if "state_fresh" not in receipt:
        issues.append("state_fresh missing")

    return issues


def main() -> int:
    import sys

    if any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python scripts/verify_whatsapp_web_action_processor_readiness.py [options]\n\n"
            "Verify the WhatsApp Web action processor readiness receipt."
        )
        return 0
    parser = argparse.ArgumentParser(description="Verify the WhatsApp Web action processor readiness receipt.")
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
