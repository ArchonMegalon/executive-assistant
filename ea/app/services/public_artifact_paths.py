from __future__ import annotations

import os
from pathlib import Path


EA_APP_ROOT = Path(__file__).resolve().parents[2]


def public_result_dir() -> Path:
    return Path(str(os.getenv("EA_PUBLIC_RESULT_DIR") or EA_APP_ROOT / "_completion" / "public_browseract_results")).expanduser()


def public_tour_dir() -> Path:
    return Path(str(os.getenv("EA_PUBLIC_TOUR_DIR") or EA_APP_ROOT / "_completion" / "public_property_tours")).expanduser()
