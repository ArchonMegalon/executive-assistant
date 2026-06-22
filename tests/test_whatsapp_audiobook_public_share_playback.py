from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "ea" / "scripts" / "verify_whatsapp_audiobook_public_share_playback.py"


def _module():
    spec = importlib.util.spec_from_file_location("verify_whatsapp_audiobook_public_share_playback", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_record_playback_e2e_updates_job_without_exposing_urls(tmp_path: Path) -> None:
    module = _module()
    job_dir = tmp_path / "job-wa-playback"
    job_dir.mkdir()
    job_path = job_dir / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "job_id": "job-wa-playback",
                "status": "audiobookshelf_imported",
                "whatsapp": {
                    "sender_ref": "4368120864006",
                    "session_ref": "session-1",
                    "public_share_delivery": {"status": "sent"},
                },
                "audiobookshelf_import": {
                    "status": "imported",
                    "public_share": {
                        "status": "public_share_ready",
                        "absolute_url": "https://audiobookshelf.example/share/demo",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    def _probe(**_: object) -> dict[str, object]:
        return {
            "contract_name": module.CONTRACT_NAME,
            "checked_at": "2026-06-21T00:00:00Z",
            "status": "pass",
            "browser": "chromium_playwright",
            "track_response_status": 206,
            "track_content_type": "audio/mp4",
            "duration_seconds": 120.0,
            "current_time_after_play_seconds": 2.5,
            "media_error": False,
            "raw_url_exposed": False,
        }

    result = module.record_playback_e2e(job_path=job_path, probe=_probe)

    assert result["passed"] is True
    assert result["status"] == "pass"
    assert result["public_share_host"] == "audiobookshelf.example"
    assert result["public_share_url_sha256"]
    assert result["raw_url_exposed"] is False
    assert "https://audiobookshelf.example/share/demo" not in json.dumps(result, sort_keys=True)

    updated = json.loads(job_path.read_text(encoding="utf-8"))
    playback = updated["audiobookshelf_import"]["public_share"]["playback_e2e"]
    assert playback["status"] == "pass"
    assert playback["track_response_status"] == 206
    assert playback["current_time_after_play_seconds"] == 2.5
