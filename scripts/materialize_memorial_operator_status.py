#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".codex-design" / "product" / "MEMORIAL_OPERATOR_STATUS.generated.json"


def _run_json(script: str) -> dict:
    proc = subprocess.run([sys.executable, str(ROOT / script)], capture_output=True, text=True, timeout=30)
    try:
        return json.loads(proc.stdout.strip() or "{}")
    except Exception:
        return {"status": "error", "script": script, "stdout": proc.stdout[:800], "stderr": proc.stderr[:800]}


def main() -> int:
    readiness = _run_json("scripts/verify_memorial_gold_readiness.py")
    whole_project = _run_json("scripts/verify_whole_project_gold_map.py")
    payload = {
        "contract_name": "ea.memorial_operator_status",
        "generated_by": "scripts/materialize_memorial_operator_status.py",
        "slug": "manfred",
        "current_label": "Memorial public-origin gold: blocked" if readiness.get("memorial_voice_gold_claim_allowed") is not True else "Memorial public-origin gold: pass",
        "local_release_candidate": "pass" if not list(readiness.get("local_release_issues") or []) else "blocked",
        "public_voice_receipt": "pass" if not list(readiness.get("public_gold_issues") or []) else "missing_or_blocked",
        "public_browser_receipt": "pass" if not list(readiness.get("public_browser_gold_issues") or []) else "missing_or_blocked",
        "room_audio_receipt": "pass" if not list(readiness.get("room_audio_issues") or []) else "missing_or_blocked",
        "whole_project_gold": whole_project.get("status", "unknown"),
        "operator_notes": [
            "Use labels only: Memorial local release candidate / Memorial public-origin gold: blocked|pass.",
            "Public-origin gold requires voice, browser, and room receipts at current HEAD/public origin.",
        ],
        "readiness": readiness,
        "whole_project": whole_project,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "output": OUTPUT.as_posix(), "current_label": payload["current_label"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
