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
DEFAULT_IMPLEMENTATION_SCOPE = ROOT / ".codex-design" / "repo" / "IMPLEMENTATION_SCOPE.md"

REQUIRED_RELEASE_CONTRACT_PATHS = (
    ROOT / ".codex-design" / "repo" / "EA_FLAGSHIP_TRUTH_PLANE.md",
    ROOT / ".codex-design" / "repo" / "EA_FLAGSHIP_RELEASE_GATE.json",
    ROOT / ".codex-design" / "repo" / "IMPLEMENTATION_SCOPE.md",
    ROOT / ".codex-design" / "ea" / "START_HERE.md",
    ROOT / ".codex-design" / "ea" / "SURFACE_DESIGN_SYSTEM.md",
    ROOT / ".codex-design" / "ea" / "LTD_INTEGRATION_MAP.md",
    ROOT / ".codex-design" / "product" / "EA_FLAGSHIP_RELEASE_GATE.generated.json",
    ROOT / ".codex-design" / "product" / "PUBLIC_MEDIA_AND_GUIDE_ASSET_POLICY.md",
    ROOT / ".codex-design" / "product" / "PUBLIC_CONCIERGE_WORKFLOWS.yaml",
    ROOT / ".codex-design" / "product" / "WEEKLY_PRODUCT_PULSE.generated.json",
    ROOT / ".codex-studio" / "published" / "EA_BROWSER_WORKFLOW_PROOF.generated.json",
)


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


def _pulse_journey_summary_snapshot(pulse: dict[str, Any], path: Path) -> dict[str, Any]:
    health = pulse.get("journey_gate_health")
    if not isinstance(health, dict):
        return {}
    supporting_signals = pulse.get("supporting_signals")
    if not isinstance(supporting_signals, dict):
        supporting_signals = {}
    source = str(pulse.get("journey_gate_source") or supporting_signals.get("journey_gate_source") or "").strip()
    if source != path.as_posix():
        return {}
    state = str(health.get("state") or health.get("status") or "").strip().lower()
    if not state:
        return {}
    return {
        "overall_state": state,
        "blocked_count": int(health.get("blocked_count") or 0),
        "warning_count": int(health.get("warning_count") or 0),
        "source": "weekly_product_pulse_snapshot",
    }


def _journey_summary(path: Path, *, pulse: dict[str, Any]) -> dict[str, Any]:
    payload = _json(path)
    summary = payload.get("summary")
    if isinstance(summary, dict):
        return dict(summary)
    return _pulse_journey_summary_snapshot(pulse, path)


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def verify(
    *,
    pulse_path: Path,
    flagship_receipt_path: Path,
    browser_proof_path: Path,
    journey_gates_path: Path,
    implementation_scope_path: Path = DEFAULT_IMPLEMENTATION_SCOPE,
    required_contract_paths: tuple[Path, ...] = REQUIRED_RELEASE_CONTRACT_PATHS,
) -> list[str]:
    issues: list[str] = []
    pulse = _json(pulse_path)
    receipt = _json(flagship_receipt_path)
    browser = _json(browser_proof_path)
    journey_summary = _journey_summary(journey_gates_path, pulse=pulse)
    implementation_scope = _text(implementation_scope_path)

    for path in required_contract_paths:
        if not path.exists():
            issues.append(f"required EA release contract missing: {path}")

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
    pulse_contract = str(pulse.get("contract_name") or "").strip()
    release_truth_source = str(
        pulse.get("release_truth_source")
        or dict(pulse.get("supporting_signals") or {}).get("flagship_release_receipt_source")
        or ""
    ).strip()
    scorecard_source = str(pulse.get("scorecard_source") or "").strip()

    if receipt_status != "pass":
        issues.append(f"flagship release receipt is {receipt_status or 'missing'}, expected pass")
    if browser_status != "pass":
        issues.append(f"browser workflow proof is {browser_status or 'missing'}, expected pass")
    if pulse_contract != "ea.weekly_product_pulse":
        issues.append(f"weekly product pulse contract is {pulse_contract or 'missing'}, expected ea.weekly_product_pulse")
    if release_truth_source != ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json":
        issues.append(
            "weekly product pulse release truth source is "
            f"{release_truth_source or 'missing'}, expected .codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json"
        )
    if scorecard_source and scorecard_source != ".codex-design/product/PRODUCT_HEALTH_SCORECARD.yaml":
        issues.append(
            "weekly product pulse scorecard source is "
            f"{scorecard_source}, expected .codex-design/product/PRODUCT_HEALTH_SCORECARD.yaml"
        )
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
    if ".codex-design/ea/*" not in implementation_scope:
        issues.append("implementation scope no longer requires mirrored .codex-design/ea/* canon")
    if "EA product surface canon under `.codex-design/ea/*`" not in implementation_scope:
        issues.append("implementation scope no longer owns the EA product surface canon line")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail closed unless EA flagship release readiness is genuinely clear.")
    parser.add_argument("--pulse", type=Path, default=DEFAULT_PULSE)
    parser.add_argument("--flagship-receipt", type=Path, default=DEFAULT_FLAGSHIP_RECEIPT)
    parser.add_argument("--browser-proof", type=Path, default=DEFAULT_BROWSER_PROOF)
    parser.add_argument("--journey-gates", type=Path, default=DEFAULT_JOURNEY_GATES)
    parser.add_argument("--implementation-scope", type=Path, default=DEFAULT_IMPLEMENTATION_SCOPE)
    args = parser.parse_args()

    issues = verify(
        pulse_path=args.pulse,
        flagship_receipt_path=args.flagship_receipt,
        browser_proof_path=args.browser_proof,
        journey_gates_path=args.journey_gates,
        implementation_scope_path=args.implementation_scope,
    )
    if issues:
        print(json.dumps({"status": "blocked", "issues": issues}, indent=2))
        return 1
    print(json.dumps({"status": "pass", "message": "EA flagship release readiness is clear."}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
