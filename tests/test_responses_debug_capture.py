from __future__ import annotations

import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ea"))
from app.api.routes import responses


def test_responses_debug_capture_prunes_numbered_files(monkeypatch, tmp_path):
    monkeypatch.setenv("EA_RESPONSES_DEBUG_CAPTURE_DIR", str(tmp_path))
    monkeypatch.setenv("EA_RESPONSES_DEBUG_CAPTURE_MAX_FILES", "2")
    monkeypatch.setenv("EA_RESPONSES_DEBUG_CAPTURE_MAX_BYTES", str(1024 * 1024))
    monkeypatch.setenv("EA_RESPONSES_DEBUG_CAPTURE_MAX_AGE_SECONDS", str(24 * 60 * 60))
    monkeypatch.setenv("EA_RESPONSES_DEBUG_CAPTURE_PRUNE_EVERY_SECONDS", "0")
    responses._RESPONSES_DEBUG_CAPTURE_LAST_PRUNE = 0.0

    for index in range(5):
        responses._capture_responses_debug(name="request", payload={"index": index})
        time.sleep(0.002)

    numbered = sorted(path.name for path in tmp_path.glob("*_request.json") if not path.name.startswith("latest_"))

    assert len(numbered) <= 2
    assert (tmp_path / "latest_request.json").is_file()
