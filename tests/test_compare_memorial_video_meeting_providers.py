from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_compare_memorial_video_meeting_providers_recommends_live_and_batch_split(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "compare_memorial_video_meeting_providers.py"
    output = tmp_path / "matrix.json"
    completed = subprocess.run(
        ["python3", str(script), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["recommendation"]["primary"] == "tavus"
    assert payload["recommendation"]["secondary"] == "did"
    assert payload["recommendation"]["owned_ltd_backup"] == "nonverbia"
    assert payload["recommendation"]["batch_clip_lane"] == "vidboard"
    providers = {item["provider_key"]: item for item in payload["providers"]}
    assert providers["vidboard"]["captcha_assessment"]["one_time_only"] is False
    assert providers["tavus"]["realtime_meeting_ready"] is True
    assert providers["did"]["realtime_meeting_ready"] is True

