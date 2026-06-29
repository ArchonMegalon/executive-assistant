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

from app.services.proactive_ooda_approval_reissue import reissue_current_proactive_ooda_approval


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name) or default).strip()


def _jsonify(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): _jsonify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(item) for item in value]
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reissue Telegram approval buttons for the current proactive OODA packet.")
    parser.add_argument("--principal-id", default=_env("EA_PROACTIVE_OODA_PRINCIPAL_ID"))
    parser.add_argument("--state-path", default=_env("EA_PROACTIVE_OODA_STATE_PATH", "state/proactive_ooda_notified.json"))
    parser.add_argument("--receipt-path", default=_env("EA_PROACTIVE_OODA_RECEIPT_PATH"))
    parser.add_argument("--stage-packet-dir", default=_env("EA_PROACTIVE_OODA_STAGE_PACKET_DIR"))
    parser.add_argument("--safe-work-result-dir", default=_env("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR"))
    parser.add_argument("--root", default=_env("EA_PROACTIVE_OODA_ROOT", str(ROOT)))
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--reissue-after-seconds",
        type=int,
        default=int(_env("EA_PROACTIVE_OODA_APPROVAL_REISSUE_AFTER_SECONDS", "0") or "0"),
        help="Allow reissue of a live pending approval only after this age threshold; 0 keeps no-spam behavior.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = reissue_current_proactive_ooda_approval(
        principal_id=str(args.principal_id or "").strip(),
        root=Path(str(args.root or ROOT)).resolve(),
        state_path=str(args.state_path or "").strip(),
        receipt_path=str(args.receipt_path or "").strip(),
        stage_packet_dir=str(args.stage_packet_dir or "").strip(),
        safe_work_result_dir=str(args.safe_work_result_dir or "").strip(),
        force=bool(args.force),
        reissue_after_seconds=max(int(args.reissue_after_seconds or 0), 0),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(_jsonify(result), sort_keys=True))
    return 0 if str(result.get("status") or "").strip() in {"sent", "already_live_pending", "already_decided", "dry_run"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
