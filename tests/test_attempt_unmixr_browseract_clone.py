from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "attempt_unmixr_browseract_clone.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("attempt_unmixr_browseract_clone", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_summarize_parses_ui_counts() -> None:
    module = _load_module()
    summary = module._summarize(
        "Monthly profiles\n0 / 4\nRemaining\n4\nSaved voices\n0\nNo voice clones found.\n"
    )
    assert summary["monthly_used"] == 0
    assert summary["monthly_limit"] == 4
    assert summary["remaining"] == 4
    assert summary["saved_voices"] == 0
    assert summary["no_voice_clones_found"] is True


def test_attempt_clone_writes_report(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"audio")

    screenshot = tmp_path / "preview.png"
    html = tmp_path / "result.html"
    screenshot.write_bytes(b"png")
    html.write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(
        module,
        "_run_playwright",
        lambda *args, **kwargs: {
            "_worker_exit_code": 0,
            "url": "https://app.unmixr.com/voice-cloning",
            "title": "Voice Cloning",
            "clone_submit_clicked": True,
            "clone_created": False,
            "clone_visible": False,
            "clone_names": [],
            "ui_limit_blocked": True,
            "ui_limit_detail": "reached_the_limit",
            "monthly_profiles_text": "0 / 4",
            "remaining_text": "4",
            "saved_voices_text": "0",
            "warnings": [],
            "errors": [],
            "api_hits": [{"url": "https://unmixr.com/api/voice-cloning-profile/", "status": 200, "body_excerpt": "{\"count\":1}"}],
            "discovered_voice_ids": ["voice-123"],
            "discovered_profile_ids": ["profile-123"],
            "body_text": "Monthly profiles\n0 / 4\nRemaining\n4\nSaved voices\n0\nNo voice clones found.\n",
            "screenshot_path": str(screenshot),
            "html_path": str(html),
        },
    )
    monkeypatch.setattr(
        module,
        "_probe_unmixr_runtime",
        lambda **kwargs: [{"voice_id": "profile-123", "runtime_ready": False, "message": "Internal Server Error"}],
    )

    result = module.attempt_clone(
        login_email="user@example.com",
        login_password="secret",
        reference_audio_path=audio,
        voice_label="ManfredHozaR2",
        description="desc",
        output_dir=tmp_path / "out",
        timeout_seconds=120,
    )

    payload = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert payload["ui_limit_blocked"] is True
    assert payload["slot_summary"]["remaining"] == 4
    assert payload["reference_audio_size_bytes"] == 5
    assert payload["api_hits"][0]["status"] == 200
    assert payload["discovered_voice_ids"] == ["voice-123"]
    assert payload["discovered_profile_ids"] == ["profile-123"]
    assert payload["runtime_probes"][0]["runtime_ready"] is False
