#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.materialize_release_authority_status import build_status as build_release_authority_status
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from materialize_release_authority_status import build_status as build_release_authority_status


ROOT = Path(__file__).resolve().parents[1]
MEMORIAL_STATUS_PATH = ROOT / ".codex-design" / "product" / "MEMORIAL_OPERATOR_STATUS.generated.json"
_GENERATED_RELEASE_AUTHORITY_PATH = (
    ROOT / ".codex-studio" / "published" / "release_authority_status.generated.json"
)
RELEASE_AUTHORITY_PATH = _GENERATED_RELEASE_AUTHORITY_PATH


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _release_authority_payload(
    *, release_authority_status_path: Path
) -> dict[str, object]:
    if (
        release_authority_status_path.resolve()
        == _GENERATED_RELEASE_AUTHORITY_PATH.resolve()
    ):
        payload = build_release_authority_status()
        return payload if isinstance(payload, dict) else {}
    return _load_json(release_authority_status_path)


def build_payload(
    *,
    memorial_status_path: Path | None = None,
    release_authority_status_path: Path | None = None,
) -> dict[str, object]:
    # Resolve defaults at call time so embedded callers can explicitly replace
    # the generated status sources without being pinned to import-time paths.
    memorial_status_path = memorial_status_path or MEMORIAL_STATUS_PATH
    release_authority_status_path = (
        release_authority_status_path or RELEASE_AUTHORITY_PATH
    )
    memorial_status = _load_json(memorial_status_path)
    release_authority = _release_authority_payload(
        release_authority_status_path=release_authority_status_path
    )

    public_runtime = memorial_status.get("public_runtime_mode_detail")
    public_runtime = public_runtime if isinstance(public_runtime, dict) else {}
    runtime_status = str(public_runtime.get("status") or "").strip().lower() or "missing"
    runtime_reason = str(public_runtime.get("reason") or "").strip() or "public_runtime_mode_missing"
    runtime_next_action = str(public_runtime.get("next_action") or "").strip() or "deploy_ea_memorial"

    authority_state = str(release_authority.get("state") or "").strip().lower() or "missing"
    authority_gate = release_authority.get("gate")
    authority_gate = authority_gate if isinstance(authority_gate, dict) else {}
    authority_gate_status = str(authority_gate.get("status") or "").strip().lower() or "missing"
    authority_issues = [
        str(item).strip()
        for item in list(release_authority.get("issues") or [])
        if str(item).strip()
    ]
    for item in list(authority_gate.get("issues") or []):
        normalized = str(item).strip()
        if normalized and normalized not in authority_issues:
            authority_issues.append(normalized)
    authority_passed = (
        authority_state == "clear"
        and authority_gate_status == "pass"
        and not authority_issues
    )
    authority_status = "pass" if authority_passed else "fail"
    authority_next_action = (
        str(release_authority.get("next_action") or "").strip()
        or "clear_release_authority_for_memorial_deploy"
    )

    issues: list[str] = []
    next_action = "deploy_ea_memorial"
    if authority_status != "pass":
        issues.extend(authority_issues or ["release_authority_blocked"])
        next_action = "clear_release_authority_for_memorial_deploy"
    if runtime_status != "pass":
        issues.append(runtime_reason)
        if next_action == "deploy_ea_memorial":
            next_action = runtime_next_action

    return {
        "contract_name": "ea.memorial_deploy_readiness.v1",
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "next_action": next_action,
        "memorial_operator_status_path": _display_path(memorial_status_path),
        "release_authority_status_path": _display_path(release_authority_status_path),
        "memorial_public_runtime": {
            "status": runtime_status,
            "reason": runtime_reason,
            "next_action": runtime_next_action,
            "project_mode": str(public_runtime.get("project_mode") or "").strip(),
            "enabled_project_modes": list(public_runtime.get("enabled_project_modes") or []),
        },
        "release_authority": {
            "status": authority_status,
            "state": authority_state,
            "gate_status": authority_gate_status,
            "issues": authority_issues,
            "next_action": authority_next_action,
            "authority_posture": str(release_authority.get("authority_posture") or "").strip(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify memorial deploy readiness before running deploy-ea-memorial."
    )
    parser.add_argument(
        "--memorial-status",
        type=Path,
        default=MEMORIAL_STATUS_PATH,
        help="Memorial operator-status artifact to verify.",
    )
    parser.add_argument(
        "--release-authority-status",
        type=Path,
        default=RELEASE_AUTHORITY_PATH,
        help="Release-authority status artifact to verify.",
    )
    parser.add_argument("--pretty", action="store_true", help="Print indented JSON.")
    args = parser.parse_args(argv)
    payload = build_payload(
        memorial_status_path=args.memorial_status.expanduser().resolve(),
        release_authority_status_path=args.release_authority_status.expanduser().resolve(),
    )
    if args.pretty:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        print(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
