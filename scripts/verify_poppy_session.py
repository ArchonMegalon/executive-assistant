#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_ltd_provider_lanes.py"),
            "--lane",
            "poppy_draft_workbench",
            "--no-write",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    sys.stdout.write(result.stdout)
    payload = json.loads(result.stdout)
    missing = payload.get("missing_checks") if isinstance(payload, dict) else []
    raise SystemExit(0 if not missing else 1)
