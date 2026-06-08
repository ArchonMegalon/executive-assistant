from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_plan_memorial_live_avatar_integration_materializes_expected_contract(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "plan_memorial_live_avatar_integration.py"
    output = tmp_path / "plan.json"
    completed = subprocess.run(
        ["python3", str(script), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["decision"]["primary_provider"] == "tavus"
    assert payload["decision"]["secondary_provider"] == "did"
    assert payload["permission_gates"]["camera"]["required_for_live_meeting"] is False
    assert payload["fallback_policy"]["provider_session_create_failed"] == "fallback_to_existing_memorial_voice_call"
    assert "/memorials/{slug}/video-meeting/session" in payload["server_contract"]["new_endpoints_needed"]

