#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
for candidate in (str(ROOT), str(EA_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.services.proactive_ooda_safe_work import (  # noqa: E402
    default_safe_work_result_dir,
    persist_safe_work_results,
)
from app.services.proactive_ooda_stage_packets import default_stage_packet_dir  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize private safe-work results from proactive OODA stage packets.")
    parser.add_argument("--stage-packet-dir", default=os.getenv("EA_PROACTIVE_OODA_STAGE_PACKET_DIR", ""))
    parser.add_argument("--result-dir", default=os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR", ""))
    parser.add_argument("--state-path", default=os.getenv("EA_PROACTIVE_OODA_STATE_PATH", "state/proactive_ooda_notified.json"))
    parser.add_argument("--limit", type=int, default=int(os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_LIMIT", "100") or "100"))
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    stage_dir = _stage_packet_dir(args)
    result_dir = _result_dir(args, stage_dir=stage_dir)
    result = persist_safe_work_results(stage_packet_dir=stage_dir, result_dir=result_dir, limit=args.limit)
    payload = {
        "ok": not result.errors,
        "stage_packet_dir": str(stage_dir),
        "result_dir": str(result_dir),
        "result_count": len(result.result_refs),
        "result_refs": list(result.result_refs),
        "paths": list(result.paths),
        "errors": list(result.errors),
    }
    if args.pretty:
        print(_format_report(payload))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["ok"] else 1


def _stage_packet_dir(args: argparse.Namespace) -> Path:
    configured = str(getattr(args, "stage_packet_dir", "") or "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else ROOT / path
    return default_stage_packet_dir(root=ROOT, state_path=getattr(args, "state_path", "state/proactive_ooda_notified.json"))


def _result_dir(args: argparse.Namespace, *, stage_dir: Path) -> Path:
    configured = str(getattr(args, "result_dir", "") or "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else ROOT / path
    return default_safe_work_result_dir(stage_dir)


def _format_report(payload: dict[str, object]) -> str:
    status = "ok" if payload.get("ok") else "not ready"
    lines = [
        f"proactive OODA safe work: {status}",
        f"stage packets: {payload.get('stage_packet_dir')}",
        f"results: {payload.get('result_count')} -> {payload.get('result_dir')}",
    ]
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        lines.append(f"errors: {', '.join(str(item) for item in errors)}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
