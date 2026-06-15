#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".codex-design" / "product" / "MEMORIAL_OPERATOR_STATUS.generated.json"
WHOLE_PROJECT_GOLD_MAP = ROOT / ".codex-design" / "product" / "WHOLE_PROJECT_GOLD_MAP.generated.json"
MEANINGFUL_BROWSER_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_realtime_browser_meaningful_public_origin.generated.json"


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _run_json(script: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / script)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=ROOT,
    )
    output = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    try:
        return json.loads(output or "{}")
    except Exception:
        return {"status": "error", "script": script, "stdout": proc.stdout[:800], "stderr": proc.stderr[:800]}


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _receipt_state(path: Path) -> str:
    payload = _load_json(path)
    if str(payload.get("status") or "").strip().lower() == "pass":
        return "pass"
    if path.exists():
        return "blocked"
    return "missing_or_blocked"


def main() -> int:
    readiness = _run_json("scripts/verify_memorial_gold_readiness.py")
    whole_project = _run_json("scripts/verify_whole_project_gold_map.py")
    whole_project_map = _load_json(WHOLE_PROJECT_GOLD_MAP)
    whole_project_gold = "blocked"
    whole_project_verifier_status = str(whole_project.get("status") or "blocked").strip().lower()
    if (
        whole_project_verifier_status == "pass"
        and whole_project_map.get("gold_claim_allowed") is True
        and str(whole_project_map.get("overall_status") or "").strip().lower() == "gold"
    ):
        whole_project_gold = "pass"
    elif whole_project_map:
        whole_project_gold = "blocked"
    else:
        whole_project_gold = "unknown"

    readiness_status = str(readiness.get("status") or "blocked").strip().lower()
    has_any_readiness_issues = bool(
        list(readiness.get("local_release_issues") or [])
        or list(readiness.get("public_gold_issues") or [])
        or list(readiness.get("public_browser_gold_issues") or [])
        or list(readiness.get("room_audio_issues") or [])
    )
    memorial_public_gold_claim_allowed = (
        readiness_status == "pass"
        or (
            readiness.get("memorial_voice_gold_claim_allowed") is True
            and not has_any_readiness_issues
        )
    )
    whole_project_gold_allowed = whole_project_gold == "pass"
    memorial_public_gold_allowed = memorial_public_gold_claim_allowed and whole_project_gold_allowed
    final_status = "pass" if memorial_public_gold_allowed else "blocked"
    payload = {
        "contract_name": "ea.memorial_operator_status",
        "generated_by": "scripts/materialize_memorial_operator_status.py",
        "slug": "manfred",
        "status": final_status,
        "current_label": "Memorial public-origin gold: pass" if final_status == "pass" else "Memorial public-origin gold: blocked",
        "local_release_candidate": "pass" if not list(readiness.get("local_release_issues") or []) else "blocked",
        "public_voice_receipt": "pass" if not list(readiness.get("public_gold_issues") or []) else "missing_or_blocked",
        "public_browser_receipt": "pass" if not list(readiness.get("public_browser_gold_issues") or []) else "missing_or_blocked",
        "public_browser_meaningful_receipt": _receipt_state(MEANINGFUL_BROWSER_RECEIPT),
        "room_audio_receipt": "pass" if not list(readiness.get("room_audio_issues") or []) else "missing_or_blocked",
        "whole_project_gold": whole_project_gold,
        "operator_notes": [
            "Use labels only: Memorial local release candidate / Memorial public-origin gold: blocked|pass.",
            "Public-origin gold requires voice, browser, and room receipts at current HEAD/public origin.",
        ],
        "artifact_paths": {
            "local_release_receipt": _display_path(ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"),
            "public_gold_receipt": _display_path(ROOT / ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"),
            "public_browser_gold_receipt": _display_path(ROOT / ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json"),
            "public_meaningful_browser_gold_receipt": _display_path(MEANINGFUL_BROWSER_RECEIPT),
            "room_audio_receipt": _display_path(ROOT / ".codex-studio/published/memorial_room_audio_public_origin.generated.json"),
        },
        "readiness": readiness,
        "whole_project": whole_project,
        "whole_project_map_summary": {
            "overall_status": whole_project_map.get("overall_status", ""),
            "gold_claim_allowed": whole_project_map.get("gold_claim_allowed"),
            "blocking_planes": list(whole_project_map.get("blocking_planes") or []),
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": final_status,
                "output": OUTPUT.as_posix(),
                "current_label": payload["current_label"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
