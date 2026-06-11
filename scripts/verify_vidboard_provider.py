#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                str(ROOT / "scripts" / "verify_ltd_provider_lanes.py"),
                "--lane",
                "video_provider_bakeoff",
            ]
        )
    )
