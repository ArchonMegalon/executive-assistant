#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PULSE = ROOT / ".codex-design" / "product" / "WEEKLY_PRODUCT_PULSE.generated.json"
DEFAULT_FLAGSHIP_RECEIPT = ROOT / ".codex-design" / "product" / "EA_FLAGSHIP_RELEASE_GATE.generated.json"
DEFAULT_BROWSER_PROOF = ROOT / ".codex-studio" / "published" / "EA_BROWSER_WORKFLOW_PROOF.generated.json"
DEFAULT_JOURNEY_GATES = Path("/docker/fleet/.codex-studio/published/JOURNEY_GATES.generated.json")


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _state(payload: dict[str, Any], key: str) -> str:
    section = payload.get(key)
    if not isinstance(section, dict):
        return ""
    return str(section.get("state") or section.get("status") or "").strip().lower()


def _journey_summary(path: Path) -> dict[str, Any]:
    payload = _json(path)
    summary = payload.get("summary")
    return dict(summary) if isinstance(summary, dict) else {}


def verify(
    *,
    pulse_path: Path,
    flagship_receipt_path: Path,
    browser_proof_path: Path,
    journey_gates_path: Path,
) -> list[str]:
    issues: list[str] = []
    pulse = _json(pulse_path)
    receipt = _json(flagship_receipt_path)
    browser = _json(browser_proof_path)
    journey_summary = _journey_summary(journey_gates_path)

    if not pulse:
        issues.append(f"weekly product pulse missing or invalid: {pulse_path}")
    if not receipt:
        issues.append(f"flagship release receipt missing or invalid: {flagship_receipt_path}")
    if not browser:
        issues.append(f"browser workflow proof missing or invalid: {browser_proof_path}")
    if not journey_summary:
        issues.append(f"journey gates summary missing or invalid: {journey_gates_path}")

    receipt_status = str(receipt.get("status") or "").strip().lower()
    browser_status = str(browser.get("status") or browser.get("receipt_status") or "").strip().lower()
    release_health = _state(pulse, "release_health")
    flagship_readiness = _state(pulse, "flagship_readiness")
    journey_health = _state(pulse, "journey_gate_health")
    launch_readiness = str(dict(pulse.get("supporting_signals") or {}).get("launch_readiness") or "").strip()
    journey_state = str(journey_summary.get("overall_state") or "").strip().lower()
    blocked_count = int(journey_summary.get("blocked_count") or 0)

    if receipt_status != "pass":
        issues.append(f"flagship release receipt is {receipt_status or 'missing'}, expected pass")
    if browser_status != "pass":
        issues.append(f"browser workflow proof is {browser_status or 'missing'}, expected pass")
    if release_health not in {"clear", "ready"}:
        issues.append(f"weekly release_health is {release_health or 'missing'}, expected clear/ready")
    if flagship_readiness not in {"clear", "ready"}:
        issues.append(f"weekly flagship_readiness is {flagship_readiness or 'missing'}, expected clear/ready")
    if journey_health not in {"ready", "clear"}:
        issues.append(f"weekly journey_gate_health is {journey_health or 'missing'}, expected ready/clear")
    if journey_state != "ready":
        issues.append(f"fleet journey gates are {journey_state or 'missing'}, expected ready")
    if blocked_count != 0:
        issues.append(f"fleet journey gates still report {blocked_count} blocked journey(s)")
    if "hold launch expansion" in launch_readiness.lower():
        issues.append(f"weekly launch_readiness still blocks expansion: {launch_readiness}")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail closed unless EA flagship release readiness is genuinely clear.")
    parser.add_argument("--pulse", type=Path, default=DEFAULT_PULSE)
    parser.add_argument("--flagship-receipt", type=Path, default=DEFAULT_FLAGSHIP_RECEIPT)
    parser.add_argument("--browser-proof", type=Path, default=DEFAULT_BROWSER_PROOF)
    parser.add_argument("--journey-gates", type=Path, default=DEFAULT_JOURNEY_GATES)
    args = parser.parse_args()

    issues = verify(
        pulse_path=args.pulse,
        flagship_receipt_path=args.flagship_receipt,
        browser_proof_path=args.browser_proof,
        journey_gates_path=args.journey_gates,
    )
    if issues:
        print(json.dumps({"status": "blocked", "issues": issues}, indent=2))
        return 1
    print(json.dumps({"status": "pass", "message": "EA flagship release readiness is clear."}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
