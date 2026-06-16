#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
if str(EA_DIR) not in sys.path:
    sys.path.insert(0, str(EA_DIR))

from app.services.release_materialization_service import materialize_release_assets


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the full EA release-truth bundle in one orchestrated pass.")
    parser.add_argument("--python-bin", default=os.getenv("PYTHON_BIN", os.getenv("VIRTUAL_ENV", "") and os.path.join(os.getenv("VIRTUAL_ENV", ""), "bin", "python") or "python3"))
    args = parser.parse_args()
    materialize_release_assets(python_bin=args.python_bin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
