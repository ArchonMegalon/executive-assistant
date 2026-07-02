#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
for candidate in (str(ROOT), str(EA_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.services.proactive_ooda_approval_reissue import reissue_current_proactive_ooda_approval  # noqa: E402


def _default_runtime_state_path() -> str:
    configured = str(os.getenv("EA_PROACTIVE_OODA_STATE_PATH") or "").strip()
    if configured:
        return configured
    runtime_default = Path("/data/provider-ledger/proactive_ooda_notified.json")
    return runtime_default.as_posix() if runtime_default.exists() else "state/proactive_ooda_notified.json"


def _default_runtime_receipt_path() -> str:
    configured = str(os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH") or "").strip()
    if configured:
        return configured
    runtime_default = Path("/data/provider-ledger/proactive_ooda_latest_run.generated.json")
    return runtime_default.as_posix() if runtime_default.exists() else ""


def _default_stage_packet_dir() -> str:
    configured = str(os.getenv("EA_PROACTIVE_OODA_STAGE_PACKET_DIR") or "").strip()
    if configured:
        return configured
    runtime_default = Path("/data/provider-ledger/proactive_ooda_stage_packets")
    return runtime_default.as_posix() if runtime_default.exists() else ""


def _default_safe_work_result_dir() -> str:
    configured = str(os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR") or "").strip()
    if configured:
        return configured
    runtime_default = Path("/data/provider-ledger/proactive_ooda_safe_work_results")
    return runtime_default.as_posix() if runtime_default.exists() else ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reissue the current proactive OODA Telegram approval surface.")
    parser.add_argument("--principal-id", default=os.getenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", ""))
    parser.add_argument("--state-path", default=_default_runtime_state_path())
    parser.add_argument("--receipt-path", default=_default_runtime_receipt_path())
    parser.add_argument("--stage-packet-dir", default=_default_stage_packet_dir())
    parser.add_argument("--safe-work-result-dir", default=_default_safe_work_result_dir())
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--reissue-after-seconds",
        type=int,
        default=int(os.getenv("EA_PROACTIVE_OODA_APPROVAL_REISSUE_AFTER_SECONDS", "0") or "0"),
        help="Allow reissue of a live pending approval only after this age threshold; 0 keeps no-spam behavior.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def main() -> int:
    args = parse_args()
    result = reissue_current_proactive_ooda_approval(
        principal_id=str(args.principal_id or "").strip(),
        root=ROOT,
        state_path=args.state_path,
        receipt_path=args.receipt_path,
        stage_packet_dir=args.stage_packet_dir,
        safe_work_result_dir=args.safe_work_result_dir,
        force=bool(args.force),
        reissue_after_seconds=max(int(args.reissue_after_seconds or 0), 0),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(_jsonable(result), sort_keys=True))
    status = str(result.get("status") or "").strip()
    return 0 if status in {"sent", "already_live_pending", "dry_run"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
