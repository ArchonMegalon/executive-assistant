from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("smoke_v1_12_6_avomap.py")), run_name="__main__")
